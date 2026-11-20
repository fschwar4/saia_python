"""Live check that SAIA's rate-limit headers still parse.

In November 2026 SAIA renamed its rate-limit headers, and nothing failed: the
parser found none of the names it knew, so the limits came back empty and the
429 retry waited blind. This test makes such a change visible. It needs an API
key and the network, sends three requests against your limits (``GET /models``,
the probe, one tiny chat call), and never runs in CI or the offline gate by
default::

    SAIA_RATE_LIMITS_LIVE=1 pytest tests/test_live_rate_limits.py

``SAIA_RATE_LIMITS_LIVE_MODEL`` overrides the chat model.
"""

from __future__ import annotations

import os

import pytest

from saia_python import RateLimitInfo, SAIAClient
from saia_python.rate_limits import WINDOWS

MODEL = os.environ.get("SAIA_RATE_LIMITS_LIVE_MODEL", "meta-llama-3.1-8b-instruct")

pytestmark = pytest.mark.skipif(
    not os.environ.get("SAIA_RATE_LIMITS_LIVE"),
    reason="set SAIA_RATE_LIMITS_LIVE=1 to run the network-backed rate-limit check",
)


def _reported(info: RateLimitInfo) -> list[str]:
    """The windows the headers gave a limit for."""
    return [w for w in WINDOWS if getattr(info, f"limit_{w}") is not None]


def test_get_rate_limits_reports_windows():
    info = SAIAClient().get_rate_limits()
    windows = _reported(info)
    assert windows, f"no rate-limit window parsed: {info.to_dict()}"
    for window in windows:
        assert getattr(info, f"remaining_{window}") is not None, window


def test_chat_response_carries_rate_limits():
    result = SAIAClient().chat.completions(
        MODEL, [{"role": "user", "content": "Hi"}], max_tokens=1
    )
    assert isinstance(result, dict)
    info = RateLimitInfo(**result["_rate_limits"])
    assert _reported(info), f"no rate-limit window parsed: {info.to_dict()}"
