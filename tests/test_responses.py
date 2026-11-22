"""Tests for saia_python.responses: text_of, iter_text, aiter_text, usage_of.

The SDK tests run the real OpenAI client over an ``httpx.MockTransport`` that
answers with the recorded SAIA responses, so the helpers see exactly the
objects the SDK hands to a caller (stream chunks are built without
validation, e.g. with ``finish_reason=None``). The Anthropic SDK is no
dependency, so a stub with ``model_dump()`` stands in for its objects.
"""

import asyncio
import json
import logging

import pytest

from saia_python import (
    AsyncTextIterator,
    TextIterator,
    aiter_text,
    iter_text,
    parse_arcana_references,
    text_of,
    usage_of,
)
from saia_python.exceptions import APIError

from ._generation_fixtures import (
    COMPLETION,
    COMPLETION_N2_CHUNKS,
    COMPLETION_STREAM_LINES,
    COMPLETION_TEXT,
    MESSAGE,
    MESSAGE_MAX_TOKENS,
    MESSAGE_REASONING,
    MESSAGE_REASONING_STREAM_LINES,
    MESSAGE_STREAM_LINES,
    MESSAGE_TEXT,
    MESSAGE_TOOL_USE,
    MESSAGE_TOOL_USE_STREAM_LINES,
    RESPONSE,
    RESPONSE_INCOMPLETE,
    RESPONSE_REASONING,
    RESPONSE_REASONING_STREAM_LINES,
    RESPONSE_STREAM_LINES,
    RESPONSE_TEXT,
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


def _parse(lines):
    """The JSON of each ``data:`` line, as :class:`~saia_python.SSEStream` reads it."""
    return [
        json.loads(line[len("data: ") :])
        for line in lines
        if line.startswith("data: {")
    ]


def _completion_chunks():
    return _parse(COMPLETION_STREAM_LINES)


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


# --- text_of: tool calls ---------------------------------------------------------

_TOOL_CALL = {"name": "get_weather", "arguments": '{"city": "Paris"}'}

_CHAT_TOOL_CALL = {
    **_CHAT_COMPLETION,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_test", "type": "function", "function": _TOOL_CALL}
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
}

_RESPONSE_TOOL_CALL = {
    **RESPONSE,
    "output": [
        {
            "type": "function_call",
            "id": "fc_test",
            "call_id": "call_test",
            "status": "completed",
            **_TOOL_CALL,
        }
    ],
}


def _logged(caplog):
    """(level, message) of each record from the helpers' logger."""
    return [
        (r.levelname, r.getMessage())
        for r in caplog.records
        if r.name == "saia_python.responses"
    ]


@pytest.mark.parametrize(
    "response",
    [_CHAT_TOOL_CALL, _RESPONSE_TOOL_CALL, MESSAGE_TOOL_USE],
    ids=["chat", "responses", "messages"],
)
def test_text_of_logs_a_tool_call_at_debug_only(caplog, response):
    with caplog.at_level(logging.DEBUG, logger="saia_python.responses"):
        assert text_of(response) == ""
    assert _logged(caplog) == [
        ("DEBUG", "text_of: no text, the response calls get_weather")
    ]


def test_text_of_logs_the_tool_calls_of_openai_sdk_objects_at_debug_only(caplog):
    question = [{"role": "user", "content": "Weather in Paris?"}]
    chat = _sdk_client(
        json.dumps(_CHAT_TOOL_CALL).encode(), "application/json"
    ).chat.completions.create(model="m", messages=question)
    response = _sdk_client(
        json.dumps(_RESPONSE_TOOL_CALL).encode(), "application/json"
    ).responses.create(model="m", input=question)
    with caplog.at_level(logging.DEBUG, logger="saia_python.responses"):
        assert text_of(chat) == text_of(response) == ""
    assert (
        _logged(caplog)
        == [("DEBUG", "text_of: no text, the response calls get_weather")] * 2
    )


def test_text_of_names_every_tool_called(caplog):
    chat = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"type": "function", "function": {"name": "get_weather"}},
                        {"type": "function", "function": {"name": "get_time"}},
                        None,  # malformed, still a call
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    response = {
        "object": "response",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "function_call", "name": "get_weather", "arguments": "{}"},
            {"type": "web_search_call", "status": "completed"},
            "junk",
        ],
    }
    message = {
        "type": "message",
        "stop_reason": "tool_use",
        "content": [
            {"type": "thinking", "thinking": "…", "signature": "s"},
            {"type": "tool_use", "id": "t1", "name": "get_weather", "input": {}},
            {"type": "server_tool_use", "id": "t2", "name": "web_search"},
            {"type": "tool_use", "id": "t3", "input": {}},  # no name
            "junk",
        ],
    }
    with caplog.at_level(logging.DEBUG, logger="saia_python.responses"):
        text_of(chat)
        text_of(response)
        text_of(message)
    assert [message for _, message in _logged(caplog)] == [
        "text_of: no text, the response calls get_weather, get_time, a tool",
        "text_of: no text, the response calls get_weather, web_search_call",
        "text_of: no text, the response calls get_weather, web_search, tool_use",
    ]


