"""Tests for saia_python.exceptions — raise_for_status 429 handling."""

import json
from unittest.mock import MagicMock

import pytest

from saia_python.exceptions import (
    APIError,
    AuthenticationError,
    RateLimitError,
    raise_for_status,
)

from ._rate_limit_headers import CURRENT_429, CURRENT_429_BODY, CURRENT_429_MESSAGE


def _json_resp(status_code, body, *, headers=None):
    """A mocked response whose ``json()`` returns ``body``."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers or {}
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


class TestRaiseForStatus:
    def test_429_includes_parsed_rate_limits(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.ok = False
        resp.text = "Too Many Requests"
        resp.headers = {
            "x-ratelimit-limit-minute": "10",
            "x-ratelimit-remaining-minute": "0",
        }
        with pytest.raises(RateLimitError) as exc_info:
            raise_for_status(resp)
        assert exc_info.value.rate_limits is not None
        assert exc_info.value.rate_limits.limit_minute == 10
        assert exc_info.value.rate_limits.remaining_minute == 0

    def test_current_429_carries_retry_after_and_the_gateway_message(self):
        resp = _json_resp(429, CURRENT_429_BODY, headers=CURRENT_429)
        with pytest.raises(RateLimitError) as exc_info:
            raise_for_status(resp)
        err = exc_info.value
        assert err.rate_limits.retry_after == 9
        assert err.rate_limits.remaining_10s == 0
        assert str(err).endswith(f"Server detail: {CURRENT_429_MESSAGE}")
        assert err.response_body == json.dumps(CURRENT_429_BODY)


class TestExtractDetail:
    """The error bodies SAIA sends; the message, not raw JSON, goes to the error."""

    def test_detail_body(self):
        with pytest.raises(APIError) as exc_info:
            raise_for_status(_json_resp(404, {"detail": "Not Found"}))
        assert str(exc_info.value) == "Not Found"

    def test_openai_style_error_body(self):
        body = {"error": {"message": "Unknown model/service", "type": "not_found"}}
        with pytest.raises(APIError) as exc_info:
            raise_for_status(_json_resp(404, body))
        assert str(exc_info.value) == "Unknown model/service"
        assert exc_info.value.response_body == json.dumps(body)

    def test_gateway_auth_body(self):
        body = {"message": "Unauthorized", "request_id": "abc123"}
        with pytest.raises(AuthenticationError) as exc_info:
            raise_for_status(_json_resp(401, body))
        assert str(exc_info.value) == "Unauthorized"

    def test_unknown_json_shape_falls_back_to_the_raw_text(self):
        with pytest.raises(APIError) as exc_info:
            raise_for_status(_json_resp(500, {"oops": True}))
        assert str(exc_info.value) == '{"oops": true}'

    def test_non_json_body_falls_back_to_the_raw_text(self):
        resp = _json_resp(502, None)
        resp.text = "Bad Gateway"
        resp.json.side_effect = ValueError("not json")
        with pytest.raises(APIError) as exc_info:
            raise_for_status(resp)
        assert str(exc_info.value) == "Bad Gateway"
