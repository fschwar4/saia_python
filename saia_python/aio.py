"""Async client for the GWDG SAIA platform — the ``httpx`` twin of the sync API.

Requires the ``[async]`` extra::

    pip install saia-python[async]

Usage mirrors :class:`~saia_python.SAIAClient`, with ``await`` on the network
calls and ``async for`` over a stream::

    from saia_python.aio import AsyncSAIAClient

    async with AsyncSAIAClient() as client:
        # non-streaming RAG chat
        answer = await client.arcana.chat(
            model="openai-gpt-oss-120b",
            messages=[{"role": "user", "content": "..."}],
            arcana_id="owner/kb",
        )
        # streaming plain chat
        stream = await client.chat.completions(
            model="...", messages=[...], stream=True,
        )
        async for chunk in stream:
            ...

**Scope.** The async layer covers the **data plane** — chat completions and
ARCANA RAG chat (streaming + non-streaming), the rate-limit
:class:`~saia_python.RetryPolicy` as a per-call ``retry`` keyword, rate-limit
surfacing, and an informative 429 error when retry is off — plus the
lightweight read-only control-plane calls (``models``, arcana
``version``/``heartbeat``/``list``/``get``, ``health_check``). File
management (upload / index / sync), voice transcription, and document
conversion stay **sync-only** on :class:`~saia_python.SAIAClient`: batch/admin
work with blocking file I/O and no concurrency benefit. See
``docs/adr/0007-native-async-transport.md``.

The retry semantics are identical to the sync path (same
:class:`~saia_python.RetryPolicy`, ``_plan``, jitter — imported, not copied), so
the two transports cannot drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._async_http import aexecute, apost_chat_completion
from ._async_streaming import AsyncSSEStream
from ._http import RetryPolicy, coerce_retry, resolve_retry
from ._payloads import (
    apply_arcana_fields,
    arcana_chat_headers,
    build_chat_body,
)
from .auth import resolve_credentials
from .exceptions import raise_for_status
from .rate_limits import RateLimitInfo, parse_rate_limits

if TYPE_CHECKING:
    import httpx

_ARCANA_PATH = "/arcanas/api/v1"

# Data-plane default: a long read so a legitimately slow RAG/chat answer (which
# can run for minutes) is not truncated. The read-only control-plane calls pass
# their own short per-request cap instead. Mirrors the sync split (the chat path
# is exempt from the control-plane timeout). httpx wants a float/httpx.Timeout,
# not the requests-style (connect, read) tuple, so these are plain floats.
_DATA_PLANE_READ_TIMEOUT = 300.0
_CONTROL_PLANE_TIMEOUT = 60.0

__all__ = [
    "AsyncSAIAClient",
    "AsyncChatService",
    "AsyncArcanaService",
    "AsyncModelsService",
    "AsyncSSEStream",
    "aexecute",
    "apost_chat_completion",
]


def _require_httpx() -> Any:
    """Import ``httpx`` or raise a pointed error naming the ``[async]`` extra."""
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - trivial import guard
        raise ImportError(
            "The async client requires the optional 'httpx' dependency. "
            "Install it with:\n    pip install saia-python[async]"
        ) from exc
    return httpx


class AsyncChatService:
    """Async access to ``/chat/completions`` (the twin of :class:`~saia_python.chat.ChatService`)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        *,
        retry: RetryPolicy | bool | None = None,
    ):
        self._client = client
        self._base_url = base_url
        self._retry = coerce_retry(retry)

    async def completions(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        retry: RetryPolicy | bool | None = None,
        **kwargs: Any,
    ) -> dict | AsyncSSEStream:
        """Send a chat completion request. See :meth:`ChatService.completions`.

        With ``stream=False`` returns the response dict (plus a ``_rate_limits``
        key); with ``stream=True`` returns an :class:`AsyncSSEStream` to iterate.
        ``retry`` overrides the service policy for this call (``False`` fails
        fast on a 429 with an informative :class:`~saia_python.RateLimitError`).
        """
        body = build_chat_body(
            model,
            messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            **kwargs,
        )
        return await apost_chat_completion(
            self._client,
            f"{self._base_url}/chat/completions",
            body,
            stream=stream,
            policy=resolve_retry(self._retry, retry),
        )

    def __repr__(self) -> str:
        return f"AsyncChatService(base_url={self._base_url!r})"


