"""Tests for structured output — ``response_format_for``, ``parse_structured``,
and ``completions_structured`` on the sync and async chat services.

The error cases mirror what SAIA returned live (2026-10-08): a reasoning model
that runs out of tokens while thinking answers HTTP 200 with ``content: None``
and ``finish_reason: "length"``.
"""

from __future__ import annotations

import asyncio
from typing import Generic, Literal, TypeVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from saia_python import (
    SAIAError,
    StructuredOutputError,
    parse_structured,
    response_format_for,
)
from saia_python._http import RetryPolicy
from saia_python.aio import AsyncChatService
from saia_python.chat import ChatService

from ._async_fakes import FakeAsyncClient, FakeAsyncResponse, rl_headers

T = TypeVar("T")

GOOD = '{"label": "negative", "confidence": 0.95}'


class Sentiment(BaseModel):
    label: Literal["positive", "negative", "neutral"]
    confidence: float


class Wrapper(BaseModel, Generic[T]):
    value: T


def _response(content, finish_reason="stop", **message):
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content, **message},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 21, "completion_tokens": 150, "total_tokens": 171},
    }


def _sync_service(json_body) -> ChatService:
    svc = ChatService.__new__(ChatService)
    svc._session = MagicMock()
    svc._base_url = "https://example.com/v1"
    svc._retry = RetryPolicy()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = rl_headers()
    resp.json.return_value = json_body
    svc._session.post.return_value = resp
    return svc


def test_response_format_for_sends_the_model_schema():
    assert response_format_for(Sentiment) == {
        "type": "json_schema",
        "json_schema": {"name": "Sentiment", "schema": Sentiment.model_json_schema()},
    }


def test_response_format_for_sanitizes_generic_model_names():
    # OpenAI-style APIs allow only a-z, A-Z, 0-9, _ and - in the name.
    assert response_format_for(Wrapper[int])["json_schema"]["name"] == "Wrapper_int_"


def test_parse_structured_returns_validated_instance():
    result = parse_structured(_response(GOOD), Sentiment)
    assert result == Sentiment(label="negative", confidence=0.95)


def test_reasoning_model_out_of_tokens_raises_with_hint():
    resp = _response(None, finish_reason="length", reasoning="Okay, the user...")
    with pytest.raises(StructuredOutputError) as info:
        parse_structured(resp, Sentiment)
    err = info.value
    assert isinstance(err, SAIAError)
    assert err.finish_reason == "length"
    assert "max_tokens" in str(err)
    assert "enable_thinking" in str(err)
    # The tokens were spent, so a caller billing from usage can still read it.
    assert err.response["usage"]["total_tokens"] == 171


def test_answer_cut_off_at_max_tokens_raises_truncation_error():
    resp = _response('{"label": "nega', finish_reason="length")
    with pytest.raises(StructuredOutputError, match="cut off at max_tokens") as info:
        parse_structured(resp, Sentiment)
    assert isinstance(info.value.__cause__, ValidationError)


def test_complete_answer_is_kept_even_when_generation_hit_the_limit():
    resp = _response(GOOD + "\n\n\n", finish_reason="length")
    assert parse_structured(resp, Sentiment).label == "negative"


def test_mismatching_answer_names_the_failing_field():
    # Bad label and missing confidence: the first error is named, the rest counted.
    resp = _response('{"label": "great"}')
    with pytest.raises(StructuredOutputError) as info:
        parse_structured(resp, Sentiment)
    message = str(info.value)
    assert "failed validation (label: " in message
    assert message.endswith("; 1 more)")
    assert info.value.finish_reason == "stop"
    assert isinstance(info.value.__cause__, ValidationError)


def test_non_json_answer_reports_the_parse_error():
    # What a backend that ignores the schema might send: JSON in a code fence.
    resp = _response(f"```json\n{GOOD}\n```")
    with pytest.raises(
        StructuredOutputError, match=r"failed validation \(Invalid JSON"
    ):
        parse_structured(resp, Sentiment)


def test_missing_content_reports_the_finish_reason():
    # E.g. the model called a tool instead of answering.
    resp = _response(None, finish_reason="tool_calls")
    with pytest.raises(StructuredOutputError, match="finish_reason='tool_calls'"):
        parse_structured(resp, Sentiment)


def test_refusal_is_reported():
    resp = _response(None, refusal="I can't help with that.")
    with pytest.raises(StructuredOutputError, match="refused: I can't help with that"):
        parse_structured(resp, Sentiment)


def test_no_choices_raises():
    with pytest.raises(StructuredOutputError, match="no choices") as info:
        parse_structured({"choices": []}, Sentiment)
    assert info.value.finish_reason is None


def test_completions_structured_sends_schema_and_returns_instance():
    svc = _sync_service(_response(GOOD))
    result = svc.completions_structured(
        "m",
        [{"role": "user", "content": "hi"}],
        Sentiment,
        max_tokens=2000,
        chat_template_kwargs={"enable_thinking": False},
    )
    assert result == Sentiment(label="negative", confidence=0.95)
    body = svc._session.post.call_args.kwargs["json"]
    assert body["response_format"] == response_format_for(Sentiment)
    assert body["max_tokens"] == 2000
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_completions_structured_refuses_streaming():
    svc = _sync_service(_response(GOOD))
    with pytest.raises(TypeError):
        svc.completions_structured("m", [], Sentiment, stream=True)
    svc._session.post.assert_not_called()


def test_async_completions_structured_sends_schema_and_returns_instance():
    client = FakeAsyncClient(
        responses=[
            FakeAsyncResponse(200, headers=rl_headers(), json_body=_response(GOOD))
        ]
    )
    svc = AsyncChatService(client, "https://x/v1")
    result = asyncio.run(svc.completions_structured("m", [], Sentiment))
    assert result == Sentiment(label="negative", confidence=0.95)
    assert client.calls[0]["json"]["response_format"] == response_format_for(Sentiment)