def test_text_of_still_warns_about_a_truncated_tool_call(caplog):
    chat = json.loads(json.dumps(_CHAT_TOOL_CALL))
    chat["choices"][0]["finish_reason"] = "length"
    response = {**_RESPONSE_TOOL_CALL, "status": "incomplete"}
    message = {**MESSAGE_TOOL_USE, "stop_reason": "max_tokens"}
    with caplog.at_level(logging.DEBUG, logger="saia_python.responses"):
        assert text_of(chat) == text_of(response) == text_of(message) == ""
    assert _logged(caplog) == [
        ("WARNING", "text_of: first choice has empty content; finish_reason='length'"),
        ("WARNING", "text_of: response has no output text; status='incomplete'"),
        ("WARNING", "text_of: message has no text; stop_reason='max_tokens'"),
    ]


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


# --- the Responses API shape -----------------------------------------------------


def _sse_lines_body(lines) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def test_text_of_reads_a_responses_api_object():
    assert text_of(RESPONSE) == RESPONSE_TEXT


def test_text_of_skips_the_reasoning_item():
    assert RESPONSE_REASONING["output"][0]["type"] == "reasoning"
    assert text_of(RESPONSE_REASONING) == "4"


def test_text_of_returns_the_partial_text_of_an_incomplete_response():
    assert RESPONSE_INCOMPLETE["status"] == "incomplete"
    assert text_of(RESPONSE_INCOMPLETE) == "2, 3"


def test_text_of_joins_every_output_text_part_and_skips_the_rest():
    response = {
        "object": "response",
        "output": [
            {"type": "function_call", "name": "f", "arguments": "{}"},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "one "},
                    {"type": "refusal", "refusal": "no"},
                ],
            },
            {"type": "message", "content": [{"type": "output_text", "text": "two"}]},
        ],
    }
    assert text_of(response) == "one two"


def test_text_of_warns_when_a_response_has_no_output_text(caplog):
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        assert text_of({"object": "response", "status": "failed", "output": []}) == ""
    assert any("no output text" in r.message for r in caplog.records)


def test_text_of_and_usage_of_read_the_final_stream_event():
    final = _parse(RESPONSE_STREAM_LINES)[-1]
    assert final["type"] == "response.completed"
    assert text_of(final) == RESPONSE_TEXT
    assert usage_of(final) == {
        "input_tokens": 27,
        "output_tokens": 6,
        "total_tokens": 33,
    }


def test_text_of_and_usage_of_read_openai_sdk_response_objects():
    response = _sdk_client(
        json.dumps(RESPONSE).encode(), "application/json"
    ).responses.create(model="m", input="Name the three primary colours.")
    assert type(response).__name__ == "Response"
    assert text_of(response) == response.output_text == RESPONSE_TEXT
    assert usage_of(response)["total_tokens"] == 33


def test_iter_text_joins_a_responses_stream():
    assert list(iter_text(_parse(RESPONSE_STREAM_LINES))) == [
        "Red",
        ", Green,",
        " Blue",
    ]


