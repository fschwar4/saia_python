"""Tests for MessagesService.create — ``/messages`` over the shared transport.

Offline: a ``MagicMock`` session answers with responses recorded from SAIA
(``_generation_fixtures``, ``_rate_limit_headers``).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from saia_python import SAIAClient, iter_text, text_of, usage_of
from saia_python._http import RetryPolicy
from saia_python._streaming import SSEStream
from saia_python.exceptions import APIError, RateLimitError
from saia_python.messages import MessagesService

from ._generation_fixtures import (
    MESSAGE,
    MESSAGE_400_BODY,
    MESSAGE_REASONING_STREAM_LINES,
    MESSAGE_STREAM_LINES,
    MESSAGE_TEXT,
    MESSAGE_TOOL_USE_STREAM_LINES,
)
from ._rate_limit_headers import CURRENT_429, CURRENT_429_BODY, CURRENT_OK

_BASE = "https://example.com/v1"
_MESSAGES = [
    {
        "role": "user",
        "content": "Name the three primary colours of light, comma-separated.",
    }
]


def _resp(status_code=200, *, headers=None, json_body=None, lines=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers if headers is not None else CURRENT_OK
    if json_body is not None:
        resp.json.return_value = json.loads(json.dumps(json_body))  # a fresh copy
        resp.text = json.dumps(json_body)
    if lines is not None:
        resp.iter_lines.return_value = iter(lines)
    return resp


def _service(*responses, retry=None) -> MessagesService:
    session = MagicMock()
    session.post.side_effect = list(responses)
    return MessagesService(session, _BASE, retry=retry)


def test_create_posts_the_messages_to_messages():
    svc = _service(_resp(json_body=MESSAGE))
    svc.create(
        "m",
        _MESSAGES,
        16,
        system="Answer briefly.",
        temperature=0,
        top_k=1,
    )
    args, kwargs = svc._session.post.call_args
    assert args == (f"{_BASE}/messages",)
    assert kwargs["json"] == {
        "model": "m",
        "messages": _MESSAGES,
        "max_tokens": 16,
        "system": "Answer briefly.",
        "temperature": 0,
        "top_k": 1,
    }
    assert "stream" not in kwargs


def test_create_omits_unset_knobs_but_always_sends_max_tokens():
    svc = _service(_resp(json_body=MESSAGE))
    svc.create("m", _MESSAGES, max_tokens=8)
    assert svc._session.post.call_args.kwargs["json"] == {
        "model": "m",
        "messages": _MESSAGES,
        "max_tokens": 8,
    }


def test_create_requires_max_tokens():
    svc = _service(_resp(json_body=MESSAGE))
    with pytest.raises(TypeError, match="max_tokens"):
        svc.create("m", _MESSAGES)  # type: ignore[call-arg]
    svc._session.post.assert_not_called()


def test_create_returns_the_message_with_rate_limits():
    svc = _service(_resp(json_body=MESSAGE))
    result = svc.create("m", _MESSAGES, 16)
    assert isinstance(result, dict)
    assert result["type"] == "message"
    assert result["stop_reason"] == "end_turn"
    assert result["_rate_limits"]["remaining_10s"] == 9
    json.dumps(result)
    assert text_of(result) == MESSAGE_TEXT
    assert usage_of(result) == {
        "input_tokens": 27,
        "output_tokens": 6,
        "total_tokens": 33,
    }


def test_create_streams_the_recorded_events():
    svc = _service(_resp(lines=MESSAGE_STREAM_LINES))
    stream = svc.create("m", _MESSAGES, 16, stream=True)
    assert isinstance(stream, SSEStream)
    assert stream.rate_limits["remaining_10s"] == 9
    kwargs = svc._session.post.call_args.kwargs
    assert kwargs["json"]["stream"] is True
    assert kwargs["headers"]["Accept"] == "text/event-stream"

    events = list(stream)  # ends when the lines do: this stream sends no [DONE]
    types = [event["type"] for event in events]
    assert types[0] == "message_start"
    assert types[-2:] == ["message_delta", "message_stop"]
    assert types.count("content_block_delta") == 5
    assert usage_of(events[0])["input_tokens"] == 27  # message_start
    assert usage_of(events[-2])["output_tokens"] == 6  # message_delta
    assert usage_of(events[-1])["total_tokens"] is None  # message_stop


def test_iter_text_reads_the_stream_and_merges_its_usage():
    svc = _service(_resp(lines=MESSAGE_STREAM_LINES))
    text = iter_text(svc.create("m", _MESSAGES, 16, stream=True))
    assert list(text) == ["Red", ",", " Green", ",", " Blue"]
    assert text.usage == {"input_tokens": 27, "output_tokens": 6, "total_tokens": 33}
    assert text.last == {"type": "message_stop"}


def test_iter_text_skips_the_thinking_of_a_reasoning_model():
    svc = _service(_resp(lines=MESSAGE_REASONING_STREAM_LINES))
    text = iter_text(svc.create("m", [], 512, stream=True))
    assert "".join(text) == "4"
    assert text.usage == {"input_tokens": 43, "output_tokens": 19, "total_tokens": 62}


def test_iter_text_yields_nothing_for_a_streamed_tool_call():
    svc = _service(_resp(lines=MESSAGE_TOOL_USE_STREAM_LINES))
    text = iter_text(svc.create("m", [], 128, stream=True))
    assert list(text) == []  # the arguments are not text
    assert text.usage["total_tokens"] == 175


def test_http_400_raises_api_error_with_the_server_message():
    # The body SAIA sent for a call without max_tokens, which the signature
    # rules out; any rejected parameter gets this shape.
    svc = _service(_resp(400, json_body=MESSAGE_400_BODY))
    with pytest.raises(APIError, match="body.max_tokens") as exc:
        svc.create("m", _MESSAGES, 8)
    assert exc.value.status_code == 400
    assert "Field required" in str(exc.value)


def test_retry_false_raises_on_429_without_retrying():
    svc = _service(_resp(429, headers=CURRENT_429, json_body=CURRENT_429_BODY))
    with pytest.raises(RateLimitError):
        svc.create("m", _MESSAGES, 8, retry=False)
    assert svc._session.post.call_count == 1


def test_the_service_policy_applies_when_no_override_is_given():
    svc = _service(
        _resp(429, headers=CURRENT_429, json_body=CURRENT_429_BODY),
        retry=RetryPolicy(max_waiting_time=5),
    )
    with pytest.raises(RateLimitError):
        svc.create("m", _MESSAGES, 8)
    assert svc._session.post.call_count == 1


def test_client_exposes_one_service_on_its_session():
    client = SAIAClient(api_key="k", base_url=_BASE, retry=False)
    svc = client.messages
    assert isinstance(svc, MessagesService)
    assert client.messages is svc
    assert svc._session is client._session
    assert svc._retry.on_rate_limit is False
    assert repr(svc) == f"MessagesService(base_url={_BASE!r})"
