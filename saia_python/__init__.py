"""SAIA Python — a wrapper for the GWDG SAIA platform REST API.

Provides both an object-oriented and a functional interface::

    # OOP
    from saia_python import SAIAClient
    client = SAIAClient(api_key="...")
    client.models.list_ids()

    # Functional
    from saia_python import list_model_ids, chat_completion
    list_model_ids()
"""

from __future__ import annotations

import concurrent.futures
from importlib.metadata import PackageNotFoundError, version

from ._streaming import SSEStream
from .arcana_references import (
    ArcanaReference,
    ParsedReferences,
    is_arcana_event,
    parse_arcana_references,
    parse_reference_entries,
)
from .auth import (
    DEFAULT_BASE_URL,
    add_arcana_to_config,
    load_api_key,
    load_arcana_ids,
    load_config,
    load_username,
    remove_arcana_from_config,
    resolve_base_url,
)
from .client import SAIAClient
from .documents import ConversionResult
from .exceptions import APIError, AuthenticationError, RateLimitError, SAIAError
from .openai_compat import create_openai_client
from .rate_limits import RateLimitInfo, parse_rate_limits
from .responses import text_of

try:
    __version__ = version("saia-python")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = [
    # Meta
    "__version__",
    # Client
    "SAIAClient",
    "resolve_base_url",
    "DEFAULT_BASE_URL",
    "create_openai_client",
    # Auth
    "load_api_key",
    "load_arcana_ids",
    "load_config",
    "load_username",
    "add_arcana_to_config",
    "remove_arcana_from_config",
    # Exceptions
    "SAIAError",
    "AuthenticationError",
    "RateLimitError",
    "APIError",
    # Rate limits
    "RateLimitInfo",
    "parse_rate_limits",
    # Response helpers
    "text_of",
    "SSEStream",
    # ARCANA reference parsing
    "ArcanaReference",
    "ParsedReferences",
    "parse_arcana_references",
    "parse_reference_entries",
    "is_arcana_event",
    # Functional API
    "list_models",
    "list_model_ids",
    "chat_completion",
    "transcribe",
    "translate",
    "list_arcanas",
    "get_arcana",
    "upload_to_arcana",
    "arcana_chat",
    "get_rate_limits",
    "convert_document",
    "ConversionResult",
]


def _make_client(api_key: str | None = None, base_url: str | None = None) -> SAIAClient:
    kwargs: dict = {}
    if api_key is not None:
        kwargs["api_key"] = api_key
    if base_url is not None:
        kwargs["base_url"] = base_url
    return SAIAClient(**kwargs)


# --- Models ---


def list_models(
    *, api_key: str | None = None, base_url: str | None = None
) -> list[dict]:
    """List all available models (functional API)."""
    return _make_client(api_key, base_url).models.list()


def list_model_ids(
    *, api_key: str | None = None, base_url: str | None = None
) -> list[str]:
    """List model ID strings (functional API)."""
    return _make_client(api_key, base_url).models.list_ids()


# --- Chat ---


def chat_completion(
    model: str,
    messages: list[dict],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> dict | SSEStream:
    """Send a chat completion request (functional API).

    See :meth:`ChatService.completions` for full parameter docs. With
    ``stream=True`` this returns an iterable ``SSEStream`` instead of a dict.
    """
    return _make_client(api_key, base_url).chat.completions(
        model=model, messages=messages, **kwargs
    )


# --- Voice ---


def transcribe(
    file_path: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> str | concurrent.futures.Future[str]:
    """Transcribe an audio file (functional API).

    See :meth:`VoiceService.transcribe` for full parameter docs. Passing
    ``wait=False`` returns a :class:`concurrent.futures.Future` instead of
    the transcription string.
    """
    return _make_client(api_key, base_url).voice.transcribe(file_path, **kwargs)


def translate(
    file_path: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> str | concurrent.futures.Future[str]:
    """Translate an audio file to English (functional API).

    See :meth:`VoiceService.translate` for full parameter docs. Passing
    ``wait=False`` returns a :class:`concurrent.futures.Future` instead of
    the translation string.
    """
    return _make_client(api_key, base_url).voice.translate(file_path, **kwargs)


# --- ARCANA ---


def list_arcanas(
    *, api_key: str | None = None, base_url: str | None = None
) -> list[dict]:
    """List all arcanas (functional API)."""
    return _make_client(api_key, base_url).arcana.list()


def get_arcana(
    name: str, *, api_key: str | None = None, base_url: str | None = None
) -> dict:
    """Get a specific arcana by name (functional API)."""
    return _make_client(api_key, base_url).arcana.get(name)


def upload_to_arcana(
    name: str,
    file_path: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict | None:
    """Upload a file to an arcana (functional API)."""
    return _make_client(api_key, base_url).arcana.upload(name, file_path)


def arcana_chat(
    model: str,
    messages: list[dict],
    arcana_id: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> dict | SSEStream:
    """Chat with RAG context from an arcana (functional API).

    With ``stream=True`` this returns an iterable ``SSEStream`` instead of a dict.
    """
    return _make_client(api_key, base_url).arcana.chat(
        model=model, messages=messages, arcana_id=arcana_id, **kwargs
    )


# --- Rate Limits ---


def get_rate_limits(
    *, api_key: str | None = None, base_url: str | None = None
) -> RateLimitInfo:
    """Fetch current rate-limit status (functional API)."""
    return _make_client(api_key, base_url).get_rate_limits()


# --- Documents ---


def convert_document(
    file_path: str,
    *,
    response_type: str = "markdown",
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> ConversionResult:
    """Convert a document using the Docling service (functional API).

    See :meth:`DocumentService.convert` for full parameter docs.
    """
    return _make_client(api_key, base_url).documents.convert(
        file_path, response_type=response_type, **kwargs
    )
