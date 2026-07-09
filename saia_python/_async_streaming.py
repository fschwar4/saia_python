"""Async SSE streaming — the ``httpx.AsyncClient`` twin of :mod:`saia_python._streaming`.

``httpx`` only exposes a streamed body inside an ``async with client.stream(...)``
context, so unlike the sync :class:`~saia_python._streaming.SSEStream` (which
wraps an already-open ``requests`` response) this class **owns** that context
manager: :meth:`AsyncSSEStream.open` enters it — retrying an initial 429 *before*
any body is exposed, exactly like the sync path — and :meth:`aclose` / the
``async with`` protocol exits it.

Like :mod:`saia_python._async_http`, this module never imports ``httpx`` at
runtime; it only calls methods on the client / response the caller supplies,
staying import-safe without the ``[async]`` extra and trivially fakeable in tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from ._async_http import AsyncSleep
from ._http import RetryPolicy, _jitter, _plan
from .exceptions import raise_for_status
from .rate_limits import parse_rate_limits

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)


class AsyncSSEStream:
    """Async iterable over the SSE chunks of an ``httpx`` streaming response.

    The async twin of :class:`~saia_python._streaming.SSEStream`. Two
    consumption modes — pick **one**, because a streamed body can only be read
    once:

    * ``async for chunk in stream`` — decoded ``dict`` chunks (the high-level
      API). Surfaces a typed error (:class:`~saia_python.RateLimitError` with an
      informative message on 429, etc.) *before* the first chunk if the upstream
      status is an error.
    * ``async for line in stream.aiter_lines()`` — the raw decoded ``str`` SSE
      lines. Does **not** raise, so a gateway can frame upstream errors itself
      (this is what the AVOR adapter uses to keep its verbatim ``[DONE]`` /
      non-``data:`` line passthrough).

    Either way, use it as an async context manager (``async with stream:``) or
    call :meth:`aclose` so the upstream connection is released.

    Attributes:
        status_code: The final upstream status code (after any retry).
        rate_limits: A JSON-serializable dict of the response's rate-limit
            headers (available immediately — headers arrive before the body).
    """

    def __init__(self, cm: Any, response: httpx.Response):
        self._cm: Any = cm
        self._response = response
        self.status_code: int = response.status_code
        self.rate_limits: dict = parse_rate_limits(response.headers).to_dict()

    @classmethod
    async def open(
        cls,
        client: httpx.AsyncClient,
        url: str,
        *,
        json: dict,
        headers: dict | None = None,
        policy: RetryPolicy | None = None,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> AsyncSSEStream:
        """Open the stream, retrying an initial 429 before exposing the body.

        Mirrors :func:`saia_python._http.execute`'s retry loop, but over
        ``client.stream(...)``: it enters the context, and on a retryable 429
        exits it (releasing the socket) and re-issues after the planned wait.
        Only status + headers are inspected, so the streamed body is never
        consumed by the retry decision. Returns a connected stream whose
        ``status_code`` reflects the final attempt (which may still be an error
        the caller inspects).
        """
        policy = policy if policy is not None else RetryPolicy()
        attempt = 0
        while True:
            cm = client.stream("POST", url, json=json, headers=headers)
            response = await cm.__aenter__()
            if response.status_code != 429 or not policy.applies(True):
                return cls(cm, response)
            wait = _plan(parse_rate_limits(response.headers), policy, attempt)
            if wait is None:
                return cls(cm, response)
            await cm.__aexit__(None, None, None)
            attempt += 1
            wait += _jitter(policy)
            log.info(
                "SAIA rate limit (429) — waiting %.1fs before retry %d", wait, attempt
            )
            await sleep(wait)

    async def aiter_lines(self) -> AsyncIterator[str]:
        """Yield the raw decoded SSE lines (no dict parsing, no raise).

        The low-level surface: the caller sees every line verbatim (``data:``
        payloads, ``data: [DONE]``, blank event terminators) and decides how to
        frame errors and what to forward. Releases the connection when the
        consumer stops, whether it finished, broke early, or was cancelled.
        """
        try:
            async for raw in self._response.aiter_lines():
                yield raw if isinstance(raw, str) else raw.decode("utf-8")
        finally:
            await self.aclose()

    async def __aiter__(self) -> AsyncIterator[dict]:
        """Yield decoded ``dict`` chunks (high-level; raises on an error status).

        Copies the sync :func:`~saia_python._streaming.iter_sse` decision logic
        verbatim: skip non-``data:`` lines, stop on ``[DONE]``, ``json.loads``
        each payload, silently skip an unparseable one.
        """
        if self.status_code >= 400:
            await self._response.aread()
            raise_for_status(self._response)
        try:
            async for raw in self._response.aiter_lines():
                line = raw if isinstance(raw, str) else raw.decode("utf-8")
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    continue
        finally:
            await self.aclose()

    async def aread(self) -> bytes:
        """Read and return the full upstream body (used to frame an error)."""
        return await self._response.aread()

    async def aclose(self) -> None:
        """Release the upstream connection. Idempotent."""
        if self._cm is not None:
            cm, self._cm = self._cm, None
            await cm.__aexit__(None, None, None)

    async def __aenter__(self) -> AsyncSSEStream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
