"""Tests for ChatService.completions — streaming vs non-streaming return types.

Guards the 0.2.0 streaming-parity behaviour: non-streaming attaches a
JSON-serializable ``_rate_limits`` dict, and streaming returns an ``SSEStream``
exposing the same headers via ``.rate_limits``.
"""

import json
from unittest.mock import MagicMock

from saia_python._http import RetryPolicy
from saia_python._streaming import SSEStream
from saia_python.chat import ChatService

_RL_HEADERS = {
    "x-ratelimit-limit-minute": "30",
    "x-ratelimit-remaining-minute": "29",
}


def _make_service() -> ChatService:
    svc = ChatService.__new__(ChatService)
    svc._session = MagicMock()
    svc._base_url = "https://example.com/v1"
    svc._retry = RetryPolicy()
    return svc


def test_completions_non_streaming_attaches_rate_limits_dict():
    """stream=False returns the response dict with a JSON-serializable
    ``_rate_limits`` dict (not a RateLimitInfo instance)."""
    svc = _make_service()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = _RL_HEADERS
    resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    svc._session.post.return_value = resp

    result = svc.completions("m", [{"role": "user", "content": "hi"}])

    assert isinstance(result, dict)
    assert isinstance(result["_rate_limits"], dict)
    assert result["_rate_limits"]["remaining_minute"] == 29
    # The whole response round-trips through json.dumps — the point of the dict form.
    json.dumps(result)


def test_completions_streaming_returns_sse_stream():
    """stream=True returns an SSEStream whose .rate_limits is ready immediately,
    and POSTs with stream=True."""
    svc = _make_service()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = _RL_HEADERS
    resp.iter_lines.return_value = iter(["data: [DONE]"])
    svc._session.post.return_value = resp

    result = svc.completions("m", [{"role": "user", "content": "hi"}], stream=True)

    assert isinstance(result, SSEStream)
    assert result.rate_limits["remaining_minute"] == 29
    assert svc._session.post.call_args.kwargs.get("stream") is True
