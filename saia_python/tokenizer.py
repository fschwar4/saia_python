"""Tokenizer support for the GWDG open-weight models.

The SAIA / Chat AI ``GET /models`` endpoint lists which models are available
but **does not** expose where each model's tokenizer lives — its per-model
payload carries ``id``, ``name``, ``input``/``output`` modalities, ``status``
and ``demand``, but no repository link. The mapping from a GWDG model id to its
upstream Hugging Face repository is only published, in human-readable form, in
the model catalogue at
https://docs.hpc.gwdg.de/services/ai-services/chat-ai/models/index.html .

This module captures that mapping (:data:`GWDG_MODEL_REPOS`) and builds the
tooling on top of it:

- :func:`resolve_repo` — translate a GWDG model id (or display name, or a full
  ``org/name`` repo) into its Hugging Face repository.
- :func:`download_tokenizer` / :func:`download_all_tokenizers` — fetch only the
  *tokenizer* files (never the weights) into a local cache, defaulting to
  ``~/saia_python/tokenizers/`` and overridable per call or via the
  ``SAIA_TOKENIZER_DIR`` environment variable.
- :func:`load_tokenizer` — load a downloaded tokenizer through
  ``transformers.AutoTokenizer``.
- :func:`chat_template_tokens` — apply a model's chat template to a
  ``role``/``content`` conversation (the system prompt may be supplied inline or
  read from a ``.txt`` / ``.md`` file), and report the resulting token ids, the
  length, the *overhead* contributed by special / structural tokens versus the
  raw text, and the subword fertility. It is deliberately tolerant: a missing
  user turn (or any other gap a strict chat template would reject) degrades to a
  best-effort count with a recorded warning rather than raising.

The heavy third-party libraries (``transformers``, ``huggingface_hub``,
``tiktoken``) are an opt-in extra — install with ``pip install
saia-python[tokenizer]`` — and are imported lazily so that importing this module
(and the package as a whole) never requires them.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from transformers import PreTrainedTokenizerBase

# ---------------------------------------------------------------------------
# GWDG model catalogue
# ---------------------------------------------------------------------------

# Single source of truth: ``(api_model_id, display_name, hf_repo)`` for every
# open-weight model GWDG hosts or has hosted. ``api_model_id`` is the string
# passed as ``"model"`` to the API (and returned as ``id`` by ``GET /models``);
# ``display_name`` is the catalogue's "Model" column (and the ``name`` field of
# the ``/models`` payload); ``hf_repo`` is the ``org/name`` the catalogue links
# to on https://huggingface.co . Sourced from the GWDG model catalogue and
# cross-checked against the live ``/models`` listing on 2026-06-21; the models
# added on 2026-10-09 come from the catalogue page alone. Only open-weight
# models are listed — the externally hosted, proprietary models (GPT-5.x, o3,
# Claude, ...) have no downloadable tokenizer; see
# :data:`OPENAI_TIKTOKEN_ENCODINGS` for their byte-pair encodings.
_MODEL_TABLE: list[tuple[str, str, str]] = [
    # Served by GWDG as of 2026-10-09.
    # DeepSeek V4 ships no Jinja chat template (only a Python encoder), so
    # chat_template_tokens falls back to a plain render with a warning for it.
    (
        "deepseek-v4-flash-0731",
        "DeepSeek V4 Flash 0731",
        "deepseek-ai/DeepSeek-V4-Flash-0731",
    ),
    ("gemma-4-31b-it", "Gemma 4 31B Instruct", "google/gemma-4-31B-it"),
    # Its tokenizer_config names TokenizersBackend, a transformers 5 class.
    ("glm-5.3-flash", "GLM 5.3 Flash", "zai-org/GLM-5.3-Flash"),
    (
        "meta-llama-3.1-8b-instruct",
        "Llama 3.1 8B Instruct",
        "nvidia/Llama-3.1-8B-Instruct-FP8",
    ),
    (
        "qwen3-30b-a3b-instruct-2507",
        "Qwen 3 30B A3B Instruct 2507",
        "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
    ),
    ("qwen3-coder-next", "Qwen 3 Coder Next", "Qwen/Qwen3-Coder-Next-FP8"),
    (
        "qwen3-omni-30b-a3b-instruct",
        "Qwen 3 Omni 30B A3B Instruct",
        "Qwen/Qwen3-Omni-30B-A3B-Instruct",
    ),
    ("qwen3.5-397b-a17b", "Qwen 3.5 397B A17B", "Qwen/Qwen3.5-397B-A17B-GPTQ-Int4"),
    ("qwen3.6-35b-a3b", "Qwen 3.6 35B A3B", "Qwen/Qwen3.6-35B-A3B-FP8"),
    ("qwen3.8-27b", "Qwen 3.8 27B", "Qwen/Qwen3.8-27B-FP8"),
    # Embedding models — served via /embeddings rather than the chat /models
    # listing, but their tokenizers are useful for sizing RAG chunks.
    # ``qwen3-embedding-4b`` is the model ARCANA's RAG pipeline uses internally.
    (
        "qwen3-embedding-4b",
        "Qwen3 Embedding 4B",
        "Qwen/Qwen3-Embedding-4B",
    ),
    (
        "e5-mistral-7b-instruct",
        "E5 Mistral 7B Instruct",
        "intfloat/e5-mistral-7b-instruct",
    ),
    # No longer served by GWDG (openai-gpt-oss-120b, devstral-2-123b-instruct-2512
    # and apertus-70b-instruct-2509 were retired on 2026-10-08). Kept because
    # their Hugging Face repos remain: the ids still resolve and the tokenizers
    # still download.
    (
        "apertus-70b-instruct-2509",
        "Apertus 70B Instruct 2509",
        "RedHatAI/Apertus-70B-Instruct-2509-FP8-dynamic",
    ),
    (
        "deepseek-r1-distill-llama-70b",
        "DeepSeek R1 Distill Llama 70B",
        "deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
    ),
    (
        "devstral-2-123b-instruct-2512",
        "Devstral 2 123B Instruct 2512",
        "mistralai/Devstral-2-123B-Instruct-2512",
    ),
    ("glm-4.7", "GLM-4.7", "zai-org/GLM-4.7-FP8"),
    ("internvl3.5-30b-a3b", "InternVL 3.5 30B A3B", "OpenGVLab/InternVL3_5-30B-A3B-HF"),
    ("medgemma-27b-it", "MedGemma 27B Instruct", "google/medgemma-27b-it"),
    (
        "mistral-large-3-675b-instruct-2512",
        "Mistral Large 3 675B Instruct 2512",
        "mistralai/Mistral-Large-3-675B-Instruct-2512-NVFP4",
    ),
    ("openai-gpt-oss-120b", "GPT OSS 120B", "openai/gpt-oss-120b"),
    (
        "qwen3-coder-30b-a3b-instruct",
        "Qwen 3 Coder 30B A3B Instruct",
        "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8",
    ),
    ("qwen3.5-122b-a10b", "Qwen 3.5 122B A10B", "Qwen/Qwen3.5-122B-A10B-GPTQ-Int4"),
    (
        "teuken-7b-instruct-research",
        "Teuken 7B Instruct Research",
        "openGPT-X/Teuken-7B-instruct-research-v0.4",
    ),
]

#: Mapping of GWDG API model id → Hugging Face ``org/name`` repository.
GWDG_MODEL_REPOS: dict[str, str] = {mid: repo for mid, _name, repo in _MODEL_TABLE}

# Normalised-display-name → repo, so the catalogue's "Model" column (which the
# ``/models`` payload echoes as ``name``) also resolves.
_DISPLAY_NORM_TO_REPO: dict[str, str] = {}

#: Best-effort ``tiktoken`` encoding for the externally hosted OpenAI models,
#: which have no downloadable tokenizer. Used by :func:`count_tiktoken_tokens`.
OPENAI_TIKTOKEN_ENCODINGS: dict[str, str] = {
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
    "gpt-5": "o200k_base",
    "gpt-5-mini": "o200k_base",
    "gpt-5-nano": "o200k_base",
    "gpt-5.1": "o200k_base",
    "gpt-5.2": "o200k_base",
    "gpt-5.4": "o200k_base",
    "gpt-5.4-mini": "o200k_base",
    "gpt-5.4-nano": "o200k_base",
    "gpt-5.5": "o200k_base",
    "o3": "o200k_base",
    "o3-mini": "o200k_base",
}


def _norm(text: str) -> str:
    """Lower-case and strip everything but ``[a-z0-9]`` for fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


