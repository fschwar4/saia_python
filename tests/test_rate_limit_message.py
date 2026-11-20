"""Tests for :func:`format_rate_limit_error` — the informative 429 message.

Shared by the sync and async transports (via ``raise_for_status``), so the
message is the same regardless of path.
"""

from __future__ import annotations

from saia_python import RateLimitInfo, format_rate_limit_error, parse_rate_limits

from ._rate_limit_headers import CURRENT_429, CURRENT_429_MESSAGE


def test_message_reports_window_reset_and_retry_hint():
    msg = format_rate_limit_error(
        RateLimitInfo(limit_minute=30, remaining_minute=0, reset_seconds=8)
    )
    assert "HTTP 429" in msg
    assert "minute 0/30" in msg
    assert "resets in ~8s" in msg
    assert "retry=True" in msg  # tells the caller how to auto-wait


def test_message_without_headers_still_has_hint():
    msg = format_rate_limit_error(RateLimitInfo())
    assert "HTTP 429" in msg
    assert "retry=True" in msg


def test_server_detail_appended_when_present_and_skipped_when_blank():
    with_detail = format_rate_limit_error(RateLimitInfo(), "too many requests")
    assert with_detail.endswith("Server detail: too many requests")
    assert "Server detail" not in format_rate_limit_error(RateLimitInfo(), "   ")


def test_message_for_the_current_scheme_uses_retry_after():
    msg = format_rate_limit_error(
        parse_rate_limits(CURRENT_429), detail=CURRENT_429_MESSAGE
    )
    assert "10s 0/10, hour 387/400, day 739/800" in msg
    assert "retry in ~9s" in msg
    assert msg.endswith(f"Server detail: {CURRENT_429_MESSAGE}")


def test_message_names_the_exhausted_window_reset_without_retry_after():
    headers = {k: v for k, v in CURRENT_429.items() if k != "retry-after"}
    msg = format_rate_limit_error(parse_rate_limits(headers))
    assert "The 10s window resets in ~19s." in msg
    # The hour window still has requests left, so its reset is not mentioned.
    assert "hour window" not in msg
