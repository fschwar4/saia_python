"""Tests for saia_python.responses: text_of, iter_text, aiter_text, usage_of.

The SDK tests run the real OpenAI client over an ``httpx.MockTransport`` that
answers with the recorded SAIA responses, so the helpers see exactly the
objects the SDK hands to a caller (stream chunks are built without
validation, e.g. with ``finish_reason=None``).
"""

import asyncio
import json
import logging

import pytest

from saia_python import aiter_text, iter_text, text_of, usage_of
from saia_python.exceptions import APIError

from ._generation_fixtures import (
    COMPLETION,
    COMPLETION_N2_CHUNKS,
    COMPLETION_STREAM_LINES,
    COMPLETION_TEXT,
)


def test_text_of_extracts_first_choice_content():
    response = {
        "choices": [{"message": {"role": "assistant", "content": "Hello there"}}]
    }
    assert text_of(response) == "Hello there"


def test_text_of_returns_empty_string_for_empty_choices(caplog):
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        result = text_of({"choices": []})
    assert result == ""
    assert any("no choices" in r.message for r in caplog.records)


def test_text_of_returns_empty_string_when_choices_key_missing(caplog):
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        result = text_of({"error": "oops"})
    assert result == ""
    assert any("no choices" in r.message for r in caplog.records)


def test_text_of_returns_empty_when_content_is_none(caplog):
    response = {
        "choices": [
            {"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}
        ]
    }
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        result = text_of(response)
    assert result == ""
    assert any("empty content" in r.message for r in caplog.records)


def test_text_of_returns_empty_when_message_missing():
    """A choice without a `message` field shouldn't raise."""
    assert text_of({"choices": [{"finish_reason": "stop"}]}) == ""


def test_text_of_takes_first_choice_when_multiple_present():
    response = {
        "choices": [
            {"message": {"content": "first"}},
            {"message": {"content": "second"}},
        ]
    }
    assert text_of(response) == "first"


# --- helpers -------------------------------------------------------------------


def _sdk_client(body: bytes, content_type: str):
    """A real ``openai.OpenAI`` client whose every request gets ``body``."""
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")

    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return openai.OpenAI(
        api_key="test-key",
        base_url="http://saia.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _sse(chunks) -> bytes:
    """Frame chunk dicts as an SSE body, ending with ``[DONE]``."""
    events = [f"data: {json.dumps(chunk)}" for chunk in chunks] + ["data: [DONE]"]
    return ("\n\n".join(events) + "\n\n").encode()


def _chat_chunk(content=None, *, role=None, index=0, **delta):
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": index, "delta": delta, "finish_reason": None}],
    }


def _completion_chunks():
    return [
        json.loads(line[len("data: ") :])
        for line in COMPLETION_STREAM_LINES
        if line.startswith("data: {")
    ]


_CHAT_COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1,
    "model": "m",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello there"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
}


# --- text_of: text_completion responses and SDK objects --------------------------


def test_text_of_reads_a_text_completion():
    assert text_of(COMPLETION) == COMPLETION_TEXT


def test_text_of_tells_the_shapes_apart_without_an_object_field():
    assert text_of({"choices": [{"text": "raw"}]}) == "raw"
    assert text_of({"choices": [{"message": {"content": "chat"}}]}) == "chat"


def test_text_of_returns_empty_for_an_empty_completion_text(caplog):
    response = {
        "object": "text_completion",
        "choices": [{"text": "", "finish_reason": "length"}],
    }
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        assert text_of(response) == ""
    assert any("empty content" in r.message for r in caplog.records)


def test_text_of_accepts_openai_sdk_objects():
    completion = _sdk_client(
        json.dumps(COMPLETION).encode(), "application/json"
    ).completions.create(model="m", prompt="Say hi in one word:", max_tokens=4)
    assert type(completion).__name__ == "Completion"
    assert text_of(completion) == COMPLETION_TEXT

    chat = _sdk_client(
        json.dumps(_CHAT_COMPLETION).encode(), "application/json"
    ).chat.completions.create(model="m", messages=[{"role": "user", "content": "Hi"}])
    assert type(chat).__name__ == "ChatCompletion"
    assert text_of(chat) == "Hello there"


def test_text_of_dumps_any_object_with_model_dump():
    class Dumpable:
        def model_dump(self):
            return {"choices": [{"message": {"content": "dumped"}}]}

    assert text_of(Dumpable()) == "dumped"


def test_text_of_returns_empty_for_something_that_is_no_response(caplog):
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        assert text_of("not a response") == ""
    assert any("not a response" in r.message for r in caplog.records)


# --- iter_text / aiter_text ------------------------------------------------------


def test_iter_text_joins_a_chat_stream():
    chunks = [
        _chat_chunk(role="assistant", content=""),  # role-only opener
        _chat_chunk(reasoning_content="thinking…"),  # reasoning is not text
        _chat_chunk("Hel"),
        _chat_chunk("lo"),
        {
            "object": "chat.completion.chunk",
            "choices": [],
            "usage": {"total_tokens": 9},
        },
    ]
    assert list(iter_text(chunks)) == ["Hel", "lo"]


