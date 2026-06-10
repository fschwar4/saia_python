"""ARCANA (RAG) service — manage knowledge bases and chat with context."""

from __future__ import annotations

import json
import uuid as _uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import cast
from urllib.parse import quote

import requests

from ._http import (
    DEFAULT_TIMEOUT,
    RetryPolicy,
    coerce_retry,
    new_session_like,
    post_chat_completion,
)
from ._streaming import SSEStream
from ._util import progress_iter
from .exceptions import APIError, raise_for_status

_ARCANA_PATH = "/arcanas/api/v1"


def extract_arcana_name(id_or_name: str) -> str:
    """Extract the arcana name from a full ID or plain name.

    The ARCANA chat endpoint uses the full ``owner/name`` format, while
    management endpoints (``get``, ``upload``) use just the ``name``.
    This function accepts either and returns the name part.

    Args:
        id_or_name: Either ``"owner/name"`` or just ``"name"``.

    Returns:
        The name portion (everything after the first ``/``, or the
        input unchanged if there is no ``/``).
    """
    if "/" in id_or_name:
        return id_or_name.split("/", 1)[1]
    return id_or_name


def _json_or_none(resp) -> dict | None:
    """Return ``resp.json()``, or ``None`` when the body is empty / not JSON.

    Several ARCANA management endpoints (delete, upload, delete-index, …) may
    answer with an empty or non-JSON body on success; this collapses the
    repeated decode-or-``None`` ``try/except`` they all used.
    """
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        return None


