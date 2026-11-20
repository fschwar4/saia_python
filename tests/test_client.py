"""Tests for SAIAClient.get_rate_limits — the probe and its auth handling.

SAIA sends rate-limit headers only for requests that name a served model, so
the probe is a ``POST /chat/completions`` whose body holds just ``model``. It
is *expected* to 400 (no messages) but still carries the headers; a 401/403
means the key is bad and must raise rather than silently return empty limits.
"""

import logging
from unittest.mock import MagicMock

import pytest

from saia_python import RateLimitInfo, SAIAClient
from saia_python.exceptions import AuthenticationError

from ._rate_limit_headers import CURRENT_OK, LEGACY_OK

_URL = "https://example.com/v1/chat/completions"


def _make_client() -> SAIAClient:
    client = SAIAClient.__new__(SAIAClient)
    client._base_url = "https://example.com/v1"
    client._session = MagicMock()
    client._timeout = (10.0, 60.0)
    client._models = None
    client._probe_model = None
    return client


def _resp(status_code, *, headers=None, text="", json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers or {}
    resp.text = text
    if json_body is None:
        resp.json.side_effect = ValueError("no json body")
    else:
        resp.json.return_value = json_body
    return resp


def _models_resp(*ids):
    return _resp(200, json_body={"object": "list", "data": [{"id": i} for i in ids]})


def test_get_rate_limits_parses_headers_on_expected_400():
    """A 400 (the expected probe response) still yields parsed rate limits."""
    client = _make_client()
    client._session.post.return_value = _resp(400, headers=CURRENT_OK)
    info = client.get_rate_limits(model="m")
    assert (info.limit_10s, info.remaining_10s) == (10, 9)
    assert info.remaining_day == 750


def test_get_rate_limits_still_reads_the_earlier_scheme():
    client = _make_client()
    client._session.post.return_value = _resp(400, headers=LEGACY_OK)
    info = client.get_rate_limits(model="m")
    assert (info.limit_minute, info.remaining_minute) == (30, 29)


def test_probe_posts_only_the_model_with_a_timeout():
    """The probe body names a model and nothing else, so nothing is generated,
    and it carries a timeout so a stalled server can't hang it."""
    client = _make_client()
    client._session.post.return_value = _resp(400, headers=CURRENT_OK)
    client.get_rate_limits(model="m")
    client._session.post.assert_called_once_with(
        _URL, json={"model": "m"}, timeout=(10.0, 60.0)
    )
    client._session.get.assert_not_called()  # an explicit model needs no lookup


def test_probe_model_is_looked_up_once_and_cached():
    client = _make_client()
    client._session.get.return_value = _models_resp("first", "second")
    client._session.post.return_value = _resp(400, headers=CURRENT_OK)
    client.get_rate_limits()
    client.get_rate_limits()
    assert client._session.get.call_count == 1  # one GET /models
    assert client._session.post.call_count == 2
    assert client._session.post.call_args.kwargs["json"] == {"model": "first"}


def test_missing_headers_warn_and_pick_the_model_again(caplog):
    """A probe without headers (e.g. a retired model: 404) logs a warning and
    drops the cached model, so the next call looks it up again."""
    client = _make_client()
    client._session.get.return_value = _models_resp("gone")
    client._session.post.return_value = _resp(404, text="Unknown model/service")
    with caplog.at_level(logging.WARNING, logger="saia_python.client"):
        info = client.get_rate_limits()
    assert info == RateLimitInfo()
    assert "carried no rate-limit headers" in caplog.text
    assert client._probe_model is None


def test_no_model_to_probe_with_returns_empty_limits(caplog):
    client = _make_client()
    client._session.get.return_value = _models_resp()
    with caplog.at_level(logging.WARNING, logger="saia_python.client"):
        info = client.get_rate_limits()
    assert info.limit_10s is None
    assert "listed no model" in caplog.text
    client._session.post.assert_not_called()


def test_get_rate_limits_raises_on_401():
    client = _make_client()
    client._session.post.return_value = _resp(401, text="Unauthorized")
    with pytest.raises(AuthenticationError):
        client.get_rate_limits(model="m")


def test_get_rate_limits_raises_on_403():
    client = _make_client()
    client._session.post.return_value = _resp(403, text="Forbidden")
    with pytest.raises(AuthenticationError):
        client.get_rate_limits(model="m")