def test_iter_text_joins_a_completion_stream():
    assert "".join(iter_text(_completion_chunks())) == COMPLETION_TEXT


def test_iter_text_skips_chunks_that_are_not_objects():
    assert list(iter_text(["junk", None, _chat_chunk("ok")])) == ["ok"]


def test_iter_text_keeps_to_the_first_choice():
    assert "".join(iter_text(COMPLETION_N2_CHUNKS)) == " 3,"
    assert list(iter_text([_chat_chunk("a", index=1), _chat_chunk("b")])) == ["b"]


def test_iter_text_reads_openai_sdk_streams():
    body = ("\n".join(COMPLETION_STREAM_LINES) + "\n").encode()
    stream = _sdk_client(body, "text/event-stream").completions.create(
        model="m", prompt="Say hi in one word:", max_tokens=4, stream=True
    )
    assert "".join(iter_text(stream)) == COMPLETION_TEXT

    body = _sse([_chat_chunk(role="assistant", content=""), _chat_chunk("Hi")])
    stream = _sdk_client(body, "text/event-stream").chat.completions.create(
        model="m", messages=[{"role": "user", "content": "Hi"}], stream=True
    )
    assert "".join(iter_text(stream)) == "Hi"


def test_iter_text_raises_on_an_error_chunk():
    error_chunk = {
        "error": {
            "message": "boom mid-stream",
            "type": "InternalServerError",
            "param": None,
            "code": 500,
        }
    }
    pieces = []
    with pytest.raises(APIError) as exc:
        for piece in iter_text([_chat_chunk("partial"), error_chunk, _chat_chunk("x")]):
            pieces.append(piece)
    assert pieces == ["partial"]
    assert "boom mid-stream" in str(exc.value)
    assert exc.value.status_code is None  # the HTTP response itself was a 200
    assert json.loads(exc.value.response_body) == error_chunk


def test_iter_text_raises_on_the_older_vllm_error_chunk():
    with pytest.raises(APIError, match="old style"):
        list(iter_text([{"object": "error", "message": "old style", "code": 400}]))


class _ClosableStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self):
        self.closed = True


def test_iter_text_closes_the_stream_when_the_consumer_stops_early():
    stream = _ClosableStream([_chat_chunk("a"), _chat_chunk("b")])
    for _piece in iter_text(stream):
        break
    assert stream.closed


def test_iter_text_closes_the_stream_on_an_error_chunk():
    stream = _ClosableStream([{"error": {"message": "x"}}])
    with pytest.raises(APIError):
        list(iter_text(stream))
    assert stream.closed


def test_aiter_text_joins_an_async_stream_and_closes_it():
    closed = []

    class AsyncStream:
        def __init__(self, chunks):
            self._chunks = chunks

        async def __aiter__(self):
            for chunk in self._chunks:
                yield chunk

        async def aclose(self):
            closed.append(True)

    async def _run():
        stream = AsyncStream([_chat_chunk("Hel"), _chat_chunk("lo")])
        return [piece async for piece in aiter_text(stream)]

    assert asyncio.run(_run()) == ["Hel", "lo"]
    assert closed == [True]


def test_aiter_text_awaits_an_async_close_method():
    # The OpenAI SDK's AsyncStream has an async close(), not aclose().
    closed = []

    class SdkLikeStream:
        async def __aiter__(self):
            yield _chat_chunk("x")

        async def close(self):
            closed.append(True)

    async def _run():
        return [piece async for piece in aiter_text(SdkLikeStream())]

    assert asyncio.run(_run()) == ["x"]
    assert closed == [True]


def test_aiter_text_raises_on_an_error_chunk():
    async def _chunks():
        yield _chat_chunk("partial")
        yield {"error": {"message": "boom"}}

    async def _run():
        return [piece async for piece in aiter_text(_chunks())]

    with pytest.raises(APIError, match="boom"):
        asyncio.run(_run())


# --- usage_of --------------------------------------------------------------------


def test_usage_of_maps_prompt_and_completion_tokens():
    assert usage_of(COMPLETION) == {
        "input_tokens": 6,
        "output_tokens": 4,
        "total_tokens": 10,
    }
    assert usage_of(_CHAT_COMPLETION)["total_tokens"] == 11


def test_usage_of_reads_input_and_output_tokens_and_computes_the_total():
    usage = {"usage": {"input_tokens": 12, "output_tokens": 5}}
    assert usage_of(usage) == {
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
    }


def test_usage_of_reads_a_streams_final_usage_chunk():
    assert usage_of(_completion_chunks()[-1])["total_tokens"] == 10


def test_usage_of_gives_none_without_usage():
    empty = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    assert usage_of(_chat_chunk("x")) == empty
    assert usage_of({"usage": None}) == empty
    assert usage_of("not a response") == empty


def test_usage_of_accepts_openai_sdk_objects():
    completion = _sdk_client(
        json.dumps(COMPLETION).encode(), "application/json"
    ).completions.create(model="m", prompt="Say hi in one word:", max_tokens=4)
    assert usage_of(completion) == {
        "input_tokens": 6,
        "output_tokens": 4,
        "total_tokens": 10,
    }
