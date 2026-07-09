"""Fake ``httpx.AsyncClient`` doubles for the async-transport tests.

Mirrors the sync suite's ``MagicMock``-session pattern (a queued list of
responses, an injectable ``sleep`` recorder) but for the async seam: awaitable
``post``/``get`` and an ``async with`` ``stream(...)`` context manager. No
network, no real ``httpx`` — the transport modules only *call methods* on the
client, so a duck-typed fake is enough. Tests drive the coroutines with
``asyncio.run`` (no ``pytest-asyncio`` dependency), matching the AVOR adapter.
"""

from __future__ import annotations

import json as _json
from typing import Any


class FakeAsyncResponse:
    """Stand-in for an ``httpx.Response`` (streamed or fully read).

    With ``aread_required=True`` it models a genuinely *streamed* httpx response:
    ``.text`` / ``.json()`` raise until ``aread()`` has been awaited (real httpx
    raises ``ResponseNotRead``). This lets the streamed-error tests pin that the
    transport reads the body before ``raise_for_status`` — a fully-read fake
    (the default) cannot.
    """

    def __init__(
        self,
        status_code: int = 200,
        *,
        headers: dict | None = None,
        json_body: Any = None,
        text: str = "",
        lines: list[str] | None = None,
        body: bytes = b"",
        aread_required: bool = False,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_body
        self._text = text or (_json.dumps(json_body) if json_body is not None else "")
        self._lines = list(lines or [])
        self._body = body
        self._read = not aread_required
        self.closed = False

    @property
    def text(self) -> str:
        if not self._read:
            raise RuntimeError("ResponseNotRead: attempted .text before aread()")
        return self._text

    def json(self) -> Any:
        if not self._read:
            raise RuntimeError("ResponseNotRead: attempted .json() before aread()")
        if self._json is None:
            raise _json.JSONDecodeError("no json body", self._text or "", 0)
        return self._json

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        self._read = True
        return self._body

    async def aclose(self) -> None:
        self.closed = True


class FakeStreamCM:
    """The async context manager returned by ``client.stream(...)``."""

    def __init__(self, response: FakeAsyncResponse, *, on_exit=None):
        self._response = response
        self._on_exit = on_exit
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> FakeAsyncResponse:
        self.entered = True
        return self._response

    async def __aexit__(self, *exc: object) -> bool:
        self.exited = True
        if self._on_exit is not None:
            self._on_exit()
        return False


class FakeAsyncClient:
    """Queued-response fake for ``aexecute`` / ``AsyncSSEStream.open``.

    ``responses`` feed the awaitable ``post``/``get`` calls in order; an
    ``Exception`` in the queue is raised (to exercise the error paths).
    ``stream_responses`` feed successive ``stream(...)`` opens (for
    retry-before-stream). Every call is recorded for shape assertions.
    """

    def __init__(
        self,
        *,
        responses: list | None = None,
        stream_responses: list[FakeAsyncResponse] | None = None,
    ):
        self._responses = list(responses or [])
        self._stream_responses = list(stream_responses or [])
        self.calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self.stream_cms: list[FakeStreamCM] = []
        self.closed = 0

    async def _dispatch(
        self, method: str, url: str, **kwargs: Any
    ) -> FakeAsyncResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self._responses:
            raise AssertionError("FakeAsyncClient: no more queued responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def post(self, url: str, **kwargs: Any) -> FakeAsyncResponse:
        return await self._dispatch("post", url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> FakeAsyncResponse:
        return await self._dispatch("get", url, **kwargs)

    def stream(self, method: str, url: str, **kwargs: Any) -> FakeStreamCM:
        self.stream_calls.append({"method": method, "url": url, **kwargs})
        if self._stream_responses:
            response = self._stream_responses.pop(0)
        else:
            response = FakeAsyncResponse()

        def _on_exit() -> None:
            self.closed += 1

        cm = FakeStreamCM(response, on_exit=_on_exit)
        self.stream_cms.append(cm)
        return cm

    async def aclose(self) -> None:
        self.closed += 1


class RecordingSleep:
    """An awaitable ``sleep`` that records its waits instead of blocking."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def rl_headers(**overrides: Any) -> dict:
    """Rate-limit headers with sane defaults (minute window, plenty remaining)."""
    headers = {
        "x-ratelimit-limit-minute": "30",
        "x-ratelimit-remaining-minute": "29",
    }
    headers.update({k: str(v) for k, v in overrides.items()})
    return headers