class ArcanaService:
    """Access the ARCANA/RAG endpoints.

    The ARCANA API uses a different auth scheme (plain key, no ``Bearer`` prefix)
    and a different URL path. This is handled automatically.

    Args:
        session: A :class:`requests.Session` (auth header will be overridden per-request).
        base_url: The SAIA API base URL (e.g. ``https://chat-ai.academiccloud.de/v1``).
        api_key: The raw API key (needed because ARCANA omits the ``Bearer`` prefix).
        timeout: Default ``(connect, read)`` timeout in seconds applied to every
            ARCANA management request that does not set its own. Guards against
            the server accepting a request but never responding (e.g. while an
            arcana is locked mid-(re)index), which would otherwise block forever
            on the socket read. A single ``float`` applies to both phases; pass
            ``None`` to disable. Defaults to ``(10, 60)``. The long-running chat
            path (:meth:`chat`) is exempt.
    """

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        api_key: str,
        *,
        timeout: float | tuple[float, float] | None = DEFAULT_TIMEOUT,
        retry: RetryPolicy | bool | None = None,
    ):
        self._session = session
        self._base_url = base_url
        self._arcana_base = f"{self._base_url}{_ARCANA_PATH}"
        self._api_key = api_key
        self._timeout = timeout
        self._retry = coerce_retry(retry)

    def _headers(self, **extra) -> dict:
        return {"Authorization": self._api_key, "Accept": "application/json", **extra}

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Issue a request on the shared session with a default timeout.

        A plain :class:`requests.Session` has no default timeout, so any ARCANA
        management call that forgets ``timeout=`` blocks forever on the socket
        read when the server accepts the request but never responds — common
        while an arcana is locked mid-(re)index. Routing every such call through
        here injects :attr:`_timeout` unless an explicit ``timeout`` was passed
        (so :meth:`heartbeat` and :meth:`generate_index` keep their own), so
        calls fail fast with :class:`requests.Timeout` instead of hanging. That
        error is *not* swallowed here — it propagates to the caller (the batch
        helpers record it per file and carry on).

        ``method`` is the lowercase HTTP verb (``"get"``, ``"post"``, ``"put"``,
        ``"delete"``); dispatching through the verb attribute keeps the call
        shape the rest of the code — and the tests — already rely on.
        """
        kwargs.setdefault("timeout", self._timeout)
        return getattr(self._session, method)(url, **kwargs)

    @staticmethod
    def _format_arcana_line(a: dict, *, with_owner: bool = False) -> str:
        """Format one arcana as a one-line summary (shared by the summary views)."""
        idx = a.get("index_info") or {}
        status = idx.get("index_status", "?")
        if with_owner:
            return (
                f"  {a['name']}  "
                f"(owner: {a.get('owner_user_name', '?')}, "
                f"files: {a.get('file_count', '?')}, "
                f"status: {status})"
            )
        return f"  {a['name']}  (files: {a.get('file_count', '?')}, status: {status})"

    @staticmethod
    def _glob_files(
        directory: str | Path, pattern: str, *, recursive: bool
    ) -> list[Path]:
        """Return the sorted matching files in ``directory``.

        Raises:
            FileNotFoundError: If ``directory`` is not a directory, or nothing
                matches ``pattern``.
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"Directory not found: {directory}")
        glob_method = directory.rglob if recursive else directory.glob
        files = sorted(p for p in glob_method(pattern) if p.is_file())
        if not files:
            raise FileNotFoundError(f"No files matching '{pattern}' in {directory}")
        return files

    def _run_file_batch(
        self,
        files: list[Path],
        action: Callable[[Path], object],
        *,
        default_status: str,
        desc: str,
        verbose: bool,
        show_progress: bool = True,
        print_summary: bool = True,
        on_result: Callable[[Path, dict], None] | None = None,
    ) -> list[dict]:
        """Apply ``action`` to each file, collecting one outcome entry per file.

        The single executor behind every multi-file operation —
        :meth:`upload_directory`, :meth:`upload_files`, :meth:`delete_directory`,
        and the apply pass of :meth:`sync_directory`. It owns exactly the
        concerns those share: iteration, an optional progress bar, per-file
        error capture, the ``on_result`` callback, and the verbose tally. No
        caller reimplements this loop.

        ``action(path)`` performs the work for one file. If it returns a ``str``
        that value is recorded as the file's ``status`` (e.g. ``"replaced"`` vs
        ``"uploaded"``); any other return value (an API response dict, ``None``)
        records ``default_status``. Any exception is caught, recorded as
        ``"failed"`` with the stringified error, and iteration continues.

        Args:
            default_status: Status recorded when ``action`` does not return a
                ``str`` — the common upload/delete case, where the action
                returns the API response.
            show_progress: Wrap the loop in a tqdm bar (default). Pass ``False``
                for callers that drive their own reporting (e.g.
                :meth:`sync_directory`).
            print_summary: Print the ``N/M files <status>`` tally when
                ``verbose`` (default). Pass ``False`` for callers that print a
                richer summary of their own.
            on_result: If given, called as ``on_result(path, entry)`` after each
                file (``entry`` is that file's ``{"file", "status", ["error"]}``
                dict), so callers can stream per-file provenance / transaction
                logging without reimplementing the loop.
        """
        iterator = (
            progress_iter(files, desc=desc, unit="file") if show_progress else files
        )
        results: list[dict] = []
        for fp in iterator:
            entry: dict = {"file": fp.name}
            try:
                label = action(fp)
                entry["status"] = label if isinstance(label, str) else default_status
            except Exception as e:
                entry["status"] = "failed"
                entry["error"] = str(e)
            if verbose:
                line = f"  {fp.name}  {entry['status']}"
                if entry["status"] == "failed":
                    line += f" ({entry['error']})"
                print(line)
            if on_result is not None:
                on_result(fp, entry)
            results.append(entry)

        if verbose and print_summary:
            succeeded = sum(1 for r in results if r["status"] != "failed")
            failed = len(results) - succeeded
            summary = f"{succeeded}/{len(results)} files {default_status}"
            if failed:
                summary += f" ({failed} failed)"
            print(summary)
        return results

    def version(self) -> str:
        """Return the ARCANA API version string.

        Calls ``GET /arcanas/api/v1/version``.

        Returns:
            The version string (e.g. ``"0.4.16"``).
        """
        resp = self._request(
            "get", f"{self._arcana_base}/version", headers=self._headers()
        )
        raise_for_status(resp)
        return resp.json().get("version", "")

    def heartbeat(self) -> bool:
        """Check whether the ARCANA service is alive.

        Calls ``GET /arcanas/api/v1/heartbeat``. Returns ``True`` if the
        service responds with 204, ``False`` otherwise (including transport
        errors — it never raises).
        """
        try:
            resp = self._request(
                "get",
                f"{self._arcana_base}/heartbeat",
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 204
        except Exception:
            return False

    def user_info(self) -> dict:
        """Return the current user's profile and arcana statistics.

        Calls ``GET /user/me``. Returns username, email, name, arcana
        count, file count, and registration date.

        Returns:
            A dict with user profile fields.
        """
        resp = self._request(
            "get",
            f"{self._arcana_base}/user/me",
            headers=self._headers(),
        )
        raise_for_status(resp)
        return resp.json()

    def user_summary(self) -> str:
        """Return a formatted overview of the user's account and all arcanas.

        Combines :meth:`user_info` and :meth:`list` into a single
        human-readable string.

        Returns:
            A multi-line summary.
        """
        user = self.user_info()
        arcanas = self.list()

        _W = 18
        lines = [
            f"{'Username':<{_W}}{user.get('username', '?')}",
            f"{'Email':<{_W}}{user.get('email', '?')}",
            f"{'Name':<{_W}}{user.get('first_name', '')} {user.get('surname', '')}".rstrip(),
            f"{'Registered':<{_W}}{user.get('is_registered', '?')}",
            f"{'Arcana count':<{_W}}{user.get('arcana_count', '?')}",
            f"{'Total files':<{_W}}{user.get('file_count', '?')}",
        ]
        if user.get("created_at"):
            lines.append(f"{'Member since':<{_W}}{user['created_at']}")

        lines.append(f"\nArcanas ({len(arcanas)}):")
        for a in arcanas:
            lines.append(self._format_arcana_line(a))
        if not arcanas:
            lines.append("  (none)")

        return "\n".join(lines)

    def create(
        self,
        name: str,
        *,
        append_uuid: bool = True,
        update_toml: bool = False,
        toml_label: str | None = None,
    ) -> dict:
        """Create a new arcana.

        Args:
            name: Name for the new arcana (1–100 characters).
            append_uuid: If ``True`` (default), append a UUID4 suffix to
                the name (e.g. ``MyArcana-a1b2c3d4-...``). This mirrors
                the behavior of the SAIA web UI and avoids name collisions.
            update_toml: If ``True``, add the new arcana to ``config.toml``
                after creation.
            toml_label: Label under ``[saia.arcana.labels]`` in config.toml.
                If omitted, the ID is appended to the ``ids`` array.

        Returns:
            A dict with the created arcana name and the full ID
            (``owner/name``).
        """
        if append_uuid:
            name = f"{name}-{_uuid.uuid4()}"

        resp = self._request(
            "post",
            f"{self._arcana_base}/arcana/",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"name": name},
        )
        raise_for_status(resp)

        # Build the full owner/name ID
        # Fetch details to get the owner_user_name
        details = self.get(name)
        owner = details.get("owner_user_name", "")
        full_id = f"{owner}/{name}" if owner else name

        result = {"name": name, "id": full_id, "message": resp.json()}

        if update_toml:
            from .auth import add_arcana_to_config

            add_arcana_to_config(full_id, label=toml_label)

        return result

    def delete(
        self,
        name: str,
        *,
        update_toml: bool = False,
    ) -> dict | None:
        """Delete an arcana entirely.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            update_toml: If ``True``, remove the arcana from ``config.toml``
                after deletion.

        Returns:
            The API response, or ``None`` if the response has no body.
        """
        # Keep the full ID for config removal before extracting the name
        full_id = name
        name = extract_arcana_name(name)

        resp = self._request(
            "delete",
            f"{self._arcana_base}/arcana/{quote(name, safe='')}",
            headers=self._headers(),
        )
        raise_for_status(resp)

        if update_toml:
            from .auth import remove_arcana_from_config

            # Try both formats (full ID and plain name)
            remove_arcana_from_config(full_id)
            if full_id != name:
                remove_arcana_from_config(name)

        return _json_or_none(resp)

    def list(self) -> list[dict]:
        """List all available arcanas.

        Returns:
            A list of arcana dicts.
        """
        resp = self._request(
            "get",
            f"{self._arcana_base}/arcana/",
            headers=self._headers(),
        )
        raise_for_status(resp)
        return resp.json()

    def summary(self, *, arcana_ids: dict[str, str] | None = None) -> str:
        """Return a formatted summary of configured and available arcanas.

        Combines information from :func:`~saia_python.load_arcana_ids`
        (configured IDs) and :meth:`list` (server-side arcanas) into a
        single human-readable string.

        Args:
            arcana_ids: Optional pre-loaded dict from
                :func:`~saia_python.load_arcana_ids`. If omitted, loaded
                automatically.

        Returns:
            A multi-line summary string.
        """
        if arcana_ids is None:
            from .auth import load_arcana_ids

            arcana_ids = load_arcana_ids()

        lines = []

        # Configured IDs
        if arcana_ids:
            lines.append(f"Configured ARCANA IDs ({len(arcana_ids)}):")
            default_id = arcana_ids.get("default", "")
            if default_id:
                name_part = extract_arcana_name(default_id)
                lines.append(f"  Default ID    {default_id}")
                lines.append(f"  Default name  {name_part}")
            for label, aid in arcana_ids.items():
                if label != "default":
                    lines.append(f"  [{label}]  {aid}")
        else:
            lines.append("No ARCANA IDs configured.")

        # Server-side arcanas
        arcanas = self.list()
        lines.append(f"\nAvailable on server ({len(arcanas)}):")
        if arcanas:
            for a in arcanas:
                lines.append(self._format_arcana_line(a, with_owner=True))
        else:
            lines.append("  (none)")

        return "\n".join(lines)

    def get(self, name: str) -> dict:
        """Retrieve details of a specific arcana.

        Accepts either the plain name or the full ``owner/name`` ID —
        the owner prefix is stripped automatically.

        Args:
            name: The arcana name or full ``owner/name`` ID.

        Returns:
            Arcana details dict.
        """
        name = extract_arcana_name(name)
        resp = self._request(
            "get",
            f"{self._arcana_base}/arcana/{quote(name, safe='')}",
            headers=self._headers(),
        )
        raise_for_status(resp)
        return resp.json()

    def info(
        self,
        name: str | None = None,
        *,
        data: dict | None = None,
        verbose: bool = False,
    ) -> str:
        """Return a formatted summary of an arcana's details.

        Args:
            name: The arcana name or full ``owner/name`` ID. Can be omitted
                if ``data`` is provided.
            data: Optional pre-fetched arcana dict (from :meth:`get`).
                Avoids a redundant API call when you already have the data.
            verbose: If ``True``, include additional fields (CLI version,
                vector DB version, error message if present).

        Returns:
            A human-readable multi-line string.
        """
        if data is None:
            if name is None:
                raise ValueError("Either name or data must be provided")
            data = self.get(name)
        idx = data.get("index_info") or {}

        def _size_fmt(n: float) -> str:
            for unit in ("B", "KB", "MB", "GB"):
                if abs(n) < 1024:
                    return f"{n:.1f} {unit}"
                n /= 1024
            return f"{n:.1f} TB"

        _W = 18  # label column width
        lines = [
            f"{'Name':<{_W}}{data.get('name', '?')}",
            f"{'Owner':<{_W}}{data.get('owner_user_name', '?')}",
            f"{'Files':<{_W}}{data.get('file_count', '?')} ({_size_fmt(data.get('size', 0))})",
            f"{'Index status':<{_W}}{idx.get('index_status', '?')}",
            f"{'Embeddings model':<{_W}}{idx.get('embeddings_model', '?')}",
            f"{'Files indexed':<{_W}}{idx.get('total_files_indexed', '?')}",
            f"{'Chunks indexed':<{_W}}{idx.get('total_chunks_indexed', '?')}",
            f"{'Created':<{_W}}{data.get('created_at', '?')}",
            f"{'Updated':<{_W}}{data.get('updated_at', '?')}",
        ]

        if verbose:
            if idx.get("error_msg") is not None:
                lines.insert(4, f"{'Error':<{_W}}{idx['error_msg']}")
            lines.append(f"{'CLI version':<{_W}}{idx.get('cli_version', '?')}")
            lines.append(
                f"{'Vector DB version':<{_W}}{idx.get('vector_db_version', '?')}"
            )

        return "\n".join(lines)

    def upload(
        self, name: str, file_path: str | Path, *, overwrite: bool = False
    ) -> dict | None:
        """Upload a file to an arcana for indexing.

        Supported formats: PDF, text, markdown. Accepts either the plain
        name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            file_path: Path to the file to upload.
            overwrite: If ``True``, replace an existing file with the same
                name (uses PUT instead of POST).

        Returns:
            The API response (may be ``None`` on success per the API spec).
        """
        name = extract_arcana_name(name)
        file_path = Path(file_path)
        base = f"{self._arcana_base}/arcana/{quote(name, safe='')}/files"
        with open(file_path, "rb") as f:
            if overwrite:
                resp = self._request(
                    "put",
                    f"{base}/{quote(file_path.name, safe='')}",
                    headers=self._headers(),
                    files={"file": (file_path.name, f)},
                )
            else:
                resp = self._request(
                    "post",
                    f"{base}/",
                    headers=self._headers(),
                    files={"file": (file_path.name, f)},
                )
        raise_for_status(resp)
        return _json_or_none(resp)

    def upload_directory(
        self,
        name: str,
        directory: str | Path,
        *,
        pattern: str = "*",
        recursive: bool = False,
        overwrite: bool = False,
        verbose: bool = False,
        on_result: Callable[[Path, dict], None] | None = None,
    ) -> list[dict]:
        """Upload all files in a directory to an arcana.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            directory: Path to the directory containing files to upload.
            pattern: Glob pattern to filter files (default ``"*"`` — all files).
                For example, ``"*.pdf"`` to upload only PDFs.
            recursive: If ``True``, search subdirectories recursively
                (uses ``**/<pattern>``).
            overwrite: If ``True``, replace existing files with the same name.
            verbose: If ``True``, print per-file upload status.
            on_result: Optional callback invoked as ``on_result(local_path,
                entry)`` after each file (``entry`` is that file's
                ``{"file", "status", ["error"]}`` dict), for inline per-file
                provenance / transaction logging.

        Returns:
            A list of dicts with keys ``"file"`` (filename only),
            ``"status"`` (``"uploaded"`` or ``"failed"``), and
            ``"error"`` (message string, only present on failure).
        """
        files = self._glob_files(directory, pattern, recursive=recursive)
        return self._run_file_batch(
            files,
            lambda fp: self.upload(name, fp, overwrite=overwrite),
            default_status="uploaded",
            desc="Uploading",
            verbose=verbose,
            on_result=on_result,
        )

    def upload_files(
        self,
        name: str,
        paths: Iterable[str | Path],
        *,
        overwrite: bool = True,
        verbose: bool = False,
        on_result: Callable[[Path, dict], None] | None = None,
    ) -> list[dict]:
        """Upload an explicit, caller-chosen list of files to an arcana.

        Unlike :meth:`upload_directory` (which globs a whole directory), this
        uploads exactly the ``paths`` you pass — so the *selection* of what to
        (re)upload is entirely the caller's decision (e.g. the result of your
        own changed-file / checksum comparison). Pair it with
        :meth:`list_files` (whose dicts carry per-file ``index_info``) and a
        single :meth:`generate_index` afterwards.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            paths: An iterable of paths to upload.
            overwrite: If ``True`` (default), replace existing files (PUT); if
                ``False``, create new files (POST). Defaults to ``True`` because
                the typical caller has already decided these files are new or
                changed.
            verbose: If ``True``, print per-file upload status.
            on_result: Optional callback invoked as ``on_result(local_path,
                entry)`` after each file (``entry`` is that file's
                ``{"file", "status", ["error"]}`` dict). Lets a caller record
                per-file provenance (e.g. a git SHA) or a transaction-log entry
                as each upload completes, without reimplementing this loop.

        Returns:
            A list of ``{"file", "status", ["error"]}`` dicts — the same shape
            as :meth:`upload_directory`.
        """
        files = [Path(p) for p in paths]
        return self._run_file_batch(
            files,
            lambda fp: self.upload(name, fp, overwrite=overwrite),
            default_status="uploaded",
            desc="Uploading",
            verbose=verbose,
            on_result=on_result,
        )

    def list_files(self, name: str) -> list[dict]:
        """List all files in an arcana.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.

        Returns:
            A list of file dicts (the API ``FileOutSchema``). Each entry has:

            - ``name`` (str): file name — use with :meth:`download_file`,
              :meth:`delete_file`, or an ``overwrite`` upload.
            - ``size`` (int): size in bytes.
            - ``owner_user_name`` (str): the owning user.
            - ``created_at`` / ``updated_at`` (str): ISO-8601 timestamps.
            - ``index_info`` (dict | None): per-file index state, or ``None``
              if the file has never been indexed. When present it holds
              ``index_status`` (str — e.g. ``"INDEXED"``, ``"NOT_INDEXED"``,
              ``"ERROR"``) and ``chunks_indexed`` (int — number of embedding
              chunks produced for the file).
            - ``related_files`` (list | None): nested entries of the same
              shape, when the server groups derived files together.

            The per-file ``index_info`` lets callers see which files are
            already indexed without doing any work. Indexing itself is
            triggered per-arcana via :meth:`generate_index` — the ARCANA API
            has no per-file index call.
        """
        name = extract_arcana_name(name)
        resp = self._request(
            "get",
            f"{self._arcana_base}/arcana/{quote(name, safe='')}/files/",
            headers=self._headers(),
        )
        raise_for_status(resp)
        return resp.json()

    def delete_file(self, name: str, file_name: str) -> dict | None:
        """Delete a file from an arcana.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            file_name: The name of the file to delete (as returned by
                :meth:`list_files`).

        Returns:
            The API response, or ``None`` if the response has no body.
        """
        name = extract_arcana_name(name)
        resp = self._request(
            "delete",
            f"{self._arcana_base}/arcana/{quote(name, safe='')}/files/{quote(file_name, safe='')}",
            headers=self._headers(),
        )
        raise_for_status(resp)
        return _json_or_none(resp)

    def download_file(self, name: str, file_name: str, output_path: str | Path) -> Path:
        """Download a file from an arcana to a local path.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            file_name: The name of the file to download (as returned
                by :meth:`list_files`).
            output_path: Local path to save the file to.

        Returns:
            The path the file was written to.
        """
        name = extract_arcana_name(name)
        resp = self._request(
            "get",
            f"{self._arcana_base}/arcana/{quote(name, safe='')}/files/{quote(file_name, safe='')}/download",
            headers=self._headers(),
            stream=True,
        )
        raise_for_status(resp)
        output_path = Path(output_path)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path

    def delete_directory(
        self,
        name: str,
        directory: str | Path,
        *,
        pattern: str = "*",
        recursive: bool = False,
        verbose: bool = False,
        on_result: Callable[[Path, dict], None] | None = None,
    ) -> list[dict]:
        """Delete files from an arcana that match filenames in a local directory.

        Finds all files in ``directory`` matching ``pattern``, then deletes
        files with the same **name** from the arcana. Useful for removing
        a batch of files that were previously uploaded with
        :meth:`upload_directory`.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            directory: Local directory whose filenames to match.
            pattern: Glob pattern to filter files (default ``"*"``).
            recursive: If ``True``, search subdirectories recursively.
            verbose: If ``True``, print per-file deletion status.
            on_result: Optional callback invoked as ``on_result(local_path,
                entry)`` after each file (``entry`` is that file's
                ``{"file", "status", ["error"]}`` dict), for inline per-file
                logging.

        Returns:
            A list of dicts with keys ``"file"`` (filename only),
            ``"status"`` (``"deleted"`` or ``"failed"``), and
            ``"error"`` (only present on failure).
        """
        files = self._glob_files(directory, pattern, recursive=recursive)
        return self._run_file_batch(
            files,
            lambda fp: self.delete_file(name, fp.name),
            default_status="deleted",
            desc="Deleting",
            verbose=verbose,
            on_result=on_result,
        )

    def sync_directory(
        self,
        name: str,
        directory: str | Path,
        *,
        select: Callable[[Path, dict | None], str],
        pattern: str = "*",
        recursive: bool = False,
        prune: bool = False,
        index: bool = True,
        index_wait: bool = True,
        verbose: bool = False,
        on_result: Callable[[Path, dict], None] | None = None,
    ) -> dict:
        """Sync a local directory into an arcana under caller-defined rules.

        The *policy* — which files to upload, replace, or skip — stays entirely
        outside the package: you supply a ``select`` callback that decides per
        file. This method only does the plumbing: glob the directory, fetch the
        remote listing, apply your decisions, and (optionally) trigger a single
        index pass. ARCANA stores no content hash, so any content-change
        detection (e.g. SHA-256 against your own manifest) belongs in
        ``select``.

        The single index pass is efficient because the server only (re)embeds
        files that are not already ``INDEXED`` — see :meth:`generate_index`.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            directory: Local directory to sync from.
            select: Called once per local file as ``select(local_path, remote)``
                where ``local_path`` is a :class:`pathlib.Path` and ``remote``
                is the matching file dict from :meth:`list_files` (matched by
                name) or ``None`` if the file is not in the arcana yet. Must
                return ``"upload"`` (POST new), ``"replace"`` (PUT over an
                existing file), or ``"skip"``.
            pattern: Glob pattern for local files (default ``"*"``).
            recursive: If ``True``, recurse into subdirectories.
            prune: If ``True``, delete remote files that have no local
                counterpart by name. Defaults to ``False`` (never deletes
                implicitly).
            index: If ``True`` (default), call :meth:`generate_index` once after
                the sync — but only when something actually changed.
            index_wait: Forwarded to :meth:`generate_index` as ``wait``.
            verbose: If ``True``, print per-file actions and a summary.
            on_result: Optional callback invoked as ``on_result(local_path,
                entry)`` for each *local* file as it is uploaded, replaced, or
                skipped (``entry`` mirrors the batch-helper shape:
                ``{"file", "status", ["error"]}``, where ``status`` is one of
                ``"uploaded"`` / ``"replaced"`` / ``"skipped"`` / ``"failed"``).
                Lets callers record per-file provenance / transaction logs
                inline. Not called for ``prune`` deletions (those are
                remote-only).

        Returns:
            A report ``dict`` with keys ``"uploaded"``, ``"replaced"``,
            ``"skipped"``, ``"deleted"`` (lists of file names), ``"failed"``
            (list of ``{"file", "error"}``) and ``"index"`` (the
            :meth:`generate_index` result, or ``None`` if indexing was skipped).

        Raises:
            ValueError: If ``select`` returns anything other than ``"upload"``,
                ``"replace"``, or ``"skip"``.
        """
        local_files = self._glob_files(directory, pattern, recursive=recursive)
        # cast: `list_files` returns list[dict], but the `.list` method on this
        # class shadows the builtin in annotations (see the mypy override), so
        # mypy mis-types the return — cast restores `list` here.
        remote_files = cast(list, self.list_files(name))
        remote_by_name = {f["name"]: f for f in remote_files}

        # Pass 1 — policy. Ask the caller what to do with each local file,
        # against the remote state as it is *before* any upload. Raises on a
        # bad decision before any I/O is done.
        valid = {"upload", "replace", "skip"}
        plan: dict[Path, str] = {}
        for path in local_files:
            decision = select(path, remote_by_name.get(path.name))
            if decision not in valid:
                raise ValueError(
                    f"select() must return one of {sorted(valid)}; "
                    f"got {decision!r} for {path.name}"
                )
            plan[path] = decision

        # Pass 2 — execute via the shared batch executor. The action maps each
        # planned decision to the work plus the status label to record; "skip"
        # does no I/O. Error capture, on_result, and per-file verbose output are
        # the executor's job — sync only supplies the per-file decision.
        def _apply(path: Path) -> str:
            decision = plan[path]
            if decision == "skip":
                return "skipped"
            self.upload(name, path, overwrite=(decision == "replace"))
            return "replaced" if decision == "replace" else "uploaded"

        entries = self._run_file_batch(
            local_files,
            _apply,
            default_status="uploaded",
            desc="Syncing",
            verbose=verbose,
            show_progress=False,  # sync prints its own richer summary below
            print_summary=False,
            on_result=on_result,
        )

        # Aggregate the flat outcomes into the categorized report — a groupby
        # view of the entries, which is sync's own output contract.
        report: dict = {
            "uploaded": [],
            "replaced": [],
            "skipped": [],
            "deleted": [],
            "failed": [],
            "index": None,
        }
        for e in entries:
            if e["status"] == "failed":
                report["failed"].append({"file": e["file"], "error": e["error"]})
            else:
                report[e["status"]].append(e["file"])

        if prune:
            local_names = {p.name for p in local_files}
            for remote_name in remote_by_name:
                if remote_name in local_names:
                    continue
                try:
                    self.delete_file(name, remote_name)
                    report["deleted"].append(remote_name)
                    if verbose:
                        print(f"  {remote_name}  deleted")
                except Exception as e:
                    report["failed"].append({"file": remote_name, "error": str(e)})

        if index and (report["uploaded"] or report["replaced"] or report["deleted"]):
            report["index"] = self.generate_index(name, wait=index_wait)

        if verbose:
            print(
                f"sync: {len(report['uploaded'])} uploaded, "
                f"{len(report['replaced'])} replaced, "
                f"{len(report['skipped'])} skipped, "
                f"{len(report['deleted'])} deleted, "
                f"{len(report['failed'])} failed"
            )
        return report

    def generate_index(
        self,
        name: str,
        *,
        wait: bool = True,
        timeout: int = 600,
        poll_interval: int = 5,
    ) -> dict | None:
        """Trigger index generation for an arcana.

        By default this blocks until indexing completes (synchronous).
        For large arcanas the server may time out (504). Use
        ``wait=False`` to fire the request and return immediately,
        then poll with :meth:`info` to check the index status.

        Args:
            name: The arcana name or full ``owner/name`` ID.
            wait: If ``True`` (default), poll until indexing finishes.
                If ``False``, fire the request and return immediately.
            timeout: Maximum seconds to wait when ``wait=True``.
                Defaults to 600 (10 minutes).
            poll_interval: Seconds between status checks when ``wait=True``.
                Defaults to 5.

        Returns:
            The arcana details dict (from :meth:`get`) when ``wait=True``
            and indexing completed, or ``None`` when ``wait=False`` or
            on timeout.

        Raises:
            TimeoutError: If ``wait=True`` and indexing does not complete
                within ``timeout`` seconds.

        Note:
            Indexing is incremental on the server: files already at
            ``index_status == "INDEXED"`` are skipped, so only files added or
            replaced since the last index (an upload resets a file to
            ``NOT_INDEXED``) are (re)embedded. This is why the efficient pattern
            is *upload only the changed files, then call this once* — the single
            whole-arcana trigger re-embeds just those. The library relies on
            this skip-``INDEXED`` behavior; if the server ever stops skipping,
            the call stays correct but re-embeds the whole arcana.
        """
        import threading
        import time

        resolved = extract_arcana_name(name)
        url = f"{self._arcana_base}/arcana/{quote(resolved, safe='')}/generate-index"

        if not wait:
            # Fire-and-forget: send the trigger on a background thread so we
            # return to the caller immediately. It uses its OWN Session — the
            # caller polls via info()/get() on the shared client Session, and
            # requests.Session is not safe to use from two threads at once.
            def _fire():
                session = new_session_like(self._session)
                try:
                    session.post(url, headers=self._headers(), timeout=600)
                except Exception:
                    pass  # indexing status is checked via info()/get()
                finally:
                    session.close()

            threading.Thread(target=_fire, daemon=True).start()
            return None

        # Synchronous: fire the request, tolerate transport-level failures, then poll
        try:
            resp = self._request("post", url, headers=self._headers(), timeout=30)
            raise_for_status(resp)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            # The trigger almost certainly reached the server (the body
            # was written before the response was dropped). ARCANA
            # commonly holds the trigger connection while it builds the
            # embedding queue, then closes it without a response. The
            # arcana state machine is authoritative — fall through to
            # the poll loop. Sanity-check with a GET first: if that
            # also fails at the transport level, the server is
            # genuinely down and the error propagates.
            self.get(name)
        except APIError as e:
            # 504 Gateway Timeout from nginx is the same shape: trigger
            # accepted, gateway gave up waiting for a response.
            if e.status_code != 504:
                raise

        # Poll until indexing finishes. Tolerate transient transport failures on
        # an individual poll (the index keeps building server-side) so a slow or
        # dropped poll GET — now that control-plane calls carry a default
        # timeout — cannot abort a long, still-progressing reindex. Only the
        # overall ``timeout`` deadline ends the wait; each retry is paced by the
        # poll_interval sleep, so a genuinely-down server still gives up at the
        # deadline.
        deadline = time.monotonic() + timeout
        terminal = {"INDEXED", "ERROR", "NOT_INDEXED"}
        status = ""
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                data = self.get(name)
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as e:
                last_error = e  # transient — remember it, retry on the next poll
                continue
            last_error = None  # a successful poll clears any prior transient error
            idx = data.get("index_info") or {}
            status = idx.get("index_status", "")
            if status in terminal:
                return data

        # Deadline exhausted. Surface whichever signal we actually have — the
        # last-seen status (slow indexing) and/or the last transport error
        # (polls that kept failing) — so the timeout is diagnosable rather than
        # reporting an empty status.
        msg = f"Indexing did not complete within {timeout}s."
        if status:
            msg += f" Last status: {status}."
        if last_error is not None:
            msg += f" Last poll error: {last_error!r}."
        msg += " Check with client.arcana.info(...)."
        raise TimeoutError(msg)

    def delete_index(self, name: str) -> dict | None:
        """Delete the index of an arcana.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.

        Returns:
            The API response, or ``None`` if the response has no body.
        """
        name = extract_arcana_name(name)
        resp = self._request(
            "delete",
            f"{self._arcana_base}/arcana/{quote(name, safe='')}/delete-index",
            headers=self._headers(),
        )
        raise_for_status(resp)
        return _json_or_none(resp)

    def setup_from_directory(
        self,
        name: str,
        source_dir: str | Path,
        *,
        pattern: str = "*.md",
        append_uuid: bool = True,
        update_toml: bool = False,
        toml_label: str | None = None,
        wait_for_index: bool = True,
        index_timeout: int = 600,
        verbose: bool = True,
    ) -> dict:
        """End-to-end: create an arcana, upload a directory, build the index.

        Composes :meth:`create`, :meth:`upload_directory`, and
        :meth:`generate_index` into a single call. The arcana name
        passed to upload + index is the one returned by ``create`` —
        i.e. with the UUID suffix when ``append_uuid=True`` (default),
        so the composition stays correct without the caller having to
        remember the renaming.

        Args:
            name: Display name for the new arcana (UUID suffix appended
                when ``append_uuid=True``).
            source_dir: Directory whose matching files should be
                uploaded to the new arcana.
            pattern: Glob pattern passed to :meth:`upload_directory`.
                Defaults to ``"*.md"``.
            append_uuid: Forwarded to :meth:`create`. If ``True``
                (default), the UUID suffix avoids name collisions and
                mirrors the SAIA web UI behaviour.
            update_toml: Forwarded to :meth:`create`. If ``True``, add
                the new arcana to ``config.toml`` after creation.
            toml_label: Label under ``[saia.arcana.labels]``.
                Ignored when ``update_toml`` is ``False``.
            wait_for_index: Forwarded to :meth:`generate_index` as
                ``wait``. If ``True`` (default), block until the index
                reaches ``INDEXED`` (or fails / times out).
            index_timeout: Forwarded to :meth:`generate_index` as
                ``timeout`` (seconds). Defaults to 600.
            verbose: Forwarded to :meth:`upload_directory`. Controls
                the per-file progress bar.

        Returns:
            A dict with three keys: ``"arcana"`` (the result from
            :meth:`create`), ``"uploads"`` (the list from
            :meth:`upload_directory`), and ``"index"`` (the result
            from :meth:`generate_index`). Callers can inspect any
            step.

        Example::

            result = client.arcana.setup_from_directory(
                "MyKB", "./markdown/",
                pattern="**/*.md",
                update_toml=True, toml_label="my_kb",
            )
            print(result["arcana"]["id"])     # owner/MyKB-<uuid>
            print(len(result["uploads"]))     # files uploaded
            print(result["index"])            # index_status
        """
        create_result = self.create(
            name,
            append_uuid=append_uuid,
            update_toml=update_toml,
            toml_label=toml_label,
        )
        arcana_name = create_result["name"]
        uploads = self.upload_directory(
            arcana_name,
            source_dir,
            pattern=pattern,
            verbose=verbose,
        )
        index = self.generate_index(
            arcana_name,
            wait=wait_for_index,
            timeout=index_timeout,
        )
        return {
            "arcana": create_result,
            "uploads": uploads,
            "index": index,
        }

    def chat(
        self,
        model: str,
        messages: list[dict],
        arcana_id: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs,
    ) -> dict | SSEStream:
        """Chat with RAG context from an arcana.

        This uses the standard ``/chat/completions`` endpoint with arcana
        parameters injected.

        Args:
            model: Model identifier.
            messages: Chat messages.
            arcana_id: The arcana ID to use for retrieval.
            stream: If ``True``, return a generator yielding chunks.
            **kwargs: Additional parameters forwarded to the API.

        Returns:
            When ``stream=False``: the API response dict, with an extra
            ``"_rate_limits"`` key (a JSON-serializable dict; see
            :class:`~saia_python.RateLimitInfo`). When ``stream=True``: an
            ``SSEStream`` whose ``rate_limits`` attribute exposes the same dict.
        """
        body = {
            "model": model,
            "messages": messages,
            "enable-tools": True,
            "arcana": {"id": arcana_id},
            **kwargs,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "inference-service": "saia-openai-gateway",
        }

        return post_chat_completion(
            self._session,
            f"{self._base_url}/chat/completions",
            body,
            headers=headers,
            stream=stream,
            policy=self._retry,
        )

    def __repr__(self):
        return f"ArcanaService(base_url={self._base_url!r})"
