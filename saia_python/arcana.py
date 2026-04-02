"""ARCANA (RAG) service — manage knowledge bases and chat with context."""

from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING, Generator, Optional
from urllib.parse import quote

from ._streaming import iter_sse
from .exceptions import APIError, raise_for_status
from .rate_limits import parse_rate_limits

if TYPE_CHECKING:
    import requests

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


class ArcanaService:
    """Access the ARCANA/RAG endpoints.

    The ARCANA API uses a different auth scheme (plain key, no ``Bearer`` prefix)
    and a different URL path. This is handled automatically.

    Args:
        session: A :class:`requests.Session` (auth header will be overridden per-request).
        base_url: The SAIA API base URL (e.g. ``https://chat-ai.academiccloud.de/v1``).
        api_key: The raw API key (needed because ARCANA omits the ``Bearer`` prefix).
    """

    def __init__(self, session: requests.Session, base_url: str, api_key: str):
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._arcana_base = f"{self._base_url}{_ARCANA_PATH}"
        self._api_key = api_key

    def _headers(self, **extra) -> dict:
        return {"Authorization": self._api_key, "Accept": "application/json", **extra}

    def user_info(self) -> dict:
        """Return the current user's profile and arcana statistics.

        Calls ``GET /user/me``. Returns username, email, name, arcana
        count, file count, and registration date.

        Returns:
            A dict with user profile fields.
        """
        resp = self._session.get(
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
            idx = a.get("index_info") or {}
            status = idx.get("index_status", "?")
            lines.append(
                f"  {a['name']}  "
                f"(files: {a.get('file_count', '?')}, status: {status})"
            )
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

        resp = self._session.post(
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

        resp = self._session.delete(
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

        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return None

    def list(self) -> list[dict]:
        """List all available arcanas.

        Returns:
            A list of arcana dicts.
        """
        resp = self._session.get(
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
                name_part = default_id.split("/", 1)[1] if "/" in default_id else default_id
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
                idx = a.get("index_info") or {}
                status = idx.get("index_status", "?")
                lines.append(
                    f"  {a['name']}  "
                    f"(owner: {a.get('owner_user_name', '?')}, "
                    f"files: {a.get('file_count', '?')}, "
                    f"status: {status})"
                )
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
        resp = self._session.get(
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

        def _size_fmt(n: int) -> str:
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
            lines.append(f"{'Vector DB version':<{_W}}{idx.get('vector_db_version', '?')}")

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
                resp = self._session.put(
                    f"{base}/{quote(file_path.name, safe='')}",
                    headers=self._headers(),
                    files={"file": (file_path.name, f)},
                )
            else:
                resp = self._session.post(
                    f"{base}/",
                    headers=self._headers(),
                    files={"file": (file_path.name, f)},
                )
        raise_for_status(resp)
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return None

    def upload_directory(
        self,
        name: str,
        directory: str | Path,
        *,
        pattern: str = "*",
        recursive: bool = False,
        overwrite: bool = False,
        verbose: bool = False,
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

        Returns:
            A list of dicts with keys ``"file"`` (filename only),
            ``"status"`` (``"uploaded"`` or ``"failed"``), and
            ``"error"`` (message string, only present on failure).
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"Directory not found: {directory}")

        glob_method = directory.rglob if recursive else directory.glob
        files = sorted(p for p in glob_method(pattern) if p.is_file())

        if not files:
            raise FileNotFoundError(
                f"No files matching '{pattern}' in {directory}"
            )

        try:
            from tqdm.auto import tqdm
        except ImportError:
            tqdm = None

        results = []
        iterator = files
        if tqdm is not None:
            iterator = tqdm(files, desc="Uploading", unit="file")

        for fp in iterator:
            entry: dict = {"file": fp.name}
            try:
                self.upload(name, fp, overwrite=overwrite)
                entry["status"] = "uploaded"
            except Exception as e:
                entry["status"] = "failed"
                entry["error"] = str(e)
            if verbose:
                status_label = "Uploaded" if entry["status"] == "uploaded" else "FAILED"
                print(f"  {fp.name}  {status_label}")
            results.append(entry)

        succeeded = sum(1 for r in results if r["status"] == "uploaded")
        failed = len(results) - succeeded
        summary = f"{succeeded}/{len(results)} files uploaded"
        if failed:
            summary += f" ({failed} failed)"
        if verbose:
            print(summary)

        return results

    def list_files(self, name: str) -> list[dict]:
        """List all files in an arcana.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.

        Returns:
            A list of file dicts.
        """
        name = extract_arcana_name(name)
        resp = self._session.get(
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
        resp = self._session.delete(
            f"{self._arcana_base}/arcana/{quote(name, safe='')}/files/{quote(file_name, safe='')}",
            headers=self._headers(),
        )
        raise_for_status(resp)
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return None

    def download_file(
        self, name: str, file_name: str, output_path: str | Path
    ) -> Path:
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
        resp = self._session.get(
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

        Returns:
            A list of dicts with keys ``"file"`` (filename only),
            ``"status"`` (``"deleted"`` or ``"failed"``), and
            ``"error"`` (only present on failure).
        """
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"Directory not found: {directory}")

        glob_method = directory.rglob if recursive else directory.glob
        filenames = sorted(
            p.name for p in glob_method(pattern) if p.is_file()
        )

        if not filenames:
            raise FileNotFoundError(
                f"No files matching '{pattern}' in {directory}"
            )

        try:
            from tqdm.auto import tqdm
        except ImportError:
            tqdm = None

        results = []
        iterator = filenames
        if tqdm is not None:
            iterator = tqdm(filenames, desc="Deleting", unit="file")

        for fn in iterator:
            entry: dict = {"file": fn}
            try:
                self.delete_file(name, fn)
                entry["status"] = "deleted"
            except Exception as e:
                entry["status"] = "failed"
                entry["error"] = str(e)
            if verbose:
                label = "Deleted" if entry["status"] == "deleted" else "FAILED"
                print(f"  {fn}  {label}")
            results.append(entry)

        succeeded = sum(1 for r in results if r["status"] == "deleted")
        failed = len(results) - succeeded
        summary = f"{succeeded}/{len(results)} files deleted"
        if failed:
            summary += f" ({failed} failed)"
        if verbose:
            print(summary)

        return results

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
        """
        import threading
        import time

        resolved = extract_arcana_name(name)
        url = f"{self._arcana_base}/arcana/{quote(resolved, safe='')}/generate-index"

        if not wait:
            # Fire-and-forget: send the request in a background thread
            # so we return to the caller immediately.
            def _fire():
                try:
                    self._session.post(url, headers=self._headers(), timeout=600)
                except Exception:
                    pass  # indexing status is checked via info()/get()

            threading.Thread(target=_fire, daemon=True).start()
            return None

        # Synchronous: fire the request, tolerate timeout/504, then poll
        try:
            resp = self._session.post(url, headers=self._headers(), timeout=30)
            raise_for_status(resp)
        except Exception as e:
            # 504 from nginx or ReadTimeout from requests both mean
            # the server accepted the job but the connection was cut.
            # Any other error is a real failure — re-raise it.
            err_str = str(e).lower()
            is_timeout = "504" in err_str or "timed out" in err_str or "timeout" in err_str
            if not is_timeout:
                raise

        # Poll until indexing finishes
        deadline = time.monotonic() + timeout
        terminal = {"INDEXED", "ERROR", "NOT_INDEXED"}

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            data = self.get(name)
            idx = (data.get("index_info") or {})
            status = idx.get("index_status", "")
            if status in terminal:
                return data

        raise TimeoutError(
            f"Indexing did not complete within {timeout}s. "
            f"Last status: {status}. Check with client.arcana.info(...)."
        )

    def delete_index(self, name: str) -> dict | None:
        """Delete the index of an arcana.

        Accepts either the plain name or the full ``owner/name`` ID.

        Args:
            name: The arcana name or full ``owner/name`` ID.

        Returns:
            The API response, or ``None`` if the response has no body.
        """
        name = extract_arcana_name(name)
        resp = self._session.delete(
            f"{self._arcana_base}/arcana/{quote(name, safe='')}/delete-index",
            headers=self._headers(),
        )
        raise_for_status(resp)
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return None

    def chat(
        self,
        model: str,
        messages: list[dict],
        arcana_id: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs,
    ) -> dict | Generator[dict, None, None]:
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
            The API response dict, or a generator if ``stream=True``.
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

        if stream:
            body["stream"] = True
            headers["Accept"] = "text/event-stream"
            resp = self._session.post(
                f"{self._base_url}/chat/completions",
                json=body,
                headers=headers,
                stream=True,
            )
            return iter_sse(resp)

        resp = self._session.post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers=headers,
        )
        raise_for_status(resp)
        result = resp.json()
        result["_rate_limits"] = parse_rate_limits(resp.headers)
        return result

    def __repr__(self):
        return f"ArcanaService(base_url={self._base_url!r})"
