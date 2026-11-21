"""Tests for :class:`AsyncResponsesService` — the async twin of ``test_responses_api.py``."""

from __future__ import annotations

import asyncio
import json

import pytest

import saia_python
from saia_python import aiter_text, text_of, usage_of
from saia_python.aio import AsyncResponsesService, AsyncSAIAClient, AsyncSSEStream
from saia_python.exceptions import APIError

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers
from ._generation_fixtures import (
    RESPONSE,
    RESPONSE_400_BODY,
    RESPONSE_STREAM_LINES,
    RESPONSE_TEXT,
)


def _svc(client, **kwargs):
    return AsyncResponsesService(client, "https://x/v1", **kwargs)


def test_create_posts_the_input_and_attaches_rate_limits():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(200, headers=rl_headers(), json_body=RESPONSE)]
    )
    result = asyncio.run(
        _svc(client).create("m", "Hi", instructions="Answer briefly.", top_p=0.5)
    )
    call = client.calls[0]
    assert (call["method"], call["url"]) == ("post", "https://x/v1/responses")
    assert call["json"] == {
        "model": "m",
        "input": "Hi",
        "instructions": "Answer briefly.",
        "top_p": 0.5,
    }
    assert result["_rate_limits"]["remaining_10s"] == 9
    json.dumps(result)
    assert text_of(result) == RESPONSE_TEXT


def test_create_streams_events_and_aiter_text_reads_them():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=RESPONSE_STREAM_LINES)
        ]
    )

    async def _run():
        stream = await _svc(client).create("m", "Hi", stream=True)
        assert isinstance(stream, AsyncSSEStream)
        text = aiter_text(stream)
        return "".join([piece async for piece in text]), text.last

    joined, last = asyncio.run(_run())
    assert joined == RESPONSE_TEXT
    assert usage_of(last)["output_tokens"] == 6
    call = client.stream_calls[0]
    assert call["url"] == "https://x/v1/responses"
    assert call["json"]["stream"] is True
    assert client.stream_cms[0].exited


def test_the_raw_stream_ends_with_the_completed_event():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=RESPONSE_STREAM_LINES)
        ]
    )

    async def _run():
        stream = await _svc(client).create("m", "Hi", stream=True)
        return [event async for event in stream]

    events = asyncio.run(_run())
    assert events[-1]["type"] == "response.completed"
    assert usage_of(events[-1])["output_tokens"] == 6


def test_http_400_raises_api_error_with_the_server_message():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(400, json_body=RESPONSE_400_BODY)]
    )
    with pytest.raises(APIError, match="max_tokens must be at least 1"):
        asyncio.run(_svc(client).create("m", "hi", max_output_tokens=-1))


def test_client_exposes_one_service_and_the_lazy_export():
    client = AsyncSAIAClient(api_key="k", base_url="https://x/v1")
    svc = client.responses
    assert isinstance(svc, AsyncResponsesService)
    assert client.responses is svc
    assert svc._client is client._client
    assert repr(svc) == "AsyncResponsesService(base_url='https://x/v1')"
    assert saia_python.AsyncResponsesService is AsyncResponsesService
    asyncio.run(client.aclose())
