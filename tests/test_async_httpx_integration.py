"""Real-httpx integration tests via ``httpx.MockTransport`` (no network).

The other async tests use duck-typed fakes for speed + zero deps; these exercise
the async transport against a genuine ``httpx.AsyncClient`` to close fake-fidelity
gaps. Most important: a real streamed httpx response raises ``ResponseNotRead``
on ``.text``/``.json()`` until ``aread()`` — so the streamed-error path must read
the body before raising, which the fakes (whose ``.text`` is always available)
cannot pin.

Skipped if the ``[async]`` extra (httpx) is not installed.
"""

from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from saia_python._http import RetryPolicy  # noqa: E402
from saia_python.aio import AsyncArcanaService, AsyncSSEStream, aexecute  # noqa: E402
from saia_python.exceptions import RateLimitError  # noqa: E402

_SSE = b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
_RL = {"x-ratelimit-limit-minute": "30", "x-ratelimit-remaining-minute": "29"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok_handler(request):
    body = json.loads(request.content) if request.content else {}
    if body.get("stream"):
        return httpx.Response(200, headers=_RL, content=_SSE)
    return httpx.Response(
        200, headers=_RL, json={"choices": [{"message": {"content": "hi"}}]}
    )


def test_aexecute_non_stream_real_httpx():
    async def _run():
        async with _client(_ok_handler) as c:
            return await aexecute(
                c,
                "post",
                "http://t/chat/completions",
                policy=RetryPolicy(False),
                idempotent=True,
                json={"model": "m", "messages": []},
            )

    r = asyncio.run(_run())
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hi"


def test_async_sse_stream_decoded_real_httpx():
    async def _run():
        async with _client(_ok_handler) as c:
            stream = await AsyncSSEStream.open(
                c, "http://t/chat/completions", json={"stream": True}, headers={}
            )
            return [chunk async for chunk in stream]

    chunks = asyncio.run(_run())
    assert chunks == [{"choices": [{"delta": {"content": "Hi"}}]}]


def test_async_sse_stream_raw_lines_real_httpx():
    async def _run():
        async with _client(_ok_handler) as c:
            stream = await AsyncSSEStream.open(
                c, "http://t/chat/completions", json={"stream": True}, headers={}
            )
            return [ln async for ln in stream.aiter_lines()]

    lines = asyncio.run(_run())
    assert any('"content":"Hi"' in ln for ln in lines)
    assert "data: [DONE]" in lines


def test_async_sse_stream_error_reads_body_then_raises_real_httpx():
    """A streamed 429 must ``aread()`` before ``raise_for_status`` — else real
    httpx raises ``ResponseNotRead`` instead of the informative RateLimitError."""

    def handler(request):
        return httpx.Response(
            429,
            headers={
                **_RL,
                "x-ratelimit-remaining-minute": "0",
                "ratelimit-reset": "7",
            },
            json={"detail": "slow down"},
        )

    async def _run():
        async with _client(handler) as c:
            stream = await AsyncSSEStream.open(
                c,
                "http://t/chat/completions",
                json={"stream": True},
                headers={},
                policy=RetryPolicy(False),
            )
            return [chunk async for chunk in stream]

    with pytest.raises(RateLimitError) as exc:
        asyncio.run(_run())
    assert exc.value.status_code == 429
    assert exc.value.rate_limits.reset_seconds == 7
    assert "slow down" in str(exc.value)


def test_async_arcana_chat_real_httpx():
    seen: dict = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx.Response(
            200, headers=_RL, json={"choices": [{"message": {"content": "ok"}}]}
        )

    async def _run():
        async with _client(handler) as c:
            svc = AsyncArcanaService(c, "http://t", "KEY")
            return await svc.chat("m", [{"role": "user", "content": "hi"}], "owner/kb")

    res = asyncio.run(_run())
    assert res["choices"][0]["message"]["content"] == "ok"
    # The Rule #6 triple actually reaches the wire (real httpx request).
    assert seen["body"]["enable-tools"] is True
    assert seen["body"]["arcana"] == {"id": "owner/kb"}
    assert seen["headers"]["inference-service"] == "saia-openai-gateway"
    assert seen["headers"]["authorization"] == "Bearer KEY"
