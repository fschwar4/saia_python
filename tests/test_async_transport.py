"""Tests for the async transport (``aexecute`` / ``apost_chat_completion``).

The async twin of ``test_transport_policy.py`` + the transport half of
``test_chat.py``: the retry loop, the 429/give-up contract, and the informative
error. Coroutines run via ``asyncio.run`` (no ``pytest-asyncio``); the network
is a ``FakeAsyncClient`` with a queued response list and an injected ``sleep``.
"""

from __future__ import annotations

import asyncio

import pytest

from saia_python._async_http import aexecute, apost_chat_completion
from saia_python._http import RetryPolicy
from saia_python.aio import AsyncSSEStream
from saia_python.exceptions import APIError, RateLimitError

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, RecordingSleep, rl_headers

# Deterministic waits in the retry tests — no random jitter.
NO_JITTER = RetryPolicy(jitter=(0.0, 0.0))


def test_aexecute_success_returns_response():
    client = FakeAsyncClient(responses=[FakeAsyncResponse(200)])
    sleep = RecordingSleep()
    resp = asyncio.run(
        aexecute(client, "post", "u", policy=NO_JITTER, idempotent=True, sleep=sleep)
    )
    assert resp.status_code == 200
    assert len(client.calls) == 1
    assert sleep.waits == []


def test_aexecute_429_then_200_retries_and_waits_reset():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(429, headers=rl_headers(**{"ratelimit-reset": 5})),
            FakeAsyncResponse(200),
        ]
    )
    sleep = RecordingSleep()
    resp = asyncio.run(
        aexecute(client, "post", "u", policy=NO_JITTER, idempotent=True, sleep=sleep)
    )
    assert resp.status_code == 200
    assert len(client.calls) == 2
    assert sleep.waits == [6.0]  # reset 5 + 1s buffer


def test_aexecute_disabled_policy_no_retry():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(429, headers=rl_headers(**{"ratelimit-reset": 5}))]
    )
    sleep = RecordingSleep()
    resp = asyncio.run(
        aexecute(
            client,
            "post",
            "u",
            policy=RetryPolicy(on_rate_limit=False),
            idempotent=True,
            sleep=sleep,
        )
    )
    assert resp.status_code == 429
    assert len(client.calls) == 1
    assert sleep.waits == []


def test_aexecute_mutation_not_retried_by_default():
    client = FakeAsyncClient(
        responses=[FakeAsyncResponse(429, headers=rl_headers(**{"ratelimit-reset": 5}))]
    )
    resp = asyncio.run(
        aexecute(client, "post", "u", policy=NO_JITTER, idempotent=False)
    )
    assert resp.status_code == 429
    assert len(client.calls) == 1


def test_aexecute_mutation_retried_when_opted_in():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(429, headers=rl_headers(**{"ratelimit-reset": 2})),
            FakeAsyncResponse(200),
        ]
    )
    sleep = RecordingSleep()
    policy = RetryPolicy(jitter=(0.0, 0.0), retry_mutations=True)
    resp = asyncio.run(
        aexecute(client, "post", "u", policy=policy, idempotent=False, sleep=sleep)
    )
    assert resp.status_code == 200
    assert len(client.calls) == 2
    assert sleep.waits == [3.0]


def test_apost_non_stream_attaches_rate_limits_dict():
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
        apost_chat_completion(client, "u", {"model": "m", "messages": []})
    )
    assert isinstance(result, dict)
    assert isinstance(result["_rate_limits"], dict)
    assert result["_rate_limits"]["remaining_minute"] == 29


def test_apost_non_stream_429_disabled_raises_informative_rate_limit():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(
                429,
                headers=rl_headers(
                    **{"x-ratelimit-remaining-minute": 0, "ratelimit-reset": 9}
                ),
                json_body={"detail": "slow down"},
            )
        ]
    )
    with pytest.raises(RateLimitError) as exc:
        asyncio.run(
            apost_chat_completion(
                client, "u", {"model": "m", "messages": []}, policy=RetryPolicy(False)
            )
        )
    msg = str(exc.value)
    assert "HTTP 429" in msg
    assert "retry=True" in msg  # the informative auto-retry hint
    assert "slow down" in msg  # the server detail is preserved
    assert exc.value.status_code == 429
    assert exc.value.rate_limits.remaining_minute == 0


def test_apost_non_stream_500_raises_apierror_with_body():
    client = FakeAsyncClient(responses=[FakeAsyncResponse(500, text="upstream boom")])
    with pytest.raises(APIError) as exc:
        asyncio.run(apost_chat_completion(client, "u", {"model": "m", "messages": []}))
    assert exc.value.status_code == 500
    assert exc.value.response_body == "upstream boom"


def test_apost_stream_returns_async_sse_stream():
    lines = [
        'data: {"choices": [{"delta": {"content": "Hi"}}]}',
        "data: [DONE]",
    ]
    client = FakeAsyncClient(
        stream_responses=[FakeAsyncResponse(200, headers=rl_headers(), lines=lines)]
    )

    async def _run():
        stream = await apost_chat_completion(
            client, "u", {"model": "m", "messages": []}, stream=True
        )
        assert isinstance(stream, AsyncSSEStream)
        return [chunk async for chunk in stream]

    chunks = asyncio.run(_run())
    assert len(chunks) == 1
    assert chunks[0]["choices"][0]["delta"]["content"] == "Hi"
    # The stream request carried stream=True + the SSE Accept header.
    assert client.stream_calls[0]["json"]["stream"] is True
    assert client.stream_calls[0]["headers"]["Accept"] == "text/event-stream"