for _mid, _name, _repo in _MODEL_TABLE:
    _DISPLAY_NORM_TO_REPO[_norm(_name)] = _repo
del _mid, _name, _repo


# The tokenizer-only files we pull from a repo. Deliberately excludes the model
# weights (``*.safetensors`` / ``*.bin``) so a download is a few MB, not GBs.
_TOKENIZER_FILE_PATTERNS: list[str] = [
    "tokenizer.json",
    "tokenizer_config.json",
    "tokenizer.model",
    "tokenizer.model.v3",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "spiece.model",
    "chat_template.jinja",
    "chat_template.json",
    "generation_config.json",
    "config.json",
    "preprocessor_config.json",
    "*.tiktoken",
]

#: Default directory for downloaded tokenizers (``~/saia_python/tokenizers/``).
DEFAULT_TOKENIZER_DIR: Path = Path.home() / "saia_python" / "tokenizers"
_ENV_DIR_VAR = "SAIA_TOKENIZER_DIR"

# Written into a repo's local dir once a download finishes, so an interrupted
# download is never mistaken for a complete one (see ``download_tokenizer``).
_COMPLETE_MARKER = ".saia_tokenizer_complete"

# Process-wide cache so repeated ``load_tokenizer`` calls don't re-parse files.
_LOADED: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Lazy imports for the optional [tokenizer] extra
# ---------------------------------------------------------------------------


def _require(module: str):
    """Import an optional ``[tokenizer]`` dependency or raise a helpful error."""
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - exercised via integration
        raise ImportError(
            f"Tokenizer support requires the optional {module!r} dependency. "
            "Install the extra with:\n    pip install saia-python[tokenizer]"
        ) from exc


# ---------------------------------------------------------------------------
# Hugging Face token discovery
# ---------------------------------------------------------------------------

# Environment / dotenv keys searched for a Hugging Face access token, in order.
_HF_TOKEN_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN")
# Dotenv-style files searched (in the cwd, then the home directory).
_HF_TOKEN_FILES = (".env", ".saia_env")


def load_hf_token(path: str | os.PathLike[str] | None = None) -> str | None:
    """Discover a Hugging Face access token for authenticated downloads.

    An HF token raises the Hub's anonymous rate limits and is required for gated
    or private repositories. Resolution order:

    1. ``path`` — an explicit ``.env``-style file (any of the ``HF_TOKEN`` /
       ``HUGGING_FACE_HUB_TOKEN`` / ``HUGGINGFACE_TOKEN`` keys).
    2. Those same environment variables.
    3. A ``.env`` then ``.saia_env`` file in the current working directory, then
       in the home directory.

    Returns ``None`` when no token is configured — public repositories still
    download anonymously (just rate-limited), so a missing token is not an error.

    Note:
        This is independent of ``huggingface_hub``'s own discovery (its cached
        ``huggingface-cli login`` token / ``HF_TOKEN`` env). When this returns
        ``None``, the Hub library's own discovery still applies.
    """
    from .auth import _parse_dotenv

    if path is not None:
        values = _parse_dotenv(Path(path).expanduser())
        for var in _HF_TOKEN_VARS:
            if values.get(var):
                return values[var]
        return None

    for var in _HF_TOKEN_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()

    for directory in (Path.cwd(), Path.home()):
        for filename in _HF_TOKEN_FILES:
            candidate = directory / filename
            if candidate.exists():
                values = _parse_dotenv(candidate)
                for var in _HF_TOKEN_VARS:
                    if values.get(var):
                        return values[var]
    return None


# ---------------------------------------------------------------------------
# Repository resolution
# ---------------------------------------------------------------------------


def available_open_models() -> list[str]:
    """Return the GWDG open-weight model ids known to this module.

    These are the keys of :data:`GWDG_MODEL_REPOS` — the models for which a
    tokenizer repository is published and can be downloaded, including the ones
    GWDG no longer serves. For the models available right now, annotate the live
    listing instead (:meth:`TokenizerService.available_repos`).
    """
    return list(GWDG_MODEL_REPOS)


def resolve_repo(model: str) -> str:
    """Translate a GWDG model into its Hugging Face ``org/name`` repository.

    Accepts, in order of preference:

    1. A GWDG API model id (e.g. ``"deepseek-v4-flash-0731"``) — exactly as
       returned by ``GET /models`` / passed as ``"model"`` in API calls.
    2. A full ``org/name`` Hugging Face repo (anything containing ``/``) — used
       verbatim, so callers can point at a model this module does not list yet.
    3. A catalogue display name (e.g. ``"DeepSeek V4 Flash 0731"``) or a loose
       spelling of an id — matched after normalisation (case / punctuation
       insensitive).

    Args:
        model: The model id, display name, or ``org/name`` repository.

    Returns:
        The Hugging Face repository as ``"org/name"``.

    Raises:
        ValueError: If ``model`` cannot be resolved to a known repository.
    """
    model = model.strip()
    # 2. Full org/name repo — pass through.
    if "/" in model:
        return model
    # 1. Exact API id.
    if model in GWDG_MODEL_REPOS:
        return GWDG_MODEL_REPOS[model]
    # 3. Normalised match against ids, display names, then repo basenames.
    norm = _norm(model)
    for mid, repo in GWDG_MODEL_REPOS.items():
        if _norm(mid) == norm:
            return repo
    if norm in _DISPLAY_NORM_TO_REPO:
        return _DISPLAY_NORM_TO_REPO[norm]
    for repo in GWDG_MODEL_REPOS.values():
        if _norm(repo.split("/")[-1]) == norm:
            return repo
    raise ValueError(
        f"Unknown GWDG model {model!r}. Pass a known model id "
        f"({', '.join(sorted(GWDG_MODEL_REPOS))}), a catalogue display name, or "
        f"a full 'org/name' Hugging Face repository."
    )


