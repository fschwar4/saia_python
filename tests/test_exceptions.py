"""Tests for saia_python.exceptions — raise_for_status 429 handling."""

from unittest.mock import MagicMock

import pytest

from saia_python.exceptions import RateLimitError, raise_for_status


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
