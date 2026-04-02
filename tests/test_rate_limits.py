"""Tests for saia_python.rate_limits — header parsing and formatting."""

from saia_python.rate_limits import RateLimitInfo, parse_rate_limits


class TestParseRateLimits:

    def test_full_headers(self):
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

    def test_non_integer_values_ignored(self):
        headers = {
            "x-ratelimit-limit-minute": "not-a-number",
            "x-ratelimit-remaining-minute": "5",
        }
        info = parse_rate_limits(headers)
        assert info.limit_minute is None
        assert info.remaining_minute == 5


class TestRateLimitInfoStr:

    def test_full_output_alignment(self):
        info = RateLimitInfo(
            limit_minute=30, remaining_minute=27,
            limit_hour=200, remaining_hour=197,
            limit_day=1000, remaining_day=960,
            limit_month=3000, remaining_month=2960,
            reset_seconds=11,
        )
        output = str(info)
        lines = output.splitlines()
        assert lines[0] == "SAIA Rate Limits:"
        assert "Resets in 11s" in lines[-1]

        # All "/" should be in the same column
        slash_positions = [line.index("/") for line in lines[1:5]]
        assert len(set(slash_positions)) == 1

        # All "(" should be in the same column
        paren_positions = [line.index("(") for line in lines[1:5]]
        assert len(set(paren_positions)) == 1

    def test_remaining_none_shows_question_mark(self):
        info = RateLimitInfo(limit_minute=30, remaining_minute=None)
        output = str(info)
        assert "? used" in output
