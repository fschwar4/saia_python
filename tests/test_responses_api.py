"""Tests for ResponsesService.create — ``/responses`` over the shared transport.

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
from saia_python.responses_api import ResponsesService

from ._generation_fixtures import (
    RESPONSE,
    RESPONSE_400_BODY,
    RESPONSE_REASONING_STREAM_LINES,
    RESPONSE_STREAM_LINES,
    RESPONSE_TEXT,
)
from ._rate_limit_headers import CURRENT_429, CURRENT_429_BODY, CURRENT_OK

_BASE = "https://example.com/v1"
_INPUT = "Name the three primary colours of light, comma-separated."


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


def _service(*responses, retry=None) -> ResponsesService:
    session = MagicMock()
    session.post.side_effect = list(responses)
    return ResponsesService(session, _BASE, retry=retry)


def test_create_posts_the_input_to_responses():
    svc = _service(_resp(json_body=RESPONSE))
    svc.create(
        "m",
        _INPUT,
        instructions="Answer briefly.",
        max_output_tokens=16,
        temperature=0,
        tool_choice="none",
    )
    args, kwargs = svc._session.post.call_args
    assert args == (f"{_BASE}/responses",)
    assert kwargs["json"] == {
        "model": "m",
        "input": _INPUT,
        "instructions": "Answer briefly.",
        "max_output_tokens": 16,
        "temperature": 0,
        "tool_choice": "none",
    }
    assert "stream" not in kwargs


def test_create_omits_unset_knobs_and_passes_an_input_list():
    svc = _service(_resp(json_body=RESPONSE))
    messages = [{"role": "user", "content": "Hi"}]
    svc.create("m", messages)
    assert svc._session.post.call_args.kwargs["json"] == {
        "model": "m",
        "input": messages,
    }


def test_create_returns_the_response_with_rate_limits():
    svc = _service(_resp(json_body=RESPONSE))
    result = svc.create("m", _INPUT, max_output_tokens=16)
    assert isinstance(result, dict)
    assert result["object"] == "response"
    assert result["status"] == "completed"
    assert result["_rate_limits"]["remaining_10s"] == 9
    json.dumps(result)
    assert text_of(result) == RESPONSE_TEXT
    assert usage_of(result) == {
        "input_tokens": 27,
        "output_tokens": 6,
        "total_tokens": 33,
    }


def test_create_streams_the_recorded_events():
    svc = _service(_resp(lines=RESPONSE_STREAM_LINES))
    stream = svc.create("m", _INPUT, max_output_tokens=16, stream=True)
    assert isinstance(stream, SSEStream)
    assert stream.rate_limits["remaining_10s"] == 9
    kwargs = svc._session.post.call_args.kwargs
    assert kwargs["json"]["stream"] is True
    assert kwargs["headers"]["Accept"] == "text/event-stream"

    events = list(stream)  # ends when the lines do: this stream sends no [DONE]
    types = [event["type"] for event in events]
    assert types[0] == "response.created"
    assert types[-1] == "response.completed"
    assert types.count("response.output_text.delta") == 3
    final = events[-1]
    assert text_of(final) == RESPONSE_TEXT  # the final event holds the response
    assert usage_of(final)["total_tokens"] == 33


def test_iter_text_reads_the_stream_and_keeps_the_usage():
    svc = _service(_resp(lines=RESPONSE_STREAM_LINES))
    stream = svc.create("m", _INPUT, max_output_tokens=16, stream=True)
    text = iter_text(stream)
    assert list(text) == ["Red", ", Green,", " Blue"]
    assert usage_of(text.last)["total_tokens"] == 33  # live text, then the counts


def test_iter_text_skips_the_reasoning_of_a_reasoning_model():
    svc = _service(_resp(lines=RESPONSE_REASONING_STREAM_LINES))
    stream = svc.create("m", "What is 2+2?", max_output_tokens=512, stream=True)
    assert "".join(iter_text(stream)) == "4"


def test_http_400_raises_api_error_with_the_server_message():
    svc = _service(_resp(400, json_body=RESPONSE_400_BODY))
    with pytest.raises(APIError, match="max_tokens must be at least 1") as exc:
        svc.create("m", "hi", max_output_tokens=-1)
    assert exc.value.status_code == 400


def test_retry_false_raises_on_429_without_retrying():
    svc = _service(_resp(429, headers=CURRENT_429, json_body=CURRENT_429_BODY))
    with pytest.raises(RateLimitError):
        svc.create("m", "hi", retry=False)
    assert svc._session.post.call_count == 1


def test_the_service_policy_applies_when_no_override_is_given():
    svc = _service(
        _resp(429, headers=CURRENT_429, json_body=CURRENT_429_BODY),
        retry=RetryPolicy(max_waiting_time=5),
    )
    with pytest.raises(RateLimitError):
        svc.create("m", "hi")
    assert svc._session.post.call_count == 1


def test_client_exposes_one_service_on_its_session():
    client = SAIAClient(api_key="k", base_url=_BASE, retry=False)
    svc = client.responses
    assert isinstance(svc, ResponsesService)
    assert client.responses is svc
    assert svc._session is client._session
    assert svc._retry.on_rate_limit is False
    assert repr(svc) == f"ResponsesService(base_url={_BASE!r})"
