"""Main SAIA client — composes all services."""

from __future__ import annotations

from typing import Optional

import requests as _requests

from .arcana import ArcanaService
from .auth import load_api_key, load_config
from .chat import ChatService
from .documents import DocumentService
from .models import ModelsService
from .rate_limits import RateLimitInfo, parse_rate_limits
from .voice import VoiceService

DEFAULT_BASE_URL = "https://chat-ai.academiccloud.de/v1"


def resolve_base_url(explicit: str | None = None) -> str:
    """Resolve the SAIA API base URL.

    Resolution order: explicit parameter > ``[saia] base_url`` in
    ``config.toml`` > hardcoded default.

    Args:
        explicit: An explicit URL. If provided, returned as-is (trailing
            slash stripped).

    Returns:
        The resolved base URL string.
    """
    if explicit is not None:
        return explicit.rstrip("/")
    config = load_config()
    toml_url = config.get("saia", {}).get("base_url", "")
    if isinstance(toml_url, str) and toml_url.strip():
        return toml_url.strip().rstrip("/")
    return DEFAULT_BASE_URL


class SAIAClient:
    """High-level client for the GWDG SAIA platform.

    Provides access to Chat, Voice AI, ARCANA, Documents, and model
    listing through a shared, authenticated HTTP session. An OpenAI-
    compatible client is available via the ``.openai`` property.

    Args:
        api_key: Your SAIA API key. If omitted, the key is resolved
            automatically — see :func:`~saia_python.load_api_key` for the
            resolution order.
        base_url: Base URL for the SAIA API. Resolution order:
            explicit parameter > ``[saia] base_url`` in ``config.toml`` >
            hardcoded default (``https://chat-ai.academiccloud.de/v1``).
        key_file: Explicit path to a ``.saia_api`` or ``.env`` file.
            Ignored when ``api_key`` is provided.

    Example::

        # All settings resolved automatically
        client = SAIAClient()

        # Native services
        client.chat.completions(model="...", messages=[...])

        # OpenAI-compatible client (requires pip install saia-python[openai])
        client.openai.chat.completions.create(model="...", messages=[...])
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        key_file: Optional[str] = None,
    ):
        self._api_key = api_key if api_key is not None else load_api_key(key_file)
        self._base_url = resolve_base_url(base_url)
        self._session = _requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
            }
        )

        self._chat: ChatService | None = None
        self._voice: VoiceService | None = None
        self._models: ModelsService | None = None
        self._arcana: ArcanaService | None = None
        self._documents: DocumentService | None = None
        self._openai = None
        self._openai_async = None

    @property
    def chat(self) -> ChatService:
        """Chat completions service."""
        if self._chat is None:
            self._chat = ChatService(self._session, self._base_url)
        return self._chat

    @property
    def voice(self) -> VoiceService:
        """Voice AI (transcription/translation) service."""
        if self._voice is None:
            self._voice = VoiceService(self._session, self._base_url)
        return self._voice

    @property
    def models(self) -> ModelsService:
        """Model listing service."""
        if self._models is None:
            self._models = ModelsService(self._session, self._base_url)
        return self._models

    @property
    def arcana(self) -> ArcanaService:
        """ARCANA/RAG service."""
        if self._arcana is None:
            self._arcana = ArcanaService(
                self._session, self._base_url, self._api_key
            )
        return self._arcana

    @property
    def documents(self) -> DocumentService:
        """Document conversion (Docling) service."""
        if self._documents is None:
            self._documents = DocumentService(self._session, self._base_url)
        return self._documents

    @property
    def openai(self):
        """OpenAI-compatible synchronous client.

        Returns an ``openai.OpenAI`` instance configured with the same
        API key and base URL as this client. Requires
        ``pip install saia-python[openai]``.

        Example::

            response = client.openai.chat.completions.create(
                model="llama-3.3-70b-instruct",
                messages=[{"role": "user", "content": "Hello!"}],
            )
        """
        if self._openai is None:
            from .openai_compat import create_openai_client
            self._openai = create_openai_client(
                api_key=self._api_key, base_url=self._base_url,
            )
        return self._openai

    @property
    def openai_async(self):
        """OpenAI-compatible asynchronous client.

        Returns an ``openai.AsyncOpenAI`` instance. Requires
        ``pip install saia-python[openai]``.
        """
        if self._openai_async is None:
            from .openai_compat import create_openai_client
            self._openai_async = create_openai_client(
                api_key=self._api_key, base_url=self._base_url,
                async_client=True,
            )
        return self._openai_async

    def get_rate_limits(self) -> RateLimitInfo:
        """Fetch current rate-limit status by making a lightweight API call.

        Uses a GET to ``/chat/completions`` which returns 400 but includes
        rate-limit headers.

        Returns:
            Parsed :class:`RateLimitInfo`.
        """
        resp = self._session.get(f"{self._base_url}/chat/completions")
        return parse_rate_limits(resp.headers)

    def arcana_version(self) -> str:
        """Return the ARCANA API version string.

        Calls ``GET /arcanas/api/v1/version``.

        Returns:
            The version string (e.g. ``"0.4.16"``).
        """
        resp = self._session.get(
            f"{self._base_url}/arcanas/api/v1/version",
            headers={"Authorization": self._api_key, "Accept": "application/json"},
        )
        from .exceptions import raise_for_status
        raise_for_status(resp)
        return resp.json().get("version", "")

    def arcana_heartbeat(self) -> bool:
        """Check if the ARCANA service is alive.

        Calls ``GET /arcanas/api/v1/heartbeat``. Returns ``True`` if the
        service responds with 204, ``False`` otherwise.

        Returns:
            ``True`` if the service is reachable.
        """
        try:
            resp = self._session.get(
                f"{self._base_url}/arcanas/api/v1/heartbeat",
                headers={"Authorization": self._api_key, "Accept": "application/json"},
                timeout=10,
            )
            return resp.status_code == 204
        except Exception:
            return False

    def __repr__(self):
        return f"SAIAClient(base_url={self._base_url!r})"