def test_iter_text_skips_reasoning_deltas():
    events = _parse(RESPONSE_REASONING_STREAM_LINES)
    kinds = {event["type"] for event in events}
    assert "response.reasoning_text.delta" in kinds
    assert list(iter_text(events)) == ["4"]


def test_iter_text_reads_openai_sdk_responses_streams():
    client = _sdk_client(_sse_lines_body(RESPONSE_STREAM_LINES), "text/event-stream")
    stream = client.responses.create(model="m", input="x", stream=True)
    assert "".join(iter_text(stream)) == RESPONSE_TEXT

    client = _sdk_client(
        _sse_lines_body(RESPONSE_REASONING_STREAM_LINES), "text/event-stream"
    )
    stream = client.responses.create(model="m", input="x", stream=True)
    assert "".join(iter_text(stream)) == "4"


def test_iter_text_raises_on_an_error_event():
    events = [
        {"type": "response.output_text.delta", "delta": "partial"},
        {
            "type": "error",
            "code": "server_error",
            "message": "boom in the middle",
            "param": None,
            "sequence_number": 5,
        },
    ]
    pieces = []
    with pytest.raises(APIError, match="boom in the middle") as exc:
        for piece in iter_text(events):
            pieces.append(piece)
    assert pieces == ["partial"]
    assert exc.value.status_code is None


def test_iter_text_raises_on_response_failed():
    failed = {
        "type": "response.failed",
        "response": {
            "object": "response",
            "status": "failed",
            "error": {"code": "server_error", "message": "the model failed"},
        },
    }
    with pytest.raises(APIError, match="the model failed"):
        list(iter_text([failed]))
    no_detail = {"type": "response.failed", "response": {"status": "failed"}}
    with pytest.raises(APIError, match="the response failed"):
        list(iter_text([no_detail]))


def test_iter_text_treats_response_incomplete_as_the_normal_end():
    events = [
        {"type": "response.output_text.delta", "delta": "2, 3"},
        {"type": "response.incomplete", "response": {"status": "incomplete"}},
    ]
    assert list(iter_text(events)) == ["2, 3"]


def test_aiter_text_joins_a_responses_stream():
    async def _events():
        for event in _parse(RESPONSE_STREAM_LINES):
            yield event

    async def _run():
        return "".join([piece async for piece in aiter_text(_events())])

    assert asyncio.run(_run()) == RESPONSE_TEXT


# --- the iterator keeps the last chunk -------------------------------------------


def test_iter_text_keeps_the_last_chunk_for_usage_of():
    usage_chunk = {
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }
    text = iter_text([_chat_chunk("Hel"), _chat_chunk("lo"), usage_chunk])
    assert isinstance(text, TextIterator)
    assert text.last is None
    assert list(text) == ["Hel", "lo"]
    assert text.last is usage_chunk
    assert usage_of(text.last)["total_tokens"] == 7

    text = iter_text(_completion_chunks())
    assert "".join(text) == COMPLETION_TEXT
    assert usage_of(text.last) == {
        "input_tokens": 6,
        "output_tokens": 4,
        "total_tokens": 10,
    }

    text = iter_text(_parse(RESPONSE_STREAM_LINES))
    assert "".join(text) == RESPONSE_TEXT
    assert text.last["type"] == "response.completed"
    assert text_of(text.last) == RESPONSE_TEXT
    assert usage_of(text.last)["total_tokens"] == 33


def test_iter_text_keeps_the_last_chunk_of_openai_sdk_streams():
    body = ("\n".join(COMPLETION_STREAM_LINES) + "\n").encode()
    stream = _sdk_client(body, "text/event-stream").completions.create(
        model="m", prompt="Say hi in one word:", max_tokens=4, stream=True
    )
    text = iter_text(stream)
    assert "".join(text) == COMPLETION_TEXT
    assert not isinstance(text.last, dict)  # the SDK's own chunk object
    assert usage_of(text.last)["total_tokens"] == 10

    client = _sdk_client(_sse_lines_body(RESPONSE_STREAM_LINES), "text/event-stream")
    text = iter_text(client.responses.create(model="m", input="x", stream=True))
    assert "".join(text) == RESPONSE_TEXT
    assert type(text.last).__name__ == "ResponseCompletedEvent"
    assert usage_of(text.last)["total_tokens"] == 33


