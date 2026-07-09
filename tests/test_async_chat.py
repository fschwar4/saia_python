"""Tests for :class:`AsyncChatService` — the async twin of ``test_chat.py``."""

from __future__ import annotations

import asyncio
import json

from saia_python.aio import AsyncChatService, AsyncSSEStream

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers


def _svc(client):
    return AsyncChatService(client, "https://x/v1")


def test_completions_non_streaming_attaches_rate_limits_dict():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(
                200,
                headers=rl_headers(),
                json_body={"choices": [{"message": {"content": "hi"}}]},
            )
        ]
    )
    result = asyncio.run(
        _svc(client).completions(
            "m", [{"role": "user", "content": "hi"}], temperature=0.5
        )
    )
    assert isinstance(result["_rate_limits"], dict)
    assert result["_rate_limits"]["remaining_minute"] == 29
    json.dumps(result)  # round-trips — the point of the dict form
    assert client.calls[0]["json"]["temperature"] == 0.5


def test_completions_omits_unset_sampling_knobs():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(200, headers=rl_headers(), json_body={})]
    )
    asyncio.run(_svc(client).completions("m", []))
    body = client.calls[0]["json"]
    assert "temperature" not in body
    assert "top_p" not in body
    assert "max_tokens" not in body


def test_completions_stream_returns_async_sse_stream():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=["data: [DONE]"])
        ]
    )

    async def _run():
        return await _svc(client).completions("m", [], stream=True)

    assert isinstance(asyncio.run(_run()), AsyncSSEStream)
