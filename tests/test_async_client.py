"""Tests for :class:`AsyncSAIAClient` — the async twin of ``test_client.py``.

The client is constructed with an explicit key (no credential discovery), then
its real ``httpx.AsyncClient`` is swapped for a :class:`FakeAsyncClient` so the
service wiring, ``get_rate_limits``, ``health_check``, and the async
context-manager close are exercised without a network.
"""

from __future__ import annotations

import asyncio

import pytest

from saia_python.aio import AsyncSAIAClient
from saia_python.exceptions import AuthenticationError

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers


def _client(fake):
    client = AsyncSAIAClient(api_key="k", base_url="https://x/v1")
    client._client = fake
    return client


def test_async_context_manager_closes_pool():
    fake = FakeAsyncClient()

    async def _run():
        client = AsyncSAIAClient(api_key="k", base_url="https://x/v1")
        client._client = fake
        async with client:
            pass

    asyncio.run(_run())
    assert fake.closed == 1


def test_get_rate_limits_tolerates_probe_400():
    fake = FakeAsyncClient(responses=[FakeAsyncResponse(400, headers=rl_headers())])
    info = asyncio.run(_client(fake).get_rate_limits(model="m"))
    assert info.remaining_10s == 9
    probe = fake.calls[0]
    assert (probe["method"], probe["url"]) == ("post", "https://x/v1/chat/completions")
    assert probe["json"] == {"model": "m"}  # only a model: nothing is generated
    assert probe["timeout"] == 60.0


def test_get_rate_limits_looks_up_the_probe_model_once():
    models = FakeAsyncResponse(200, json_body={"data": [{"id": "m1"}, {"id": "m2"}]})
    fake = FakeAsyncClient(
        responses=[
            models,
            FakeAsyncResponse(400, headers=rl_headers()),
            FakeAsyncResponse(400, headers=rl_headers()),
        ]
    )
    client = _client(fake)

    async def _run():
        await client.get_rate_limits()
        await client.get_rate_limits()

    asyncio.run(_run())
    assert [c["method"] for c in fake.calls] == ["get", "post", "post"]
    assert fake.calls[2]["json"] == {"model": "m1"}


def test_get_rate_limits_without_headers_picks_the_model_again():
    models = FakeAsyncResponse(200, json_body={"data": [{"id": "gone"}]})
    fake = FakeAsyncClient(responses=[models, FakeAsyncResponse(404, text="x")])
    client = _client(fake)
    info = asyncio.run(client.get_rate_limits())
    assert info.limit_10s is None
    assert client._probe_model is None


def test_get_rate_limits_raises_on_401():
    fake = FakeAsyncClient(responses=[FakeAsyncResponse(401, text="bad key")])
    with pytest.raises(AuthenticationError):
        asyncio.run(_client(fake).get_rate_limits(model="m"))


def test_health_check_verbose_reports_both_legs():
    fake = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(
                200, headers={}, json_body={"data": [{"id": "m1"}, {"id": "m2"}]}
            ),
            FakeAsyncResponse(204, headers={}),
        ]
    )
    result = asyncio.run(_client(fake).health_check(verbose=True))
    assert result["ok"] is True
    assert result["model_count"] == 2
    assert result["arcana_ok"] is True