def test_iter_text_keeps_the_chunk_that_reported_an_error():
    error_chunk = {"error": {"message": "boom"}}
    text = iter_text([_chat_chunk("partial"), error_chunk])
    with pytest.raises(APIError):
        list(text)
    assert text.last is error_chunk


def test_iter_text_close_stops_reading_and_closes_the_stream():
    first = _chat_chunk("a")
    stream = _ClosableStream([first, _chat_chunk("b")])
    text = iter_text(stream)
    assert next(text) == "a"
    assert text.last is first
    text.close()
    assert stream.closed
    assert list(text) == []


def test_aiter_text_keeps_the_last_event():
    async def _events():
        for event in _parse(RESPONSE_STREAM_LINES):
            yield event

    async def _run():
        text = aiter_text(_events())
        assert isinstance(text, AsyncTextIterator)
        assert text.last is None
        joined = "".join([piece async for piece in text])
        return joined, text.last

    joined, last = asyncio.run(_run())
    assert joined == RESPONSE_TEXT
    assert last["type"] == "response.completed"
    assert usage_of(last)["total_tokens"] == 33


def test_aiter_text_aclose_stops_reading_and_closes_the_stream():
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
        text = aiter_text(AsyncStream([_chat_chunk("a"), _chat_chunk("b")]))
        first = await text.__anext__()
        await text.aclose()
        return first, [piece async for piece in text]

    assert asyncio.run(_run()) == ("a", [])
    assert closed == [True]


# --- the Messages API shape (Anthropic's format) ---------------------------------


class _Dumped:
    """Stands in for an Anthropic SDK object: a pydantic model with
    ``model_dump()``."""

    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return json.loads(json.dumps(self._data))


def test_text_of_reads_a_messages_api_object():
    assert text_of(MESSAGE) == MESSAGE_TEXT


def test_text_of_skips_the_thinking_block():
    assert text_of(MESSAGE_REASONING) == "4"


def test_text_of_returns_the_partial_text_of_a_message_cut_off(caplog):
    with caplog.at_level(logging.DEBUG, logger="saia_python.responses"):
        assert text_of(MESSAGE_MAX_TOKENS) == "1, 2"
    assert _logged(caplog) == []


def test_text_of_joins_every_text_block_and_skips_the_rest():
    message = {
        "type": "message",
        "content": [
            {"type": "thinking", "thinking": "hmm", "signature": "s"},
            {"type": "redacted_thinking", "data": "…"},
            {"type": "text", "text": "Red, "},
            {"type": "tool_use", "id": "t", "name": "get_weather", "input": {}},
            {"type": "text", "text": None},
            "junk",
            {"type": "text", "text": "Blue"},
        ],
        "stop_reason": "end_turn",
    }
    assert text_of(message) == "Red, Blue"


def test_text_of_warns_when_a_message_has_no_text(caplog):
    message = {**MESSAGE, "content": [], "stop_reason": "end_turn"}
    with caplog.at_level(logging.DEBUG, logger="saia_python.responses"):
        assert text_of(message) == ""
    assert _logged(caplog) == [
        ("WARNING", "text_of: message has no text; stop_reason='end_turn'")
    ]


def test_text_of_and_usage_of_read_sdk_objects_with_model_dump():
    assert text_of(_Dumped(MESSAGE_REASONING)) == "4"
    assert usage_of(_Dumped(MESSAGE)) == {
        "input_tokens": 27,
        "output_tokens": 6,
        "total_tokens": 33,
    }


def test_usage_of_reads_a_message_and_its_stream_events():
    events = _parse(MESSAGE_STREAM_LINES)
    start, delta, stop = events[0], events[-2], events[-1]
    assert (start["type"], delta["type"], stop["type"]) == (
        "message_start",
        "message_delta",
        "message_stop",
    )
    assert usage_of(MESSAGE)["total_tokens"] == 33
    assert usage_of(start) == {
        "input_tokens": 27,
        "output_tokens": 0,
        "total_tokens": 27,
    }
    assert usage_of(delta) == usage_of(MESSAGE)
    assert usage_of(stop)["total_tokens"] is None  # the last event has none


