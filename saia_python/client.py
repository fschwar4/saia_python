"""Main SAIA client — composes all services."""

from __future__ import annotations

import requests as _requests

from ._http import DEFAULT_TIMEOUT
from .arcana import ArcanaService
from .auth import resolve_credentials
from .chat import ChatService
from .documents import DocumentService
from .exceptions import raise_for_status
from .models import ModelsService
from .rate_limits import RateLimitInfo, parse_rate_limits
from .voice import VoiceService


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
        timeout: Default ``(connect, read)`` timeout in seconds for ARCANA
            management calls, forwarded to :class:`~saia_python.arcana.ArcanaService`.
            Stops those calls from hanging forever when the server accepts a
            request but never responds (e.g. while an arcana is locked
            mid-(re)index). A single ``float`` applies to both phases; pass
            ``None`` to disable. Defaults to ``(10, 60)``.

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
        api_key: str | None = None,
        base_url: str | None = None,
        key_file: str | None = None,
        *,
        timeout: float | tuple[float, float] | None = DEFAULT_TIMEOUT,
    ):
        self._api_key, self._base_url = resolve_credentials(api_key, base_url, key_file)
        self._timeout = timeout
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
            self._models = ModelsService(
                self._session, self._base_url, timeout=self._timeout
            )
        return self._models

    @property
    def arcana(self) -> ArcanaService:
        """ARCANA/RAG service."""
        if self._arcana is None:
            self._arcana = ArcanaService(
                self._session,
                self._base_url,
                self._api_key,
                timeout=self._timeout,
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
                api_key=self._api_key,
                base_url=self._base_url,
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
                api_key=self._api_key,
                base_url=self._base_url,
                async_client=True,
            )
        return self._openai_async

    def get_rate_limits(self) -> RateLimitInfo:
        """Fetch current rate-limit status by making a lightweight API call.

        Uses a GET to ``/chat/completions`` which returns 400 but includes
        rate-limit headers.

        Returns:
            Parsed :class:`RateLimitInfo`.

        Raises:
            AuthenticationError: If the API key is invalid or expired
                (401/403). Other non-2xx statuses (notably the expected
                400) are tolerated since they still carry the headers.
        """
        resp = self._session.get(
            f"{self._base_url}/chat/completions", timeout=self._timeout
        )
        if resp.status_code in (401, 403):
            # The probe is *expected* to 400 (missing request body) but still
            # carries rate-limit headers. A 401/403 means the key is bad, so
            # surface it instead of silently returning an empty RateLimitInfo.
            raise_for_status(resp)
        return parse_rate_limits(resp.headers)

    def arcana_version(self) -> str:
        """Return the ARCANA API version string.

        Thin delegate to :meth:`ArcanaService.version`
        (``client.arcana.version()``), which owns the ARCANA URL path and
        auth scheme.

        Returns:
            The version string (e.g. ``"0.4.16"``).
        """
        return self.arcana.version()

    def arcana_heartbeat(self) -> bool:
        """Check if the ARCANA service is alive.

        Thin delegate to :meth:`ArcanaService.heartbeat`
        (``client.arcana.heartbeat()``). Returns ``True`` if the service
        responds with 204, ``False`` otherwise.

        Returns:
            ``True`` if the service is reachable.
        """
        return self.arcana.heartbeat()

    def health_check(self, *, verbose: bool = False) -> bool | dict:
        """Verify that the client can reach the API and authenticate.

        Combines two cheap GETs:

        - ``GET /models`` (authenticated) — confirms the API key resolves
          and the chat backend is reachable.
        - ``GET /arcanas/api/v1/heartbeat`` (cheap 204) — confirms the
          ARCANA backend is reachable.

        Args:
            verbose: If ``True``, return a diagnostic dict instead of a
                bool. Useful in onboarding / setup scripts where you
                want to surface *which* leg failed.

        Returns:
            ``True`` if both legs succeed, ``False`` otherwise. With
            ``verbose=True``, a dict::

                {
                    "ok":            <bool>,
                    "base_url":      <str>,
                    "models_ok":     <bool>,
                    "model_count":   <int>,    # 0 if models leg failed
                    "arcana_ok":     <bool>,
                    "error":         <str|None>,  # first leg that failed
                }
        """
        details: dict = {
            "base_url": self._base_url,
            "models_ok": False,
            "model_count": 0,
            "arcana_ok": False,
            "error": None,
        }
        try:
            model_ids = self.models.list_ids()
            details["models_ok"] = True
            details["model_count"] = len(model_ids)
        except Exception as exc:
            details["error"] = f"models: {exc}"
        details["arcana_ok"] = self.arcana_heartbeat()
        if not details["arcana_ok"] and details["error"] is None:
            details["error"] = "arcana heartbeat returned non-204"
        details["ok"] = details["models_ok"] and details["arcana_ok"]
        return details if verbose else bool(details["ok"])

    def __repr__(self):
        return f"SAIAClient(base_url={self._base_url!r})"
