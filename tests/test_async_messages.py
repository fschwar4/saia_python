"""Tests for :class:`AsyncMessagesService` — the async twin of ``test_messages.py``."""

from __future__ import annotations

import asyncio
import json

import pytest

import saia_python
from saia_python import aiter_text, text_of, usage_of
from saia_python.aio import AsyncMessagesService, AsyncSAIAClient, AsyncSSEStream
from saia_python.exceptions import APIError

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers
from ._generation_fixtures import (
    MESSAGE,
    MESSAGE_400_BODY,
    MESSAGE_STREAM_LINES,
    MESSAGE_TEXT,
)

_MESSAGES = [{"role": "user", "content": "Hi"}]


def _svc(client, **kwargs):
    return AsyncMessagesService(client, "https://x/v1", **kwargs)


def test_create_posts_the_messages_and_attaches_rate_limits():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(200, headers=rl_headers(), json_body=MESSAGE)]
    )
    result = asyncio.run(
        _svc(client).create("m", _MESSAGES, 16, system="Answer briefly.", top_p=0.5)
    )
    call = client.calls[0]
    assert (call["method"], call["url"]) == ("post", "https://x/v1/messages")
    assert call["json"] == {
        "model": "m",
        "messages": _MESSAGES,
        "max_tokens": 16,
        "system": "Answer briefly.",
        "top_p": 0.5,
    }
    assert result["_rate_limits"]["remaining_10s"] == 9
    json.dumps(result)
    assert text_of(result) == MESSAGE_TEXT
    assert usage_of(result)["total_tokens"] == 33


def test_create_streams_events_and_aiter_text_reads_them():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=MESSAGE_STREAM_LINES)
        ]
    )

    async def _run():
        stream = await _svc(client).create("m", _MESSAGES, 16, stream=True)
        assert isinstance(stream, AsyncSSEStream)
        text = aiter_text(stream)
        return "".join([piece async for piece in text]), text.usage

    joined, usage = asyncio.run(_run())
    assert joined == MESSAGE_TEXT
    assert usage == {"input_tokens": 27, "output_tokens": 6, "total_tokens": 33}
    call = client.stream_calls[0]
    assert call["url"] == "https://x/v1/messages"
    assert call["json"]["stream"] is True
    assert client.stream_cms[0].exited


def test_http_400_raises_api_error_with_the_server_message():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(400, json_body=MESSAGE_400_BODY)]
    )
    with pytest.raises(APIError, match="body.max_tokens"):
        asyncio.run(_svc(client).create("m", _MESSAGES, 8))


def test_client_exposes_one_service_and_the_lazy_export():
    client = AsyncSAIAClient(api_key="k", base_url="https://x/v1")
    svc = client.messages
    assert isinstance(svc, AsyncMessagesService)
    assert client.messages is svc
    assert svc._client is client._client
    assert repr(svc) == "AsyncMessagesService(base_url='https://x/v1')"
    assert saia_python.AsyncMessagesService is AsyncMessagesService
    asyncio.run(client.aclose())
