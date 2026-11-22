"""Tests for :class:`AsyncChatService` — the async twin of ``test_chat.py``."""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, patch

import saia_python
from saia_python.aio import (
    AsyncChatCompletions,
    AsyncChatService,
    AsyncSAIAClient,
    AsyncSSEStream,
)

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
    assert result["_rate_limits"]["remaining_10s"] == 9
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


# --- completions.create(...) and the AsyncChatCompletions object --------------


def test_create_and_the_call_form_send_the_same_request():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(200, headers=rl_headers(), json_body={}),
            FakeAsyncResponse(200, headers=rl_headers(), json_body={}),
        ]
    )
    svc = _svc(client)

    async def _run():
        result = await svc.completions.create("m", [], temperature=0.2, seed=7)
        await svc.completions("m", [], temperature=0.2, seed=7)
        return result

    assert asyncio.run(_run())["_rate_limits"]["remaining_10s"] == 9
    first, second = client.calls
    assert first == second
    assert first["url"] == "https://x/v1/chat/completions"
    assert first["json"] == {
        "model": "m",
        "messages": [],
        "seed": 7,
        "temperature": 0.2,
    }


def test_create_streams():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=["data: [DONE]"])
        ]
    )

    async def _run():
        return await _svc(client).completions.create("m", [], stream=True)

    assert isinstance(asyncio.run(_run()), AsyncSSEStream)
    assert client.stream_calls[0]["json"]["stream"] is True


def test_completions_is_one_object_per_service():
    svc = _svc(FakeAsyncClient())
    completions = svc.completions
    assert isinstance(completions, AsyncChatCompletions)
    assert svc.completions is completions  # built on first access, then kept
    assert inspect.iscoroutinefunction(completions.create)
    assert repr(completions) == "AsyncChatCompletions(base_url='https://x/v1')"


def test_client_chat_completions_and_the_lazy_export():
    client = AsyncSAIAClient(api_key="k", base_url="https://x/v1")
    completions = client.chat.completions
    assert isinstance(completions, AsyncChatCompletions)
    assert completions._service is client.chat
    assert saia_python.AsyncChatCompletions is AsyncChatCompletions
    asyncio.run(client.aclose())


def test_patching_create_catches_both_forms():
    svc = _svc(FakeAsyncClient())
    create = AsyncMock(return_value={"ok": True})

    async def _run():
        return (
            await svc.completions.create("m", []),
            await svc.completions("m", []),
        )

    with patch.object(svc.completions, "create", create):
        assert asyncio.run(_run()) == ({"ok": True}, {"ok": True})
    assert create.await_count == 2
