"""Tests for :class:`AsyncSSEStream` — the async twin of ``test_streaming.py``.

Covers both consumption modes (decoded ``dict`` chunks vs raw lines), the
error-status surfacing, ``aread`` for error framing, and the retry-before-open
loop.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from saia_python._http import RetryPolicy
from saia_python.aio import AsyncSSEStream
from saia_python.exceptions import RateLimitError

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, RecordingSleep, rl_headers

NO_JITTER = RetryPolicy(jitter=(0.0, 0.0))


def _open(client, **kwargs):
    return AsyncSSEStream.open(client, "u", json={"stream": True}, headers={}, **kwargs)


def test_decoded_chunks_stop_at_done():
    lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " world"}}]}',
        "data: [DONE]",
    ]
    client = FakeAsyncClient(
        stream_responses=[FakeAsyncResponse(200, headers=rl_headers(), lines=lines)]
    )

    async def _run():
        stream = await _open(client)
        return [chunk async for chunk in stream]

    chunks = asyncio.run(_run())
    assert [c["choices"][0]["delta"]["content"] for c in chunks] == ["Hello", " world"]
    assert client.closed == 1  # connection released after iteration


def test_raw_aiter_lines_are_verbatim():
    lines = ["event: ping", 'data: {"x": 1}', "", "data: garbage{", "data: [DONE]"]
    client = FakeAsyncClient(
        stream_responses=[FakeAsyncResponse(200, headers=rl_headers(), lines=lines)]
    )

    async def _run():
        stream = await _open(client)
        return [ln async for ln in stream.aiter_lines()]

    out = asyncio.run(_run())
    assert out == lines  # no filtering, no [DONE] swallowing — the adapter needs this
    assert client.closed == 1


def test_status_code_and_aread_expose_error_body():
    client = FakeAsyncClient(
        stream_responses=[FakeAsyncResponse(500, headers={}, body=b"upstream boom")]
    )

    async def _run():
        stream = await _open(client)
        assert stream.status_code == 500
        body = await stream.aread()
        await stream.aclose()
        return body

    assert asyncio.run(_run()) == b"upstream boom"


def test_dict_iteration_raises_on_error_status():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(
                429,
                headers=rl_headers(**{"ratelimit-reset": 3}),
                json_body={"detail": "nope"},
                # Model a real streamed httpx response: the body is unreadable
                # until aread(). This pins that __aiter__ reads before raising
                # (drop that read and this test gets ResponseNotRead, not 429).
                aread_required=True,
            )
        ]
    )

    async def _run():
        stream = await _open(client, policy=RetryPolicy(on_rate_limit=False))
        return [chunk async for chunk in stream]

    with pytest.raises(RateLimitError) as exc:
        asyncio.run(_run())
    err = exc.value
    assert "HTTP 429" in str(err)
    # The stream error path must read the body (line 126) BEFORE raising, so the
    # typed error carries the parsed rate limits + status + server detail — not
    # a bare message a gateway can't reframe from.
    assert err.status_code == 429
    assert err.rate_limits.reset_seconds == 3
    assert err.response_body and "nope" in err.response_body


def test_retry_before_open_waits_then_streams():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(429, headers=rl_headers(**{"ratelimit-reset": 2})),
            FakeAsyncResponse(200, headers=rl_headers(), lines=["data: [DONE]"]),
        ]
    )
    sleep = RecordingSleep()

    async def _run():
        stream = await _open(client, policy=NO_JITTER, sleep=sleep)
        assert stream.status_code == 200
        await stream.aclose()

    asyncio.run(_run())
    assert len(client.stream_calls) == 2
    assert sleep.waits == [3.0]  # reset 2 + 1s buffer, retried before the body
    # The first (429) stream connection MUST be released before re-issuing —
    # otherwise every rate-limited retry leaks an httpx connection until the
    # pool is exhausted. closed == 2: the retried cm on give-up-success + the
    # explicit aclose() above (the pre-retry release is the load-bearing one).
    assert client.stream_cms[0].exited is True


def test_aclose_is_idempotent():
    client = FakeAsyncClient(
        stream_responses=[FakeAsyncResponse(200, headers=rl_headers(), lines=[])]
    )

    async def _run():
        stream = await _open(client)
        await stream.aclose()
        await stream.aclose()  # second close must be a no-op, not an error

    asyncio.run(_run())
    assert client.closed == 1


def test_keeps_trailing_usage_chunk_with_empty_choices():
    # Same contract as the sync twin: SAIA's final chunk has no choices but
    # carries the token usage, and the stream must hand it over unchanged.
    usage_chunk = {
        "choices": [],
        "usage": {"prompt_tokens": 104, "total_tokens": 124, "completion_tokens": 20},
    }
    lines = [
        'data: {"choices": [{"delta": {"content": "Hi"}}]}',
        f"data: {json.dumps(usage_chunk)}",
        "data: [DONE]",
    ]
    client = FakeAsyncClient(
        stream_responses=[FakeAsyncResponse(200, headers=rl_headers(), lines=lines)]
    )

    async def _run():
        stream = await _open(client)
        return [chunk async for chunk in stream]

    assert asyncio.run(_run())[-1] == usage_chunk
