"""Tests for :class:`AsyncArcanaService` — the async twin of ``test_arcana.py``
(the chat + read-only control-plane subset).

The headline invariant is the same three-part ARCANA injection the sync
``ArcanaService.chat`` and the AVOR adapter enforce (Rule #6): ``enable-tools``
+ ``arcana.id`` in the body **and** the ``inference-service`` header.
"""

from __future__ import annotations

import asyncio

from saia_python.aio import AsyncArcanaService, AsyncSSEStream

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers


def _svc(client, *, api_key="KEY"):
    return AsyncArcanaService(client, "https://x/v1", api_key)


def _chat_ok():
    return FakeAsyncResponse(
        200,
        headers=rl_headers(),
        json_body={"choices": [{"message": {"content": "hi"}}]},
    )


def test_chat_injects_three_arcana_components():
    client = FakeAsyncClient(responses=[_chat_ok()])
    asyncio.run(_svc(client).chat("m", [{"role": "user", "content": "hi"}], "owner/kb"))
    call = client.calls[0]
    assert call["json"]["arcana"] == {"id": "owner/kb"}
    assert call["json"]["enable-tools"] is True
    assert call["headers"]["inference-service"] == "saia-openai-gateway"
    assert call["headers"]["Authorization"] == "Bearer KEY"
    assert call["url"].endswith("/chat/completions")


def test_chat_api_key_override_is_per_call():
    client = FakeAsyncClient(responses=[_chat_ok()])
    asyncio.run(
        _svc(client, api_key="INSTANCE").chat("m", [], "owner/kb", api_key="PER_CALL")
    )
    # A shared pooled client can authenticate each request as a different user.
    assert client.calls[0]["headers"]["Authorization"] == "Bearer PER_CALL"


def test_chat_extra_headers_merge_without_dropping_invariant():
    client = FakeAsyncClient(responses=[_chat_ok()])
    asyncio.run(
        _svc(client).chat("m", [], "owner/kb", extra_headers={"X-Request-ID": "rid"})
    )
    headers = client.calls[0]["headers"]
    assert headers["X-Request-ID"] == "rid"
    assert headers["inference-service"] == "saia-openai-gateway"


def test_chat_stream_returns_async_sse_stream():
    client = FakeAsyncClient(
        stream_responses=[
            FakeAsyncResponse(200, headers=rl_headers(), lines=["data: [DONE]"])
        ]
    )

    async def _run():
        return await _svc(client).chat("m", [], "owner/kb", stream=True)

    assert isinstance(asyncio.run(_run()), AsyncSSEStream)


def test_heartbeat_true_on_204_uses_raw_key():
    client = FakeAsyncClient(responses=[FakeAsyncResponse(204, headers={})])
    assert asyncio.run(_svc(client).heartbeat()) is True
    # Control plane uses the RAW key (no Bearer prefix), unlike chat().
    assert client.calls[0]["headers"]["Authorization"] == "KEY"


def test_list_returns_json_body():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(200, headers={}, json_body=[{"name": "a"}])]
    )
    assert asyncio.run(_svc(client).list()) == [{"name": "a"}]
