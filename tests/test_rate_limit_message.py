"""Tests for :func:`format_rate_limit_error` — the informative 429 message.

Shared by the sync and async transports (via ``raise_for_status``), so the
message is the same regardless of path.
"""

from __future__ import annotations

from saia_python import RateLimitInfo, format_rate_limit_error


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