def repo_url(model: str) -> str:
    """Return the full ``https://huggingface.co/...`` URL for ``model``."""
    return f"https://huggingface.co/{resolve_repo(model)}"


# ---------------------------------------------------------------------------
# Gated-repository errors
# ---------------------------------------------------------------------------


class GatedRepoAccessError(RuntimeError):
    """A tokenizer download was blocked because the repository is *gated*.

    The repository exists and its tokenizer files are present, but Hugging Face
    denied access (HTTP 403): a gated repo requires accepting its licence on the
    model page **and** an ``HF_TOKEN`` for the accepting account. A few catalogue
    entries are gated — e.g. ``google/medgemma-27b-it`` (Google's Health AI
    terms). The original ``huggingface_hub`` error is preserved as the exception
    cause (``__cause__``).
    """


def _looks_gated(exc: Exception) -> bool:
    """Heuristic: does ``exc`` look like a gated / unauthorized Hub error?"""
    blob = f"{type(exc).__name__} {exc}".lower()
    return "gated" in blob or "401" in blob or "403" in blob


def _gated_repo_message(model: str, repo: str) -> str:
    """Build the expressive, actionable message for a gated-repo denial."""
    url = f"https://huggingface.co/{repo}"
    return (
        f"Access to the gated Hugging Face repository '{repo}' (GWDG model "
        f"'{model}') was denied (HTTP 403). The tokenizer exists, but the repo "
        f"is licence-gated. To download it:\n"
        f"  1. Open {url} and accept the licence (sign in first).\n"
        f"  2. Create a read token at https://huggingface.co/settings/tokens.\n"
        f"  3. Provide it as HF_TOKEN — in the environment or a .env / .saia_env "
        f"file (see saia_python.tokenizer.load_hf_token) — then retry.\n"
        f"In a download_all_tokenizers() run this model is recorded as None and "
        f"the batch continues."
    )


# ---------------------------------------------------------------------------
# Download cache management
# ---------------------------------------------------------------------------


