"""Tests for SAIAClient.get_rate_limits — auth-failure handling.

The probe GET is *expected* to 400 (no request body) but still carries the
rate-limit headers; a 401/403 means the key is bad and must raise rather than
silently returning empty limits.
"""

from unittest.mock import MagicMock

import pytest

from saia_python import SAIAClient
from saia_python.exceptions import AuthenticationError


def _make_client() -> SAIAClient:
    client = SAIAClient.__new__(SAIAClient)
    client._base_url = "https://example.com/v1"
    client._session = MagicMock()
    return client


def _resp(status_code, *, headers=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers or {}
    resp.text = text
    resp.json.side_effect = ValueError("no json body")
    return resp


def test_get_rate_limits_parses_headers_on_expected_400():
    """A 400 (the expected probe response) still yields parsed rate limits."""
    client = _make_client()
    client._session.get.return_value = _resp(
        400,
        headers={
            "x-ratelimit-limit-minute": "30",
            "x-ratelimit-remaining-minute": "27",
        },
    )
    info = client.get_rate_limits()
    assert info.limit_minute == 30
    assert info.remaining_minute == 27


def test_get_rate_limits_raises_on_401():
    client = _make_client()
    client._session.get.return_value = _resp(401, text="Unauthorized")
    with pytest.raises(AuthenticationError):
        client.get_rate_limits()


def test_get_rate_limits_raises_on_403():
    client = _make_client()
    client._session.get.return_value = _resp(403, text="Forbidden")
    with pytest.raises(AuthenticationError):
        client.get_rate_limits()