def test_iter_text_joins_a_messages_stream():
    pieces = list(iter_text(_parse(MESSAGE_STREAM_LINES)))
    assert pieces == ["Red", ",", " Green", ",", " Blue"]
    assert "".join(pieces) == text_of(MESSAGE)


def test_iter_text_skips_thinking_and_signature_deltas():
    events = _parse(MESSAGE_REASONING_STREAM_LINES)
    deltas = {e["delta"]["type"] for e in events if e["type"] == "content_block_delta"}
    assert deltas == {"thinking_delta", "signature_delta", "text_delta"}
    assert list(iter_text(events)) == ["4"]


def test_iter_text_skips_the_arguments_of_a_streamed_tool_call():
    events = _parse(MESSAGE_TOOL_USE_STREAM_LINES)
    assert any(e.get("delta", {}).get("type") == "input_json_delta" for e in events)
    assert list(iter_text(events)) == []


def test_iter_text_skips_malformed_content_block_deltas():
    events = [
        {"type": "content_block_delta", "delta": "not a dict"},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": 7}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
    ]
    assert list(iter_text(events)) == ["ok"]


def test_iter_text_raises_on_a_messages_error_event():
    events = [
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Re"}},
        {
            "type": "error",
            "error": {"type": "overloaded_error", "message": "Overloaded"},
        },
    ]
    pieces = []
    with pytest.raises(APIError, match="Overloaded") as exc:
        for piece in iter_text(events):
            pieces.append(piece)
    assert pieces == ["Re"]
    assert exc.value.status_code is None


def test_iter_text_reads_a_stream_of_sdk_event_objects():
    events = [_Dumped(event) for event in _parse(MESSAGE_STREAM_LINES)]
    text = iter_text(events)
    assert "".join(text) == MESSAGE_TEXT
    assert text.usage["total_tokens"] == 33
    assert text.last is events[-1]  # as the stream gave it


def test_aiter_text_joins_a_messages_stream():
    async def _events():
        for event in _parse(MESSAGE_REASONING_STREAM_LINES):
            yield event

    async def _run():
        text = aiter_text(_events())
        return "".join([piece async for piece in text]), text.usage

    assert asyncio.run(_run()) == (
        "4",
        {"input_tokens": 43, "output_tokens": 19, "total_tokens": 62},
    )


# --- the iterator's usage --------------------------------------------------------

_NO_USAGE = {"input_tokens": None, "output_tokens": None, "total_tokens": None}


def test_usage_is_what_the_stream_has_reported_so_far():
    text = iter_text(_parse(MESSAGE_STREAM_LINES))
    assert text.usage == _NO_USAGE
    assert next(text) == "Red"  # message_start has been read
    assert text.usage == {"input_tokens": 27, "output_tokens": 0, "total_tokens": 27}
    assert "".join(text) == ", Green, Blue"
    assert text.usage == {"input_tokens": 27, "output_tokens": 6, "total_tokens": 33}


def test_usage_equals_usage_of_the_last_chunk_on_the_other_routes():
    usage_chunk = {
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }
    for chunks in (
        [_chat_chunk("Hel"), _chat_chunk("lo"), usage_chunk],
        _completion_chunks(),
        _parse(RESPONSE_STREAM_LINES),
        _parse(RESPONSE_REASONING_STREAM_LINES),
    ):
        text = iter_text(chunks)
        list(text)
        assert text.usage == usage_of(text.last)
        assert text.usage["total_tokens"] is not None


def test_usage_merges_the_counts_report_by_report():
    # Anthropic's own API sends only the output tokens in message_delta.
    events = [
        {
            "type": "message_start",
            "message": {
                "type": "message",
                "content": [],
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 7, "input_tokens": None},
        },
        {"type": "message_stop"},
    ]
    text = iter_text(events)
    assert list(text) == ["Hi"]
    assert text.usage == {"input_tokens": 10, "output_tokens": 7, "total_tokens": 17}


