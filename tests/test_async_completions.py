"""Tests for :class:`AsyncCompletionsService` — the async twin of ``test_completions.py``."""

from __future__ import annotations

import asyncio
import json

import pytest

import saia_python
from saia_python import aiter_text, text_of
from saia_python.aio import AsyncCompletionsService, AsyncSAIAClient, AsyncSSEStream
from saia_python.exceptions import APIError, RateLimitError

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers
from ._generation_fixtures import (
    COMPLETION,
    COMPLETION_400_BODY,
    COMPLETION_STREAM_LINES,
    COMPLETION_TEXT,
)
from ._rate_limit_headers import CURRENT_429, CURRENT_429_BODY


def _svc(client, **kwargs):
    return AsyncCompletionsService(client, "https://x/v1", **kwargs)


def test_create_posts_the_prompt_and_attaches_rate_limits():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(200, headers=rl_headers(), json_body=COMPLETION)]
    )
    result = asyncio.run(
        _svc(client).create("m", "Say hi in one word:", max_tokens=4, seed=1)
    )
    call = client.calls[0]
    assert (call["method"], call["url"]) == ("post", "https://x/v1/completions")
    assert call["json"] == {
        "model": "m",
        "prompt": "Say hi in one word:",
        "max_tokens": 4,
        "seed": 1,
    }
    assert result["_rate_limits"]["remaining_10s"] == 9
    json.dumps(result)
    assert text_of(result) == COMPLETION_TEXT


def test_create_streams_and_aiter_text_reads_it():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=COMPLETION_STREAM_LINES)
        ]
    )

    async def _run():
        stream = await _svc(client).create("m", "Say hi", max_tokens=4, stream=True)
        assert isinstance(stream, AsyncSSEStream)
        assert stream.rate_limits["remaining_10s"] == 9
        return "".join([piece async for piece in aiter_text(stream)])

    assert asyncio.run(_run()) == COMPLETION_TEXT
    call = client.stream_calls[0]
    assert call["url"] == "https://x/v1/completions"
    assert call["json"]["stream"] is True
    assert call["headers"]["Accept"] == "text/event-stream"
    assert client.stream_cms[0].exited  # aiter_text released the connection


def test_http_400_raises_api_error_with_the_server_message():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(400, json_body=COMPLETION_400_BODY)]
    )
    with pytest.raises(APIError, match="max_tokens must be at least 1"):
        asyncio.run(_svc(client).create("m", "hi", max_tokens=-1))


def test_retry_false_raises_on_429_without_retrying():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(429, headers=CURRENT_429, json_body=CURRENT_429_BODY)
        ]
    )
    with pytest.raises(RateLimitError):
        asyncio.run(_svc(client, retry=False).create("m", "hi"))
    assert len(client.calls) == 1


def test_client_exposes_one_service_and_the_lazy_export():
    client = AsyncSAIAClient(api_key="k", base_url="https://x/v1")
    svc = client.completions
    assert isinstance(svc, AsyncCompletionsService)
    assert client.completions is svc
    assert svc._client is client._client  # shares the connection pool
    assert repr(svc) == "AsyncCompletionsService(base_url='https://x/v1')"
    assert saia_python.AsyncCompletionsService is AsyncCompletionsService
    asyncio.run(client.aclose())
