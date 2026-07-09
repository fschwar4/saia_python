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
    info = asyncio.run(_client(fake).get_rate_limits())
    assert info.remaining_minute == 29


def test_get_rate_limits_raises_on_401():
    fake = FakeAsyncClient(responses=[FakeAsyncResponse(401, text="bad key")])
    with pytest.raises(AuthenticationError):
        asyncio.run(_client(fake).get_rate_limits())


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