def tokenizer_dir(cache_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the directory tokenizers are cached in.

    Resolution order: the explicit ``cache_dir`` argument, then the
    ``SAIA_TOKENIZER_DIR`` environment variable, then
    :data:`DEFAULT_TOKENIZER_DIR` (``~/saia_python/tokenizers/``). ``~`` is
    expanded in all cases.
    """
    if cache_dir is not None:
        return Path(cache_dir).expanduser()
    env = os.environ.get(_ENV_DIR_VAR)
    if env and env.strip():
        return Path(env).expanduser()
    return DEFAULT_TOKENIZER_DIR


def _local_repo_dir(repo: str, cache_dir: str | os.PathLike[str] | None) -> Path:
    """Return the local directory a given ``org/name`` repo maps to."""
    return tokenizer_dir(cache_dir) / repo


def download_tokenizer(
    model: str,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    repo: str | None = None,
    token: str | None = None,
    force: bool = False,
) -> Path:
    """Download a model's tokenizer files into the local cache.

    Only the tokenizer-relevant files are fetched (see
    :data:`_TOKENIZER_FILE_PATTERNS`); the model weights are never downloaded,
    so this stays in the low-megabytes range. Files land in
    ``<cache_dir>/<org>/<name>/``.

    Args:
        model: A GWDG model id, display name, or ``org/name`` repo
            (see :func:`resolve_repo`).
        cache_dir: Where to store the files. Defaults to
            :func:`tokenizer_dir` (``~/saia_python/tokenizers/``).
        repo: Explicit Hugging Face repository, bypassing :func:`resolve_repo`.
        token: A Hugging Face access token, for gated/private repos and to lift
            the anonymous rate limit. When omitted, it is resolved via
            :func:`load_hf_token` (``HF_TOKEN`` env, then ``.env`` / ``.saia_env``);
            if that finds nothing, ``huggingface_hub``'s own discovery (cached
            login) still applies.
        force: Re-download even if the files already exist locally.

    Returns:
        The local directory containing the tokenizer files.

    Raises:
        ImportError: If the ``[tokenizer]`` extra is not installed.
    """
    repo = repo or resolve_repo(model)
    target = _local_repo_dir(repo, cache_dir)
    # Short-circuit only on a completion marker written *after* a successful
    # download — never on a single file. An interrupted download leaves the
    # marker absent, so the next call re-runs (resumable) snapshot_download
    # instead of handing a half-populated directory to ``from_pretrained``.
    if not force and (target / _COMPLETE_MARKER).exists():
        return target

    if token is None:
        token = load_hf_token()
    hub = _require("huggingface_hub")
    target.mkdir(parents=True, exist_ok=True)
    try:
        hub.snapshot_download(
            repo_id=repo,
            allow_patterns=_TOKENIZER_FILE_PATTERNS,
            local_dir=str(target),
            token=token,
        )
    except Exception as exc:  # noqa: BLE001 - re-raised, gated case made expressive
        if _looks_gated(exc):
            raise GatedRepoAccessError(_gated_repo_message(model, repo)) from exc
        raise
    (target / _COMPLETE_MARKER).write_text("ok", encoding="utf-8")
    return target


def download_all_tokenizers(
    *,
    models: list[str] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    token: str | None = None,
    force: bool = False,
    verbose: bool = False,
) -> dict[str, Path | None]:
    """Download the tokenizers for many models, tolerating per-model failures.

    Convenience wrapper that loops :func:`download_tokenizer` over a model list.
    With ``models=None`` it covers every open-weight model in
    :data:`GWDG_MODEL_REPOS`. A model that fails (e.g. a gated repo without a
    token, or a transient network error) is recorded as ``None`` instead of
    aborting the whole batch.

    To drive this from the *live* set of available models, fetch the ids first::

        from saia_python import SAIAClient, download_all_tokenizers
        ids = SAIAClient().models.list_ids()
        download_all_tokenizers(models=ids)

    Args:
        models: Model ids/names to download. Defaults to all open-weight models.
        cache_dir: Cache directory (see :func:`tokenizer_dir`).
        token: Hugging Face token. Resolved once via :func:`load_hf_token` when
            omitted (``HF_TOKEN`` env, then ``.env`` / ``.saia_env``).
        force: Re-download even if cached.
        verbose: Print a per-model success/failure line.

    Returns:
        A mapping of input model id → local directory (or ``None`` on failure).
    """
    from ._util import progress_iter

    if token is None:
        token = load_hf_token()
    targets = models if models is not None else available_open_models()
    results: dict[str, Path | None] = {}
    for model in progress_iter(
        targets, desc="Downloading tokenizers", unit="model", enabled=not verbose
    ):
        try:
            path = download_tokenizer(
                model, cache_dir=cache_dir, token=token, force=force
            )
            results[model] = path
            if verbose:
                print(f"  {model:<40} -> {path}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            results[model] = None
            if verbose:
                print(f"  {model:<40} FAILED: {_describe_download_error(model, exc)}")
    return results


def _describe_download_error(model: str, exc: Exception) -> str:
    """A one-line failure reason, with a licence hint for gated repos."""
    name = type(exc).__name__
    if _looks_gated(exc):
        try:
            where = f"https://huggingface.co/{resolve_repo(model)}"
        except ValueError:
            where = model
        return (
            f"{name}: gated repository — accept the licence at {where} "
            "(signed in as your HF_TOKEN account), then retry"
        )
    return f"{name}: {str(exc).splitlines()[0][:200]}"


# ---------------------------------------------------------------------------
# Tokenizer loading
# ---------------------------------------------------------------------------


def load_tokenizer(
    model: str,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    repo: str | None = None,
    token: str | None = None,
    download: bool = True,
    trust_remote_code: bool = False,
    **from_pretrained_kwargs: Any,
) -> PreTrainedTokenizerBase:
    """Load a model's tokenizer via ``transformers.AutoTokenizer``.

    The tokenizer files are taken from the local cache, downloading them first
    when missing (unless ``download=False``). Loaded tokenizers are cached per
    process, so repeated calls for the same model are cheap.

    Args:
        model: A GWDG model id, display name, or ``org/name`` repo.
        cache_dir: Cache directory (see :func:`tokenizer_dir`).
        repo: Explicit Hugging Face repository, bypassing :func:`resolve_repo`.
        token: Hugging Face token for gated repos.
        download: Download the files if they are not already cached. When
            ``False`` and the cache is empty, loading raises.
        trust_remote_code: Forwarded to ``AutoTokenizer.from_pretrained`` — a
            few tokenizers ship a custom class and need this.
        **from_pretrained_kwargs: Extra keyword arguments forwarded verbatim to
            ``AutoTokenizer.from_pretrained``.

    Returns:
        A ``transformers.PreTrainedTokenizerBase`` instance.

    Raises:
        ImportError: If the ``[tokenizer]`` extra is not installed.
    """
    repo = repo or resolve_repo(model)
    # Key the process cache on everything that changes the returned tokenizer —
    # including the forwarded ``from_pretrained`` options (``use_fast``,
    # ``revision``, ``padding_side``, ...) — so distinct load options don't
    # collapse onto one cached instance. (``token`` is excluded: it gates
    # access but does not alter the tokenizer.)
    opts_key = repr(sorted(from_pretrained_kwargs.items()))
    cache_key = f"{tokenizer_dir(cache_dir)}::{repo}::{trust_remote_code}::{opts_key}"
    cached = _LOADED.get(cache_key)
    if cached is not None:
        return cached

    if token is None:
        token = load_hf_token()
    if download:
        local = download_tokenizer(model, cache_dir=cache_dir, repo=repo, token=token)
    else:
        local = _local_repo_dir(repo, cache_dir)

    transformers = _require("transformers")
    tok = transformers.AutoTokenizer.from_pretrained(
        str(local),
        token=token,
        trust_remote_code=trust_remote_code,
        **from_pretrained_kwargs,
    )
    _LOADED[cache_key] = tok
    return tok


# ---------------------------------------------------------------------------
# Chat-template token counting
# ---------------------------------------------------------------------------


@dataclass
class ChatTokenCount:
    """The result of tokenizing a chat conversation against a model template.

    Attributes:
        model: The model the conversation was tokenized for (if known).
        repo: The resolved Hugging Face repository (if known).
        num_tokens: Length of the full chat-templated prompt, **including** the
            special and structural tokens the template inserts (BOS/EOS, role
            markers such as ``<|im_start|>``, the generation prompt, ...).
        num_text_tokens: Tokens contributed by the raw message *content* alone,
            encoded without any special tokens. The "pure text" baseline.
        overhead_tokens: ``num_tokens - num_text_tokens`` — how many tokens the
            chat template's special/structural scaffolding adds.
        overhead_ratio_text: ``overhead_tokens / num_text_tokens`` — the overhead
            relative to the raw text (e.g. ``0.5`` = the scaffolding adds half
            again as many tokens as the text itself). ``nan`` if no text tokens.
        overhead_ratio_total: ``overhead_tokens / num_tokens`` — the fraction of
            the full prompt that is special/structural overhead (always in
            ``[0, 1]`` for normal templates). ``nan`` if the prompt is empty.
        num_words: Whitespace-delimited word count across all message contents.
        fertility: Subword fertility of the raw text — ``num_text_tokens /
            num_words`` (tokens per word, special tokens excluded).
        fertility_with_special: ``num_tokens / num_words`` — fertility including
            the template's special/structural tokens.
        token_ids: The full templated token ids.
        tokens: The token *strings* for ``token_ids`` (empty if the tokenizer
            cannot map ids back to tokens).
        rendered: The chat template rendered to text (``None`` if rendering was
            not available).
        add_generation_prompt: Whether a trailing generation prompt is actually
            present in ``token_ids`` / ``rendered``. This is the *effective*
            value: it is forced to ``False`` if the requested generation prompt
            had to be dropped on a fallback path, so it never disagrees with the
            counted tokens.
        warnings: Non-fatal issues — e.g. the chat template rejected the
            conversation (missing user turn) and a fallback was used.
    """

    model: str | None
    repo: str | None
    num_tokens: int
    num_text_tokens: int
    overhead_tokens: int
    overhead_ratio_text: float
    overhead_ratio_total: float
    num_words: int
    fertility: float
    fertility_with_special: float
    token_ids: list[int]
    tokens: list[str]
    rendered: str | None
    add_generation_prompt: bool
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a one-line human-readable summary."""
        return (
            f"{self.num_tokens} tokens "
            f"({self.num_text_tokens} text + {self.overhead_tokens} overhead, "
            f"{self.overhead_ratio_total:.1%} of total), "
            f"{self.num_words} words, fertility {self.fertility:.3f}"
        )


def count_words(text: str) -> int:
    """Count whitespace-delimited words — the denominator for fertility."""
    return len(text.split())


