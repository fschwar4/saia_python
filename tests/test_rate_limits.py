"""Tests for saia_python.rate_limits — header parsing and formatting."""

import json

from saia_python.rate_limits import RateLimitInfo, parse_rate_limits

from ._rate_limit_headers import CURRENT_429, CURRENT_OK


class TestParseRateLimits:
    def test_full_headers(self):
        """The earlier (Kong) scheme: four windows and one reset."""
        headers = {
            "x-ratelimit-limit-minute": "30",
            "x-ratelimit-limit-hour": "200",
            "x-ratelimit-limit-day": "1000",
            "x-ratelimit-limit-month": "3000",
            "x-ratelimit-remaining-minute": "27",
            "x-ratelimit-remaining-hour": "197",
            "x-ratelimit-remaining-day": "960",
            "x-ratelimit-remaining-month": "2960",
            "ratelimit-reset": "11",
        }
        info = parse_rate_limits(headers)
        assert info.limit_minute == 30
        assert info.remaining_minute == 27
        assert info.limit_month == 3000
        assert info.remaining_month == 2960
        assert info.reset_seconds == 11

    def test_current_scheme(self):
        """The scheme SAIA sends since 2026-11: a reset per window."""
        info = parse_rate_limits(CURRENT_OK)
        assert (info.limit_10s, info.remaining_10s, info.reset_10s) == (10, 9, 18)
        assert (info.limit_hour, info.remaining_hour, info.reset_hour) == (
            400,
            398,
            6328,
        )
        assert (info.limit_day, info.remaining_day, info.reset_day) == (
            800,
            750,
            27928,
        )
        # Nothing from the earlier scheme is invented.
        assert info.limit_minute is None
        assert info.reset_seconds is None
        assert info.retry_after is None

    def test_current_429_has_retry_after_and_names_the_exhausted_window(self):
        info = parse_rate_limits(CURRENT_429)
        assert info.retry_after == 9
        assert info.exhausted_windows() == ["10s"]

    def test_current_scheme_wins_over_earlier_for_a_shared_window(self):
        info = parse_rate_limits(
            {
                "x-ratelimit-remaining-hour": "5",
                "x-ratelimit-remaining-requests-hour": "7",
            }
        )
        assert info.remaining_hour == 7

    def test_non_integer_values_ignored(self):
        headers = {
            "x-ratelimit-limit-minute": "not-a-number",
            "x-ratelimit-remaining-minute": "5",
        }
        info = parse_rate_limits(headers)
        assert info.limit_minute is None
        assert info.remaining_minute == 5

    def test_to_dict_is_json_serializable_with_the_new_keys(self):
        data = parse_rate_limits(CURRENT_429).to_dict()
        assert data["remaining_10s"] == 0
        assert data["retry_after"] == 9
        json.dumps(data)


class TestRetryAfter:
    def test_seconds(self):
        assert parse_rate_limits({"retry-after": "9"}).retry_after == 9

    def test_fractional_seconds_round_up(self):
        assert parse_rate_limits({"retry-after": "8.2"}).retry_after == 9

    def test_http_date_is_measured_from_the_date_header(self):
        info = parse_rate_limits(
            {
                "date": "Thu, 19 Nov 2026 15:15:31 GMT",
                "retry-after": "Thu, 19 Nov 2026 15:15:40 GMT",
            }
        )
        assert info.retry_after == 9

    def test_a_date_in_the_past_means_no_wait(self):
        info = parse_rate_limits(
            {
                "date": "Thu, 19 Nov 2026 15:15:31 GMT",
                "retry-after": "Thu, 19 Nov 2026 15:15:00 GMT",
            }
        )
        assert info.retry_after == 0

    def test_garbage_is_ignored(self):
        assert parse_rate_limits({"retry-after": "soon"}).retry_after is None
        assert parse_rate_limits({"retry-after": "inf"}).retry_after is None


class TestRateLimitInfoStr:
    def test_str_renders_without_crashing(self):
        """``__str__`` is a human-readable summary: verify it renders the
        header and values and tolerates ``None`` fields. The exact column
        alignment is cosmetic and intentionally not asserted (too brittle)."""
        info = RateLimitInfo(
            limit_minute=30,
            remaining_minute=27,
            limit_hour=200,
            remaining_hour=197,
            limit_day=1000,
            remaining_day=960,
            limit_month=3000,
            remaining_month=2960,
            reset_seconds=11,
        )
        output = str(info)
        assert output.startswith("SAIA Rate Limits:")
        assert "30" in output and "Resets in 11s" in output

        # A ``None`` field must not raise when formatting.
        assert isinstance(
            str(RateLimitInfo(limit_minute=30, remaining_minute=None)), str
        )

    def test_str_shows_each_window_reset_and_retry_after(self):
        output = str(parse_rate_limits(CURRENT_429))
        assert "10s" in output and "resets in 19s" in output
        assert "resets in 1h 44m" in output  # the hour window, 6269 s
        assert "Retry after 9s" in output

    def test_str_without_data(self):
        assert str(RateLimitInfo()) == "SAIA Rate Limits: (no data)"
