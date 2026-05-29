"""API key, ARCANA ID, and configuration discovery.

Configuration is split across two files:

- ``.env`` — secrets only (API key, optionally a single default ARCANA ID)
- ``config.toml`` — structured settings (username, base URL, ARCANA IDs, etc.)

Both files are searched in the current working directory, then the home directory.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import tomlkit

_ENV_VAR = "SAIA_API_KEY"
_KEY_FILE = ".saia_api"
_ENV_FILE = ".env"
_CONFIG_FILE = "config.toml"

_USERNAME_VAR = "SAIA_USERNAME"
_ARCANA_ID_VAR = "SAIA_ARCANA_ID"
_ARCANA_ID_PATTERN = re.compile(r"^SAIA_ARCANA_ID_(\w+)$")


def _search_dirs() -> list[Path]:
    """Return directories to search, evaluated at call time."""
    return [Path.cwd(), Path.home()]


# ---------------------------------------------------------------------------
# .env parsing
# ---------------------------------------------------------------------------


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict of all KEY=value pairs."""
    result = {}
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return result
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _find_dotenv() -> dict[str, str]:
    """Find and parse the first .env file in search dirs."""
    for directory in _search_dirs():
        candidate = directory / _ENV_FILE
        if candidate.exists():
            return _parse_dotenv(candidate)
    return {}


# ---------------------------------------------------------------------------
# config.toml parsing
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> tomlkit.TOMLDocument:
    """Load a TOML file as a tomlkit document (preserves comments).

    Returns an empty TOMLDocument if the file cannot be read.

    Raises:
        ValueError: If the file exists but contains invalid TOML.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return tomlkit.document()
    try:
        return tomlkit.parse(content)
    except tomlkit.exceptions.ParseError as e:
        raise ValueError(
            f"Invalid TOML in {path}: {e}\n"
            f"Fix the syntax error or remove the file."
        ) from e


def _find_config() -> dict:
    """Find and parse the first config.toml in search dirs."""
    for directory in _search_dirs():
        candidate = directory / _CONFIG_FILE
        if candidate.exists():
            return _load_toml(candidate)
    return {}


def load_config() -> dict:
    """Load the full ``config.toml`` as a dict.

    Searches the current working directory, then the home directory.

    Returns:
        The parsed TOML dict, or an empty dict if not found.
    """
    return _find_config()


def _find_config_path() -> Path:
    """Return the path to config.toml (existing or default to cwd)."""
    for directory in _search_dirs():
        candidate = directory / _CONFIG_FILE
        if candidate.exists():
            return candidate
    return Path.cwd() / _CONFIG_FILE


def _write_toml(path: Path, data) -> None:
    """Write a TOML document to a file, preserving comments and formatting."""
    path.write_text(tomlkit.dumps(data), encoding="utf-8")


def add_arcana_to_config(arcana_id: str, *, label: str | None = None) -> Path:
    """Add an ARCANA ID to ``config.toml``.

    Preserves existing comments and formatting. If ``label`` is provided,
    adds to ``[saia.arcana.labels]``. Otherwise appends to
    ``[saia.arcana] ids`` array.

    Args:
        arcana_id: The full ``owner/name`` ARCANA ID.
        label: Optional label key (e.g. ``"project_a"``).

    Returns:
        The path to the updated config.toml.
    """
    path = _find_config_path()
    doc = _load_toml(path) if path.exists() else tomlkit.document()

    if "saia" not in doc:
        doc.add("saia", tomlkit.table())
    saia = doc["saia"]
    if "arcana" not in saia:
        saia.add("arcana", tomlkit.table())
    arcana = saia["arcana"]

    if label:
        if "labels" not in arcana:
            arcana.add("labels", tomlkit.table())
        arcana["labels"][label] = arcana_id
    else:
        if "ids" not in arcana:
            arcana.add("ids", tomlkit.array())
        ids = arcana["ids"]
        if arcana_id not in ids:
            ids.append(arcana_id)

    _write_toml(path, doc)
    return path


def remove_arcana_from_config(arcana_id: str) -> Path:
    """Remove an ARCANA ID from ``config.toml``.

    Preserves existing comments and formatting. Removes the ID from
    ``[saia.arcana] ids``, ``[saia.arcana] default``, and any matching
    entry in ``[saia.arcana.labels]``.

    Args:
        arcana_id: The full ``owner/name`` ARCANA ID to remove.

    Returns:
        The path to the updated config.toml.
    """
    path = _find_config_path()
    if not path.exists():
        return path

    doc = _load_toml(path)
    arcana = doc.get("saia", {}).get("arcana", {})

    # Remove from ids array
    ids = arcana.get("ids", [])
    if arcana_id in ids:
        ids.remove(arcana_id)

    # Remove from default
    if arcana.get("default") == arcana_id:
        del arcana["default"]

    # Remove from labels
    labels = arcana.get("labels", {})
    to_remove = [k for k, v in labels.items() if v == arcana_id]
    for k in to_remove:
        del labels[k]

    _write_toml(path, doc)
    return path


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------


def load_api_key(path: str | Path | None = None) -> str:
    """Discover and return the SAIA API key.

    Resolution order:

    1. ``path`` argument — explicit file path (``.saia_api`` or ``.env`` format)
    2. ``SAIA_API_KEY`` environment variable
    3. ``.saia_api`` in the current working directory
    4. ``.saia_api`` in the home directory
    5. ``.env`` in the current working directory (looks for ``SAIA_API_KEY=...``)
    6. ``.env`` in the home directory

    Args:
        path: Optional explicit path to a ``.saia_api`` or ``.env`` file.

    Returns:
        The API key string.

    Raises:
        FileNotFoundError: If ``path`` was given but does not exist.
        ValueError: If no API key could be found anywhere.
    """
    # 1. Explicit file path
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"API key file not found: {p}")
        return _read_file(p)

    # 2. Environment variable
    key = os.environ.get(_ENV_VAR)
    if key and key.strip():
        return key.strip()

    # 3 & 4. .saia_api in cwd / home
    for directory in _search_dirs():
        candidate = directory / _KEY_FILE
        if candidate.exists():
            return _read_raw(candidate)

    # 5 & 6. .env in cwd / home
    dotenv = _find_dotenv()
    value = dotenv.get(_ENV_VAR)
    if value:
        return value

    raise ValueError(
        f"No SAIA API key found. Provide it via:\n"
        f"  - SAIAClient(api_key='...')\n"
        f"  - Environment variable {_ENV_VAR!r}\n"
        f"  - {_KEY_FILE!r} file containing the raw key\n"
        f"  - {_ENV_FILE!r} file with {_ENV_VAR}=<key>"
    )


def _read_file(path: Path) -> str:
    """Read an API key from an explicit file path.

    Accepts both supported formats: a ``.env``-style file (a
    ``SAIA_API_KEY=...`` line) and a raw ``.saia_api`` file (the key on
    its own line). The dotenv form wins when a ``SAIA_API_KEY`` entry is
    present; otherwise the first non-empty, non-comment line is treated as
    the raw key.

    This replaces the previous "contains ``=``" heuristic, which mis-classified
    raw keys that legitimately contain ``=`` (e.g. base64 padding) and raised
    ``IndexError`` on an empty file.
    """
    value = _parse_dotenv(path).get(_ENV_VAR)
    if value:
        return value
    return _read_raw(path)


def _read_raw(path: Path) -> str:
    """Read a .saia_api file — first non-empty, non-comment line."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise ValueError(f"No API key found in {path}")