def _resolve_text(text: str | None, file: str | os.PathLike[str] | None) -> str | None:
    """Resolve a message body from an inline string or a text file.

    Exactly one source may be given. A ``file`` is read as UTF-8 and works for
    any plain-text format (``.txt``, ``.md``, ...).

    Raises:
        ValueError: If both ``text`` and ``file`` are provided.
        FileNotFoundError: If ``file`` is given but does not exist.
    """
    if file is not None:
        if text is not None:
            raise ValueError("Provide either the inline text or a file, not both.")
        path = Path(file).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"System prompt file not found: {path}")
        return path.read_text(encoding="utf-8")
    return text


def _build_messages(
    messages: list[dict[str, str]] | None,
    system: str | None,
    system_file: str | os.PathLike[str] | None,
    user: str | None,
    user_file: str | os.PathLike[str] | None,
    assistant: str | None,
) -> list[dict[str, str]]:
    """Assemble a role/content message list from the convenience arguments.

    An explicit ``messages`` list wins outright. Otherwise the system, user and
    assistant turns are assembled in that order, each optionally sourced from a
    file. Parts that are absent are simply skipped — a system-only or empty
    conversation is allowed here; tolerance for what the *template* makes of it
    is handled downstream.
    """
    if messages is not None:
        return [dict(m) for m in messages]
    built: list[dict[str, str]] = []
    sys_content = _resolve_text(system, system_file)
    if sys_content is not None:
        built.append({"role": "system", "content": sys_content})
    user_content = _resolve_text(user, user_file)
    if user_content is not None:
        built.append({"role": "user", "content": user_content})
    if assistant is not None:
        built.append({"role": "assistant", "content": assistant})
    return built


def _manual_render(messages: list[dict[str, str]]) -> str:
    """Fallback rendering when a chat template rejects the conversation."""
    return "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in messages)


def _to_id_list(obj: Any) -> list[int]:
    """Normalise an ``apply_chat_template`` / ``encode`` result to ``list[int]``.

    Depending on the tokenizer (and ``transformers`` version),
    ``apply_chat_template(tokenize=True)`` may return a flat ``list[int]``, a
    ``BatchEncoding`` / dict (``{"input_ids": [...], ...}``), a tensor, or a
    batched ``[[...]]`` list. This flattens all of those to a single id list so
    the counts are never thrown off by the container shape.
    """
    from collections.abc import Mapping

    ids: Any = obj
    if isinstance(obj, Mapping):
        ids = obj.get("input_ids", obj)
    elif hasattr(obj, "input_ids"):
        ids = obj.input_ids
    if hasattr(ids, "tolist"):  # torch / numpy tensor
        ids = ids.tolist()
    # Unwrap a single batch dimension, e.g. [[1, 2, 3]] -> [1, 2, 3].
    if (
        isinstance(ids, (list, tuple))
        and len(ids) > 0
        and isinstance(ids[0], (list, tuple))
    ):
        ids = ids[0]
    return [int(x) for x in ids]


def _apply_template(
    tokenizer: Any,
    messages: list[dict[str, str]],
    add_generation_prompt: bool,
) -> tuple[list[int], str | None, bool, list[str]]:
    """Tokenize ``messages`` with the chat template, tolerating template gaps.

    Strict chat templates can reject otherwise-valid inputs (e.g. a missing user
    turn, or roles that do not alternate). Rather than propagate that as an
    error, this retries without the generation prompt and finally falls back to
    a manual render encoded with special tokens, recording what happened in the
    returned warnings list.

    Returns ``(token_ids, rendered, effective_add_generation_prompt, warnings)``.
    The rendered string and the effective flag always describe the *counted*
    ids: when the generation-prompt attempt is rejected and the retry drops it,
    both are re-derived without the generation prompt so the public fields never
    disagree with ``token_ids``.
    """
    warnings: list[str] = []
    if not messages:
        warnings.append("no messages supplied; counting an empty conversation")

    def _render(gen: bool) -> str | None:
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=gen
            )
        except Exception:  # noqa: BLE001 - rendering is best-effort, for display
            return None

    try:
        ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=add_generation_prompt,
        )
        return (
            _to_id_list(ids),
            _render(add_generation_prompt),
            add_generation_prompt,
            warnings,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f"chat template rejected the conversation "
            f"({type(exc).__name__}: {exc}); retrying without a generation prompt"
        )

    try:
        ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
        )
        # The generation prompt was dropped — re-render and report it as such
        # so rendered/flag stay consistent with the counted ids.
        return _to_id_list(ids), _render(False), False, warnings
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f"chat template still failed ({type(exc).__name__}: {exc}); "
            "falling back to a plain 'role: content' render with special tokens"
        )

    text = _manual_render(messages)
    ids = tokenizer.encode(text, add_special_tokens=True)
    return _to_id_list(ids), text, False, warnings


def chat_template_tokens(
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    *,
    system: str | None = None,
    system_file: str | os.PathLike[str] | None = None,
    user: str | None = None,
    user_file: str | os.PathLike[str] | None = None,
    assistant: str | None = None,
    add_generation_prompt: bool = True,
    tokenizer: Any | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    repo: str | None = None,
    token: str | None = None,
) -> ChatTokenCount:
    """Apply a model's chat template to a conversation and measure it.

    Builds a ``role``/``content`` conversation — either from an explicit
    ``messages`` list or from the ``system`` / ``user`` / ``assistant``
    convenience arguments (the system prompt, and optionally the user turn, may
    be read from a ``.txt`` / ``.md`` file) — applies the model's chat template,
    and reports the full :class:`ChatTokenCount`: the templated length, the raw
    text length, the special/structural-token overhead between them, and the
    subword fertility.

    It is deliberately forgiving. A missing user turn, an empty conversation, or
    any other shape a strict template rejects is degraded to a best-effort count
    with an entry in :attr:`ChatTokenCount.warnings` — it never raises on
    account of a missing chat-template part.

    Either ``model`` (the tokenizer is loaded for you) or ``tokenizer`` (a
    pre-loaded ``transformers`` tokenizer, reused as-is) must be given.

    Args:
        model: A GWDG model id, display name, or ``org/name`` repo. Used to load
            the tokenizer when ``tokenizer`` is not supplied.
        messages: An explicit ``[{"role": ..., "content": ...}, ...]`` list. If
            given, the convenience arguments below are ignored.
        system: Inline system-prompt text.
        system_file: Path to a text file whose contents are the system prompt.
        user: Inline user-turn text.
        user_file: Path to a text file whose contents are the user turn.
        assistant: Inline assistant-turn text.
        add_generation_prompt: Append the template's generation prompt (the
            tokens that cue the model to start replying). Default ``True``.
        tokenizer: A pre-loaded tokenizer to use instead of loading one.
        cache_dir: Cache directory (see :func:`tokenizer_dir`).
        repo: Explicit Hugging Face repository, bypassing :func:`resolve_repo`.
        token: Hugging Face token for gated repos.

    Returns:
        A :class:`ChatTokenCount`.

    Raises:
        ValueError: If neither ``model`` nor ``tokenizer`` is provided, or if a
            message body is given both inline and as a file.
    """
    if tokenizer is None:
        if model is None:
            raise ValueError("Provide either a 'model' or a preloaded 'tokenizer'.")
        tokenizer = load_tokenizer(model, cache_dir=cache_dir, repo=repo, token=token)

    convo = _build_messages(messages, system, system_file, user, user_file, assistant)

    token_ids, rendered, effective_gen_prompt, warnings = _apply_template(
        tokenizer, convo, add_generation_prompt
    )

    # Raw-text baseline: encode each message body without special tokens.
    num_text_tokens = 0
    for m in convo:
        content = m.get("content", "")
        if content:
            num_text_tokens += len(tokenizer.encode(content, add_special_tokens=False))

    num_tokens = len(token_ids)
    overhead = num_tokens - num_text_tokens
    overhead_ratio_text = (
        overhead / num_text_tokens if num_text_tokens else float("nan")
    )
    overhead_ratio_total = overhead / num_tokens if num_tokens else float("nan")
    num_words = sum(count_words(m.get("content", "")) for m in convo)

    fertility = num_text_tokens / num_words if num_words else float("nan")
    fertility_special = num_tokens / num_words if num_words else float("nan")

    tokens: list[str] = []
    convert = getattr(tokenizer, "convert_ids_to_tokens", None)
    if callable(convert):
        try:
            tokens = list(convert(token_ids))
        except Exception:  # noqa: BLE001 - token strings are a nicety, not core
            tokens = []

    resolved_repo = repo
    if resolved_repo is None and model is not None:
        try:
            resolved_repo = resolve_repo(model)
        except ValueError:
            resolved_repo = None

    return ChatTokenCount(
        model=model,
        repo=resolved_repo,
        num_tokens=num_tokens,
        num_text_tokens=num_text_tokens,
        overhead_tokens=overhead,
        overhead_ratio_text=overhead_ratio_text,
        overhead_ratio_total=overhead_ratio_total,
        num_words=num_words,
        fertility=fertility,
        fertility_with_special=fertility_special,
        token_ids=token_ids,
        tokens=tokens,
        rendered=rendered,
        add_generation_prompt=effective_gen_prompt,
        warnings=warnings,
    )