def test_usage_takes_a_total_only_from_the_report_that_carries_it():
    reports = [
        {"choices": [], "usage": {"prompt_tokens": 5, "total_tokens": 5}},
        {"choices": [], "usage": {"completion_tokens": 3}},
    ]
    text = iter_text(reports)
    list(text)
    assert text.usage == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}


def test_usage_ignores_counts_that_are_no_integers():
    reports = [
        {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}},
        {"choices": [], "usage": {"prompt_tokens": True, "completion_tokens": "9"}},
        {"choices": [], "usage": "junk"},
    ]
    text = iter_text(reports)
    list(text)
    assert text.usage == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}


def test_usage_keeps_the_counts_reported_before_an_error():
    events = _parse(MESSAGE_STREAM_LINES)[:3] + [
        {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    ]
    text = iter_text(events)
    with pytest.raises(APIError, match="boom"):
        list(text)
    assert text.usage == {"input_tokens": 27, "output_tokens": 0, "total_tokens": 27}


# --- ARCANA answers: references=True ---------------------------------------------

_ARCANA_ANSWER = (
    "The first option is preferred [RREF1], with details in [RREF2, RREF3].\n\n"
    "-----\n"
    "References:\n\n"
    "[RREF1] doc-a.md (0.21)\nChunk body...\n"
    "[RREF2] doc-b.md (0.30)\nChunk body...\n"
    "[RREF3] doc-a.md (0.33)\nChunk body...\n"
)


def _arcana_chunks(size=5):
    """The ARCANA answer as chat chunks of ``size`` characters, then usage."""
    text = _ARCANA_ANSWER
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    usage = {
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {"total_tokens": 99},
    }
    return (
        [_chat_chunk(role="assistant", content="")]
        + [_chat_chunk(piece) for piece in pieces]
        + [usage]
    )


def test_iter_text_with_references_streams_the_answer_without_the_block():
    expected = parse_arcana_references(_ARCANA_ANSWER)
    text = iter_text(_arcana_chunks(), references=True)
    assert text.references is None  # until the stream is through
    pieces = list(text)
    assert "".join(pieces) == expected.answer  # no block, no rule under it
    assert "".join(pieces).endswith("[RREF2, RREF3].")
    assert any("[RREF2, RREF3]" in piece for piece in pieces)
    assert text.references == expected
    assert text.references.by_number[3].filename == "doc-a.md"
    assert usage_of(text.last)["total_tokens"] == 99


def test_iter_text_with_references_can_keep_the_separator():
    expected = parse_arcana_references(_ARCANA_ANSWER)
    text = iter_text(_arcana_chunks(), references=True, strip_separator=False)
    assert "".join(text) == expected.prose == expected.answer + "\n\n-----"


def test_iter_text_yields_the_block_and_keeps_no_references_by_default():
    text = iter_text(_arcana_chunks())
    assert "".join(text) == _ARCANA_ANSWER
    assert text.references is None


def test_iter_text_keeps_no_references_when_the_stream_fails():
    text = iter_text(
        [_chat_chunk("partial"), {"error": {"message": "x"}}], references=True
    )
    with pytest.raises(APIError):
        list(text)
    assert text.references is None


def test_iter_text_with_references_yields_held_back_text_at_the_end():
    # No References block: the trailing newline might have started one, so it
    # waits, and comes out once the stream has ended.
    text = iter_text([_chat_chunk("No retrieval.\n")], references=True)
    assert list(text) == ["No retrieval.", "\n"]
    assert text.references.matched is False

    async def _chunks():
        yield _chat_chunk("see [RREF")

    async def _run():
        text = aiter_text(_chunks(), references=True)
        return [piece async for piece in text], text.references

    pieces, references = asyncio.run(_run())
    assert pieces == ["see ", "[RREF"]
    assert references.prose == "see [RREF"


def test_aiter_text_with_references_streams_the_answer_without_the_block():
    async def _chunks():
        for chunk in _arcana_chunks(size=3):
            yield chunk

    async def _run():
        text = aiter_text(_chunks(), references=True)
        return "".join([piece async for piece in text]), text.references

    joined, references = asyncio.run(_run())
    expected = parse_arcana_references(_ARCANA_ANSWER)
    assert joined == expected.answer
    assert references == expected