class AsyncArcanaService:
    """Async access to the ARCANA data plane + read-only control plane.

    Covers RAG :meth:`chat` (the point of the async layer) plus the cheap
    read-only management calls (:meth:`version`, :meth:`heartbeat`,
    :meth:`user_info`, :meth:`list`, :meth:`get`). Uploads, indexing, and
    directory sync stay on the sync :class:`~saia_python.arcana.ArcanaService`.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        *,
        timeout: float | None = _CONTROL_PLANE_TIMEOUT,
        retry: RetryPolicy | bool | None = None,
    ):
        self._client = client
        self._base_url = base_url
        self._arcana_base = f"{base_url}{_ARCANA_PATH}"
        self._api_key = api_key
        self._timeout = timeout
        self._retry = coerce_retry(retry)

    def _headers(self, **extra: str) -> dict:
        # Control plane uses the raw key (no Bearer prefix), unlike chat().
        return {"Authorization": self._api_key, "Accept": "application/json", **extra}

    async def chat(
        self,
        model: str,
        messages: list[dict],
        arcana_id: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        retry: RetryPolicy | bool | None = None,
        api_key: str | None = None,
        extra_headers: dict | None = None,
        **kwargs: Any,
    ) -> dict | AsyncSSEStream:
        """Chat with RAG context from an arcana (async twin of :meth:`ArcanaService.chat`).

        The three-part ARCANA injection (``enable-tools`` + ``arcana.id`` body
        fields and the ``inference-service`` header) comes from the shared
        :func:`~saia_python._payloads.apply_arcana_fields` /
        :func:`~saia_python._payloads.arcana_chat_headers`, so it matches the
        sync :meth:`ArcanaService.chat`. One deliberate difference: the injection
        is applied **last**, so the retrieval fields cannot be disabled by a
        stray caller key (the sync path lets a ``**kwargs`` override win) — the
        Rule #6-safe behaviour.

        Args:
            api_key: Override the instance key for this call — lets one pooled
                async client serve many users (each request authenticated
                separately), which a shared multi-user gateway needs.
            extra_headers: Extra headers merged into the request (e.g. an
                ``X-Request-ID`` for cross-referencing upstream logs).
        """
        body = apply_arcana_fields(
            build_chat_body(
                model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ),
            arcana_id,
        )
        headers = arcana_chat_headers(api_key or self._api_key, extra=extra_headers)
        return await apost_chat_completion(
            self._client,
            f"{self._base_url}/chat/completions",
            body,
            headers=headers,
            stream=stream,
            policy=resolve_retry(self._retry, retry),
        )

    async def _get_json(
        self, url: str, *, timeout: Any = None, retry: Any = None
    ) -> Any:
        resp = await aexecute(
            self._client,
            "get",
            url,
            policy=resolve_retry(self._retry, retry),
            idempotent=True,
            headers=self._headers(),
            timeout=timeout if timeout is not None else self._timeout,
        )
        raise_for_status(resp)
        return resp.json()

    async def version(self) -> str:
        """Return the ARCANA API version string."""
        data = await self._get_json(f"{self._arcana_base}/version")
        return data.get("version", "") if isinstance(data, dict) else str(data)

    async def heartbeat(self) -> bool:
        """Return ``True`` if the ARCANA backend answers 204 (fast, no retry)."""
        try:
            resp = await aexecute(
                self._client,
                "get",
                f"{self._arcana_base}/heartbeat",
                policy=coerce_retry(False),
                idempotent=True,
                headers=self._headers(),
                timeout=10.0,
            )
        except Exception:
            return False
        return resp.status_code == 204

    async def user_info(self) -> dict:
        """Return the current user's profile + arcana statistics."""
        return await self._get_json(f"{self._arcana_base}/user/me")

    async def list(self) -> list[dict]:
        """List the caller's arcanas."""
        return await self._get_json(f"{self._arcana_base}/arcana/")

    async def get(self, name: str) -> dict:
        """Get one arcana by name (accepts ``owner/name`` or ``name``)."""
        from urllib.parse import quote

        from .arcana import extract_arcana_name

        short = extract_arcana_name(name)
        return await self._get_json(f"{self._arcana_base}/arcana/{quote(short)}")

    def __repr__(self) -> str:
        return f"AsyncArcanaService(base_url={self._base_url!r})"


