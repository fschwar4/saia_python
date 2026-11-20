"""Tests for CompletionsService.create — ``/completions`` over the shared transport.

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
from saia_python.completions import CompletionsService
from saia_python.exceptions import APIError, RateLimitError

from ._generation_fixtures import (
    COMPLETION,
    COMPLETION_400_BODY,
    COMPLETION_STREAM_LINES,
    COMPLETION_TEXT,
)
from ._rate_limit_headers import CURRENT_429, CURRENT_429_BODY, CURRENT_OK

_BASE = "https://example.com/v1"


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


def _service(*responses, retry=None) -> CompletionsService:
    session = MagicMock()
    session.post.side_effect = list(responses)
    return CompletionsService(session, _BASE, retry=retry)


def test_create_posts_the_prompt_to_completions():
    svc = _service(_resp(json_body=COMPLETION))
    svc.create("m", "Say hi in one word:", max_tokens=4, temperature=0, stop=["\n"])
    args, kwargs = svc._session.post.call_args
    assert args == (f"{_BASE}/completions",)
    assert kwargs["json"] == {
        "model": "m",
        "prompt": "Say hi in one word:",
        "max_tokens": 4,
        "temperature": 0,
        "stop": ["\n"],
    }
    assert "stream" not in kwargs  # a plain, non-streamed request


def test_create_omits_unset_sampling_knobs():
    svc = _service(_resp(json_body=COMPLETION))
    svc.create("m", "x")
    assert svc._session.post.call_args.kwargs["json"] == {"model": "m", "prompt": "x"}


def test_create_returns_the_response_with_rate_limits():
    svc = _service(_resp(json_body=COMPLETION))
    result = svc.create("m", "Say hi in one word:", max_tokens=4)
    assert isinstance(result, dict)
    assert result["object"] == "text_completion"
    assert result["_rate_limits"]["remaining_10s"] == 9
    json.dumps(result)  # JSON-serializable, like chat
    assert text_of(result) == COMPLETION_TEXT
    assert usage_of(result) == {
        "input_tokens": 6,
        "output_tokens": 4,
        "total_tokens": 10,
    }


def test_create_streams_the_recorded_chunks():
    svc = _service(_resp(lines=COMPLETION_STREAM_LINES))
    stream = svc.create("m", "Say hi in one word:", max_tokens=4, stream=True)
    assert isinstance(stream, SSEStream)
    assert stream.rate_limits["remaining_10s"] == 9
    kwargs = svc._session.post.call_args.kwargs
    assert kwargs["json"]["stream"] is True
    assert kwargs["headers"]["Accept"] == "text/event-stream"
    assert kwargs["stream"] is True

    chunks = list(stream)
    assert len(chunks) == 5  # four text chunks and the usage chunk; [DONE] ends it
    assert chunks[-1]["choices"] == []
    assert usage_of(chunks[-1])["total_tokens"] == 10
    assert "".join(c["choices"][0]["text"] for c in chunks[:-1]) == COMPLETION_TEXT


def test_iter_text_reads_the_stream():
    svc = _service(_resp(lines=COMPLETION_STREAM_LINES))
    stream = svc.create("m", "Say hi in one word:", max_tokens=4, stream=True)
    assert "".join(iter_text(stream)) == COMPLETION_TEXT


def test_http_400_raises_api_error_with_the_server_message():
    svc = _service(_resp(400, json_body=COMPLETION_400_BODY))
    with pytest.raises(APIError) as exc:
        svc.create("m", "hi", max_tokens=-1)
    assert exc.value.status_code == 400
    assert str(exc.value).startswith("max_tokens must be at least 1")


def test_streamed_http_400_raises_once_iteration_starts():
    svc = _service(_resp(400, json_body=COMPLETION_400_BODY, lines=[]))
    stream = svc.create("m", "hi", max_tokens=-1, stream=True)
    with pytest.raises(APIError, match="max_tokens must be at least 1"):
        next(stream)


def test_retry_false_raises_on_429_without_retrying():
    svc = _service(_resp(429, headers=CURRENT_429, json_body=CURRENT_429_BODY))
    with pytest.raises(RateLimitError) as exc:
        svc.create("m", "hi", retry=False)
    assert exc.value.rate_limits.retry_after == 9
    assert svc._session.post.call_count == 1


def test_the_service_policy_applies_when_no_override_is_given():
    # A policy that may not wait 9 s gives up at once, without sleeping.
    svc = _service(
        _resp(429, headers=CURRENT_429, json_body=CURRENT_429_BODY),
        retry=RetryPolicy(max_waiting_time=5),
    )
    with pytest.raises(RateLimitError):
        svc.create("m", "hi")
    assert svc._session.post.call_count == 1


def test_client_exposes_one_service_on_its_session():
    client = SAIAClient(api_key="k", base_url=_BASE, retry=False)
    svc = client.completions
    assert isinstance(svc, CompletionsService)
    assert client.completions is svc  # created once
    assert svc._session is client._session
    assert svc._retry.on_rate_limit is False  # the client's policy
    assert repr(svc) == f"CompletionsService(base_url={_BASE!r})"