# ---------------------------------------------------------------------------
# ARCANA ID loading
# ---------------------------------------------------------------------------


def load_arcana_ids() -> dict[str, str]:
    """Discover ARCANA IDs from ``.env``, ``config.toml``, and environment variables.

    All sources are merged. The ``"default"`` key is set by the highest-priority
    source that provides a single ARCANA ID:

    1. ``SAIA_ARCANA_ID`` in ``.env`` or environment variable
    2. ``[saia.arcana] default`` in ``config.toml``
    3. First element of ``[saia.arcana] ids`` in ``config.toml``
    4. First ``SAIA_ARCANA_ID_XX`` key (by file/env order, not sorted)

    Additional IDs from ``config.toml`` arrays and numbered env vars are
    included under their respective labels.

    Returns:
        A dict mapping label to arcana ID string:

        - ``"default"`` — the default arcana ID (if any source provides one)
        - ``"0"``, ``"1"``, ... — from ``[saia.arcana] ids`` array
        - Numbered suffixes (e.g. ``"01"``) — from ``SAIA_ARCANA_ID_01`` env vars

        Returns an empty dict if no ARCANA IDs are found.
    """
    dotenv = _find_dotenv()
    config = _find_config()
    arcana_cfg = config.get("saia", {}).get("arcana", {})

    # Merge env vars + .env (env vars win)
    env_merged = {**dotenv, **os.environ}

    result: dict[str, str] = {}
    default: str | None = None

    # --- Collect from config.toml ---

    # Named entries: [saia.arcana.labels]
    labels = arcana_cfg.get("labels", {})
    for label, value in labels.items():
        if isinstance(value, str) and value.strip():
            result[label] = value.strip()

    # Array: [saia.arcana] ids = [...]
    ids_list = arcana_cfg.get("ids", [])
    if isinstance(ids_list, list):
        for i, item in enumerate(ids_list):
            if isinstance(item, str) and item.strip():
                result[str(i)] = item.strip()
        # Priority 3: first element of ids array
        if ids_list and isinstance(ids_list[0], str) and ids_list[0].strip():
            default = ids_list[0].strip()

    # Single default: [saia.arcana] default = "..."
    toml_default = arcana_cfg.get("default", "")
    if isinstance(toml_default, str) and toml_default.strip():
        # Priority 2: explicit default in config.toml
        default = toml_default.strip()

    # --- Collect from env vars / .env ---

    # Numbered: SAIA_ARCANA_ID_XX (insertion order, not sorted)
    first_numbered: str | None = None
    for key, value in env_merged.items():
        match = _ARCANA_ID_PATTERN.match(key)
        if match and value.strip():
            suffix = match.group(1)
            result[suffix] = value.strip()
            if first_numbered is None:
                first_numbered = value.strip()

    # Priority 4: first numbered key
    if first_numbered and default is None:
        default = first_numbered

    # Priority 1: SAIA_ARCANA_ID in env/.env (highest priority)
    env_single = env_merged.get(_ARCANA_ID_VAR, "").strip()
    if env_single:
        default = env_single

    # Set the default
    if default:
        result["default"] = default

    # --- Resolve owner prefix using username ---
    result = _resolve_owner_prefix(result, config, env_merged)

    return result