def chat_template_length(
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    **kwargs: Any,
) -> int:
    """Return only the templated token length (see :func:`chat_template_tokens`).

    A thin wrapper that discards everything but
    :attr:`ChatTokenCount.num_tokens`.
    """
    return chat_template_tokens(model, messages, **kwargs).num_tokens


def special_token_overhead(
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    **kwargs: Any,
) -> int:
    """Return only the special/structural-token overhead.

    The number of tokens the chat template adds on top of the raw message text
    — see :attr:`ChatTokenCount.overhead_tokens`.
    """
    return chat_template_tokens(model, messages, **kwargs).overhead_tokens


def subword_fertility(
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    *,
    include_special: bool = False,
    **kwargs: Any,
) -> float:
    """Return the subword fertility (tokens per word) of a conversation.

    Fertility is ``tokens / words``. The ``include_special`` flag selects the
    numerator:

    - ``include_special=False`` (default): the raw-text tokens only — the
      genuine subword fertility of the content
      (:attr:`ChatTokenCount.fertility`).
    - ``include_special=True``: the full chat-templated length, so the
      template's special/structural tokens are counted too
      (:attr:`ChatTokenCount.fertility_with_special`).

    Returns ``nan`` when the conversation contains no words.
    """
    result = chat_template_tokens(model, messages, **kwargs)
    return result.fertility_with_special if include_special else result.fertility


# ---------------------------------------------------------------------------
# tiktoken (externally hosted OpenAI models)
# ---------------------------------------------------------------------------


def count_tiktoken_tokens(
    text: str,
    *,
    model: str | None = None,
    encoding: str | None = None,
) -> int:
    """Count tokens with ``tiktoken`` — for the externally hosted OpenAI models.

    The proprietary models GWDG relays (GPT-5.x, o3, ...) have no downloadable
    Hugging Face tokenizer, but their byte-pair encoding is available through
    ``tiktoken``. This counts the tokens of a plain string under that encoding.

    Args:
        text: The text to tokenize.
        model: An OpenAI model id; its encoding is looked up in
            :data:`OPENAI_TIKTOKEN_ENCODINGS`, then via
            ``tiktoken.encoding_for_model``.
        encoding: An explicit ``tiktoken`` encoding name (e.g. ``"o200k_base"``)
            that overrides ``model``.

    When neither ``model`` nor ``encoding`` resolves to a known encoding
    (including the no-argument call), the count falls back to ``"o200k_base"``,
    the encoding shared by the current OpenAI models this module targets.

    Returns:
        The token count.

    Raises:
        ImportError: If the ``[tokenizer]`` extra is not installed.
    """
    tiktoken = _require("tiktoken")
    if encoding is None and model is not None:
        encoding = OPENAI_TIKTOKEN_ENCODINGS.get(model)
        if encoding is None:
            try:
                enc = tiktoken.encoding_for_model(model)
                return len(enc.encode(text))
            except Exception:  # noqa: BLE001 - fall back to a modern default
                encoding = "o200k_base"
    enc = tiktoken.get_encoding(encoding or "o200k_base")
    return len(enc.encode(text))


# ---------------------------------------------------------------------------
# Directory / RAG-corpus token distribution
# ---------------------------------------------------------------------------

#: Extensions treated as UTF-8 text and tokenized as content (RAG chunks, docs).
DEFAULT_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".mdx",
        ".txt",
        ".text",
        ".rst",
        ".org",
        ".json",
        ".jsonl",
        ".ndjson",
        ".csv",
        ".tsv",
        ".yaml",
        ".yml",
        ".toml",
        ".html",
        ".htm",
        ".xml",
        ".tex",
        ".srt",
        ".vtt",
        ".log",
        ".py",
        ".js",
        ".ts",
        ".java",
        ".c",
        ".cpp",
        ".go",
        ".rs",
        ".sh",
    }
)
#: Extensions treated as images (token cost estimated from pixel dimensions).
DEFAULT_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
)