class AsyncModelsService:
    """Async model listing (read-only twin of :class:`~saia_python.models.ModelsService`)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        *,
        timeout: float | None = _CONTROL_PLANE_TIMEOUT,
    ):
        self._client = client
        self._base_url = base_url
        self._timeout = timeout

    async def list_raw(self) -> dict:
        """Return the raw ``GET /models`` payload."""
        # Cap the read at the control-plane timeout (not the client-wide
        # data-plane read, which is long for chat) so a wedged /models probe
        # fails fast instead of hanging — mirrors the sync ModelsService.
        resp = await self._client.get(f"{self._base_url}/models", timeout=self._timeout)
        raise_for_status(resp)
        return resp.json()

    async def list(self) -> list[dict]:
        """Return the list of model dicts (unwrapping the ``{"data": [...]}``)."""
        payload = await self.list_raw()
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"]
        return payload if isinstance(payload, list) else []

    async def list_ids(self) -> list[str]:
        """Return the model id strings, de-duplicated in first-seen order.

        Coalesces the same id keys as the sync :meth:`ModelsService.list_ids`
        (``id`` / ``modelId`` / ``model_id`` / ``model`` / ``name`` /
        ``model_name``) so a non-OpenAI-shaped gateway payload still yields ids.
        """
        seen: dict[str, None] = {}
        for model in await self.list():
            if not isinstance(model, dict):
                continue
            mid = (
                model.get("id")
                or model.get("modelId")
                or model.get("model_id")
                or model.get("model")
                or model.get("name")
                or model.get("model_name")
            )
            if isinstance(mid, str) and mid:
                seen.setdefault(mid, None)
        return list(seen)

    def __repr__(self) -> str:
        return f"AsyncModelsService(base_url={self._base_url!r})"


class AsyncSAIAClient:
    """Async, connection-pooled client for the SAIA data plane.

    Owns one ``httpx.AsyncClient`` (shared across services for connection
    pooling). Use it as an async context manager so the pool is closed::

        async with AsyncSAIAClient() as client:
            await client.chat.completions(model="...", messages=[...])

    Credential + base-URL resolution is identical to
    :class:`~saia_python.SAIAClient` (delegated to the same
    :func:`~saia_python.auth.resolve_credentials`).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        key_file: str | None = None,
        *,
        timeout: Any = None,
        retry: RetryPolicy | bool | None = None,
    ):
        httpx = _require_httpx()
        self._api_key, self._base_url = resolve_credentials(api_key, base_url, key_file)
        self._retry = coerce_retry(retry)
        if timeout is None:
            timeout = httpx.Timeout(
                connect=10.0, read=_DATA_PLANE_READ_TIMEOUT, write=10.0, pool=10.0
            )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
            },
        )
        self._chat: AsyncChatService | None = None
        self._arcana: AsyncArcanaService | None = None
        self._models: AsyncModelsService | None = None

    @property
    def chat(self) -> AsyncChatService:
        """Async chat completions service."""
        if self._chat is None:
            self._chat = AsyncChatService(
                self._client, self._base_url, retry=self._retry
            )
        return self._chat

    @property
    def arcana(self) -> AsyncArcanaService:
        """Async ARCANA/RAG service (data plane + read-only control plane)."""
        if self._arcana is None:
            self._arcana = AsyncArcanaService(
                self._client, self._base_url, self._api_key, retry=self._retry
            )
        return self._arcana

    @property
    def models(self) -> AsyncModelsService:
        """Async model listing service."""
        if self._models is None:
            self._models = AsyncModelsService(self._client, self._base_url)
        return self._models

    async def get_rate_limits(self) -> RateLimitInfo:
        """Fetch current rate-limit status via a lightweight probe.

        A ``GET /chat/completions`` returns 400 (missing body) but carries the
        rate-limit headers; a 401/403 is surfaced as
        :class:`~saia_python.AuthenticationError`.
        """
        resp = await self._client.get(f"{self._base_url}/chat/completions")
        if resp.status_code in (401, 403):
            raise_for_status(resp)
        return parse_rate_limits(resp.headers)

    async def arcana_version(self) -> str:
        """Return the ARCANA API version string."""
        return await self.arcana.version()

    async def arcana_heartbeat(self) -> bool:
        """Return ``True`` if the ARCANA backend is reachable (204)."""
        return await self.arcana.heartbeat()

    async def health_check(self, *, verbose: bool = False) -> bool | dict:
        """Verify the client can reach + authenticate against the API.

        Combines ``GET /models`` (auth + chat backend) with the ARCANA
        heartbeat. Returns a bool, or a diagnostic dict with ``verbose=True``.
        """
        details: dict = {
            "base_url": self._base_url,
            "models_ok": False,
            "model_count": 0,
            "arcana_ok": False,
            "error": None,
        }
        try:
            model_ids = await self.models.list_ids()
            details["models_ok"] = True
            details["model_count"] = len(model_ids)
        except Exception as exc:
            details["error"] = f"models: {exc}"
        details["arcana_ok"] = await self.arcana_heartbeat()
        if not details["arcana_ok"] and details["error"] is None:
            details["error"] = "arcana heartbeat returned non-204"
        details["ok"] = details["models_ok"] and details["arcana_ok"]
        return details if verbose else bool(details["ok"])

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` (release the pool)."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSAIAClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"AsyncSAIAClient(base_url={self._base_url!r})"