def _resolve_owner_prefix(
    ids: dict[str, str], config: dict, env_merged: dict[str, str]
) -> dict[str, str]:
    """Prepend ``username/`` to ARCANA IDs that lack an owner prefix.

    The chat endpoint requires the ``owner/name`` format. If an ID has no
    ``/``, the username is resolved from ``SAIA_USERNAME`` (env, .env) or
    ``[saia] username`` in config.toml.

    Args:
        ids: The collected ARCANA IDs.
        config: The parsed ``config.toml``.
        env_merged: The already-merged ``{**dotenv, **os.environ}`` mapping
            (env vars take precedence over ``.env``). Reused here to avoid
            re-reading ``.env`` from disk.

    Raises:
        ValueError: If an ID has no ``/`` and no username is configured.
    """
    if not ids:
        return ids

    # Check if any ID needs a prefix
    needs_prefix = any("/" not in v for v in ids.values())
    if not needs_prefix:
        return ids

    # Resolve username: env var / .env first (already merged), then config.toml
    username = (env_merged.get(_USERNAME_VAR) or "").strip()
    if not username:
        cfg_username = config.get("saia", {}).get("username", "")
        username = cfg_username.strip() if isinstance(cfg_username, str) else ""

    if not username:
        missing = [f"{k}={v}" for k, v in ids.items() if "/" not in v]
        raise ValueError(
            f"ARCANA ID(s) without owner prefix require a username, "
            f"but SAIA_USERNAME is not configured.\n"
            f"  IDs missing owner prefix: {', '.join(missing)}\n"
            f"  Set SAIA_USERNAME in .env or [saia] username in config.toml."
        )

    resolved = {}
    for label, value in ids.items():
        if "/" not in value:
            resolved[label] = f"{username}/{value}"
        else:
            resolved[label] = value
    return resolved


# ---------------------------------------------------------------------------
# Username loading
# ---------------------------------------------------------------------------


def load_username() -> str | None:
    """Discover the SAIA username from environment, ``.env``, or ``config.toml``.

    Resolution order:

    1. ``SAIA_USERNAME`` environment variable
    2. ``SAIA_USERNAME`` in ``.env``
    3. ``[saia] username`` in ``config.toml``

    Returns:
        The username string, or ``None`` if not configured.
    """
    value = os.environ.get(_USERNAME_VAR, "").strip()
    if value:
        return value

    dotenv = _find_dotenv()
    value = dotenv.get(_USERNAME_VAR, "").strip()
    if value:
        return value

    config = _find_config()
    value = config.get("saia", {}).get("username", "")
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None