def _percentile(sorted_vals: list[int], p: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(sorted_vals[int(k)])
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def _estimate_image_tokens(path: Path, patch_size: int) -> int | None:
    """Estimate how many tokens an image is worth, from its pixel grid.

    Coarse, model-agnostic heuristic: the number of ``patch_size``×``patch_size``
    patches covering the image (``ceil(w/p) * ceil(h/p)``). The exact count for a
    given vision model depends on its processor (pixel budget, patch merging),
    so treat this as a comparable estimate across a corpus, not an exact count.
    Returns ``None`` if Pillow is unavailable or the image cannot be read.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            width, height = im.size
    except Exception:  # noqa: BLE001 - unreadable/corrupt image -> uncounted
        return None
    patches = math.ceil(width / patch_size) * math.ceil(height / patch_size)
    return max(1, patches)


@dataclass
class FileTokenCount:
    """Token count for one file in a :func:`token_distribution` scan.

    Attributes:
        path: Path relative to the scanned root (POSIX separators).
        kind: ``"text"``, ``"image"``, or ``"skipped"``.
        num_tokens: Token count — text tokens for text files, an *estimate* for
            images (see :func:`_estimate_image_tokens`), ``0`` when skipped or
            uncounted.
        num_words: Whitespace word count (``0`` for images / skipped).
        size_bytes: File size on disk.
        note: Why a file was skipped or how its count was derived (e.g.
            ``"image estimate"``), else ``None``.
    """

    path: str
    kind: str
    num_tokens: int
    num_words: int
    size_bytes: int
    note: str | None = None


@dataclass
class TokenDistribution:
    """Token statistics over a directory of files (e.g. a RAG corpus).

    Returned by :func:`token_distribution`. The per-file rows are in
    :attr:`files`; the aggregates below summarise the counted ones (text and
    image, excluding skipped files).
    """

    model: str | None
    repo: str | None
    root: str
    files: list[FileTokenCount]
    include_special: bool = False

    @property
    def counted(self) -> list[FileTokenCount]:
        """Files that contributed a token count (text + image)."""
        return [f for f in self.files if f.kind in ("text", "image")]

    @property
    def token_counts(self) -> list[int]:
        """The per-file token counts of the counted files."""
        return [f.num_tokens for f in self.counted]

    @property
    def num_files(self) -> int:
        """Total files iterated (including skipped)."""
        return len(self.files)

    @property
    def total_tokens(self) -> int:
        return sum(self.token_counts)

    @property
    def total_words(self) -> int:
        return sum(f.num_words for f in self.files)

    def by_kind(self) -> dict[str, int]:
        """File counts grouped by ``kind`` (``text`` / ``image`` / ``skipped``)."""
        out: dict[str, int] = {}
        for f in self.files:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out

    def by_extension(self) -> dict[str, dict[str, int]]:
        """Per-extension ``{files, tokens}`` rollup (counted files only)."""
        out: dict[str, dict[str, int]] = {}
        for f in self.counted:
            ext = Path(f.path).suffix.lower() or "(none)"
            row = out.setdefault(ext, {"files": 0, "tokens": 0})
            row["files"] += 1
            row["tokens"] += f.num_tokens
        return out

    def stats(self) -> dict[str, float]:
        """Summary statistics of the per-file token counts."""
        cs = sorted(self.token_counts)
        if not cs:
            return {
                "files": 0,
                "total": 0,
                "min": 0,
                "max": 0,
                "mean": 0.0,
                "median": 0.0,
                "p90": 0.0,
                "p95": 0.0,
            }
        import statistics

        return {
            "files": len(cs),
            "total": sum(cs),
            "min": cs[0],
            "max": cs[-1],
            "mean": statistics.fmean(cs),
            "median": statistics.median(cs),
            "p90": _percentile(cs, 90),
            "p95": _percentile(cs, 95),
        }

    def histogram(self, bins: int = 10) -> list[tuple[float, float, int]]:
        """Bin the per-file token counts into ``(low, high, count)`` tuples."""
        cs = sorted(self.token_counts)
        if not cs:
            return []
        lo, hi = cs[0], cs[-1]
        if lo == hi:
            return [(float(lo), float(hi), len(cs))]
        width = (hi - lo) / bins
        counts = [0] * bins
        for v in cs:
            idx = min(int((v - lo) / width), bins - 1)
            counts[idx] += 1
        return [(lo + i * width, lo + (i + 1) * width, counts[i]) for i in range(bins)]

    def summary(self) -> str:
        """Return a one-line human-readable summary."""
        s = self.stats()
        kinds = self.by_kind()
        return (
            f"{self.num_files} files "
            f"({kinds.get('text', 0)} text, {kinds.get('image', 0)} image, "
            f"{kinds.get('skipped', 0)} skipped); {self.total_tokens} tokens; "
            f"per-file min {s['min']} / median {s['median']:.0f} / "
            f"mean {s['mean']:.1f} / p95 {s['p95']:.0f} / max {s['max']}"
        )


def token_distribution(
    directory: str | os.PathLike[str],
    model: str | None = None,
    *,
    tokenizer: Any | None = None,
    recursive: bool = True,
    include_special: bool = False,
    text_extensions: frozenset[str] | set[str] = DEFAULT_TEXT_EXTENSIONS,
    image_extensions: frozenset[str] | set[str] = DEFAULT_IMAGE_EXTENSIONS,
    count_images: bool = True,
    image_patch_size: int = 28,
    max_bytes: int | None = None,
    follow_symlinks: bool = False,
    cache_dir: str | os.PathLike[str] | None = None,
    repo: str | None = None,
    token: str | None = None,
    verbose: bool = False,
) -> TokenDistribution:
    """Tokenize every file under a directory and summarise the distribution.

    Walks ``directory`` (recursively by default, into subdirectories), tokenizes
    each text file as raw content (no chat template — these are documents / RAG
    chunks), estimates a token cost for each image, and returns a
    :class:`TokenDistribution` with per-file rows and aggregate statistics. Built
    for sizing a RAG corpus against a model's tokenizer (e.g. the embedding model
    ``qwen3-embedding-4b``).

    Either ``model`` or a preloaded ``tokenizer`` must be given.

    Args:
        directory: The root directory to scan.
        model: A GWDG model id / display name / ``org/name`` repo, used to load
            the tokenizer when ``tokenizer`` is not supplied.
        tokenizer: A preloaded tokenizer to use instead of loading one.
        recursive: Descend into subdirectories (default ``True``).
        include_special: Encode text with the tokenizer's special tokens
            (default ``False`` — count the pure content).
        text_extensions: Lower-case suffixes treated as UTF-8 text.
        image_extensions: Lower-case suffixes treated as images.
        count_images: Estimate image token costs (default ``True``). When
            ``False``, images are recorded as skipped.
        image_patch_size: Patch size for the image estimate (see
            :func:`_estimate_image_tokens`).
        max_bytes: Skip text files larger than this many bytes (``None`` = no
            limit), recording them as skipped.
        follow_symlinks: Follow symlinked files/dirs (default ``False``).
        cache_dir, repo, token: Forwarded to :func:`load_tokenizer` when a
            tokenizer must be loaded.
        verbose: Print a per-file line as it is processed.

    Returns:
        A :class:`TokenDistribution`.

    Raises:
        ValueError: If neither ``model`` nor ``tokenizer`` is given.
        NotADirectoryError: If ``directory`` is not a directory.
    """
    if tokenizer is None:
        if model is None:
            raise ValueError("Provide either a 'model' or a preloaded 'tokenizer'.")
        tokenizer = load_tokenizer(model, cache_dir=cache_dir, repo=repo, token=token)

    root = Path(directory).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    text_exts = {e.lower() for e in text_extensions}
    image_exts = {e.lower() for e in image_extensions}
    try:
        import PIL  # noqa: F401

        _pillow = True
    except ImportError:
        _pillow = False

    paths = sorted(root.rglob("*") if recursive else root.iterdir())
    rows: list[FileTokenCount] = []
    for path in paths:
        if path.is_symlink() and not follow_symlinks:
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        ext = path.suffix.lower()

        if ext in text_exts:
            if max_bytes is not None and size > max_bytes:
                rows.append(
                    FileTokenCount(rel, "skipped", 0, 0, size, "exceeds max_bytes")
                )
            else:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    n_tok = len(
                        tokenizer.encode(text, add_special_tokens=include_special)
                    )
                    rows.append(
                        FileTokenCount(rel, "text", n_tok, count_words(text), size)
                    )
                except Exception as exc:  # noqa: BLE001 - unreadable file -> skip
                    rows.append(
                        FileTokenCount(rel, "skipped", 0, 0, size, f"unreadable: {exc}")
                    )
        elif ext in image_exts:
            if not count_images:
                rows.append(
                    FileTokenCount(rel, "skipped", 0, 0, size, "image (not counted)")
                )
            else:
                est = _estimate_image_tokens(path, image_patch_size)
                if est is None:
                    why = "install Pillow to estimate" if not _pillow else "unreadable"
                    rows.append(
                        FileTokenCount(
                            rel, "image", 0, 0, size, f"image (uncounted: {why})"
                        )
                    )
                else:
                    rows.append(
                        FileTokenCount(rel, "image", est, 0, size, "image estimate")
                    )
        else:
            rows.append(
                FileTokenCount(rel, "skipped", 0, 0, size, "unsupported extension")
            )

        if verbose:
            last = rows[-1]
            print(f"  {last.kind:8} {last.num_tokens:>8}  {last.path}")

    resolved_repo = repo
    if resolved_repo is None and model is not None:
        try:
            resolved_repo = resolve_repo(model)
        except ValueError:
            resolved_repo = None

    return TokenDistribution(
        model=model,
        repo=resolved_repo,
        root=str(root),
        files=rows,
        include_special=include_special,
    )


# ---------------------------------------------------------------------------
# Client-facing service
# ---------------------------------------------------------------------------


def _repo_for_live_entry(entry: dict) -> str | None:
    """Best-effort repo for a live ``/models`` entry: by id, then by name."""
    mid = entry.get("id")
    if isinstance(mid, str):
        if mid in GWDG_MODEL_REPOS:
            return GWDG_MODEL_REPOS[mid]
        try:
            return resolve_repo(mid)
        except ValueError:
            pass
    name = entry.get("name")
    if isinstance(name, str):
        repo = _DISPLAY_NORM_TO_REPO.get(_norm(name))
        if repo:
            return repo
    return None


class TokenizerService:
    """Tokenizer access bound to a :class:`~saia_python.SAIAClient`.

    Reached as ``client.tokenizers``. Thin, stateful glue over the module-level
    functions that additionally knows the client's *live* model list, so it can
    annotate it with repositories and download the whole available set.

    Args:
        models_service: The client's :class:`~saia_python.models.ModelsService`,
            used to fetch the live model list.
        cache_dir: Default cache directory for this service's downloads
            (see :func:`tokenizer_dir`).
    """

    def __init__(
        self,
        models_service: Any | None = None,
        *,
        cache_dir: str | os.PathLike[str] | None = None,
    ):
        self._models = models_service
        self._cache_dir = cache_dir

    def available_repos(self, *, live: bool = True) -> dict[str, str | None]:
        """Map each available model id to its tokenizer repository.

        This is the answer to "does the models endpoint expose the repository?"
        — it does **not**: the live ``/models`` payload carries no repo field, so
        each live id is annotated here from the published catalogue
        (:data:`GWDG_MODEL_REPOS`). Ids with no known repository — notably the
        externally hosted proprietary models — map to ``None``.

        Args:
            live: Annotate the live ``/models`` listing. When ``False`` (or when
                no models service / the call fails), the static catalogue is
                returned instead.

        Returns:
            A mapping of model id → ``"org/name"`` repository (or ``None``).
        """
        if live and self._models is not None:
            try:
                entries = self._models.list()
            except Exception:  # noqa: BLE001 - fall back to the static catalogue
                entries = []
            if entries:
                return {
                    e.get("id"): _repo_for_live_entry(e) for e in entries if e.get("id")
                }
        return dict(GWDG_MODEL_REPOS)

    def download(self, model: str, **kwargs: Any) -> Path:
        """Download one model's tokenizer (see :func:`download_tokenizer`)."""
        kwargs.setdefault("cache_dir", self._cache_dir)
        return download_tokenizer(model, **kwargs)

    def download_all(
        self, *, open_only: bool = True, **kwargs: Any
    ) -> dict[str, Path | None]:
        """Download tokenizers for every available model.

        Wraps the live available-models listing and :func:`download_tokenizer`.
        With ``open_only=True`` (default) only the models with a known
        downloadable repository are attempted, so the proprietary external
        models are skipped rather than reported as failures.

        Args:
            open_only: Restrict to models with a known tokenizer repository.
            **kwargs: Forwarded to :func:`download_all_tokenizers`
                (``token``, ``force``, ``verbose``, ``cache_dir``).

        Returns:
            A mapping of model id → local directory (or ``None`` on failure).
        """
        kwargs.setdefault("cache_dir", self._cache_dir)
        repos = self.available_repos(live=True)
        models = (
            [mid for mid, repo in repos.items() if repo] if open_only else list(repos)
        )
        return download_all_tokenizers(models=models, **kwargs)

    def load(self, model: str, **kwargs: Any) -> PreTrainedTokenizerBase:
        """Load one model's tokenizer (see :func:`load_tokenizer`)."""
        kwargs.setdefault("cache_dir", self._cache_dir)
        return load_tokenizer(model, **kwargs)

    def chat_template_tokens(
        self,
        model: str | None = None,
        messages: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> ChatTokenCount:
        """Tokenize a conversation (see :func:`chat_template_tokens`)."""
        kwargs.setdefault("cache_dir", self._cache_dir)
        return chat_template_tokens(model, messages, **kwargs)

    def token_distribution(
        self,
        directory: str | os.PathLike[str],
        model: str | None = None,
        **kwargs: Any,
    ) -> TokenDistribution:
        """Tokenize a directory of files (see :func:`token_distribution`)."""
        kwargs.setdefault("cache_dir", self._cache_dir)
        return token_distribution(directory, model, **kwargs)

    def __repr__(self) -> str:
        return f"TokenizerService(cache_dir={tokenizer_dir(self._cache_dir)!r})"
