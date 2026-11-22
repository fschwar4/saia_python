"""Helpers for reading generation responses and streams.

They read what the native services return (plain dicts, and streams of dict
chunks) and SDK objects alike: anything with ``model_dump()``, such as the
OpenAI SDK's objects, is dumped to a dict first. The shapes understood so far:

- ``chat.completion`` from ``/chat/completions`` (chat and ARCANA RAG): the
  text is ``choices[0].message.content``, a stream chunk's
  ``choices[0].delta.content``.
- ``text_completion`` from ``/completions``: the text is ``choices[0].text``,
  in a stream chunk too.
- ``response`` from ``/responses`` (OpenAI's Responses API): the text is every
  ``output_text`` part of every ``message`` item; a stream sends it in
  ``response.output_text.delta`` events. Reasoning items are skipped.
- ``message`` from ``/messages`` (Anthropic's Messages format): the text is
  every ``text`` block of ``content``; a stream sends it in
  ``content_block_delta`` events with a ``text_delta``. Thinking blocks are
  skipped.

Every caller would otherwise write the same lookup chain. The helpers make it
safe and uniform: a response without text returns ``""`` (with a logged
warning, or only a DEBUG line when the response calls a tool instead) so
downstream string-handling code doesn't have to special-case it.

Despite the module name, this is **not** a wrapper for OpenAI's Responses API;
that is :mod:`saia_python.responses_api`.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Generator,
    Iterable,
    Iterator,
)
from typing import Any

from .arcana_references import ParsedReferences, ReferencesSplitter
from .exceptions import APIError

log = logging.getLogger(__name__)


def _as_dict(obj: Any) -> Any:
    """Return ``obj`` as plain data: SDK objects (pydantic models) are dumped."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    return dump() if callable(dump) else obj


def _unwrap_event(data: Any) -> Any:
    """The response or message a stream event carries, else ``data`` itself.

    ``response.created``, ``response.completed`` and the like wrap the whole
    Responses API object; the last one holds the final output and ``usage``.
    A Messages stream's ``message_start`` wraps the message as it begins,
    with the input tokens.
    """
    if not isinstance(data, dict):
        return data
    kind = data.get("type")
    if (
        isinstance(kind, str)
        and kind.startswith("response.")
        and isinstance(data.get("response"), dict)
    ):
        return data["response"]
    if kind == "message_start" and isinstance(data.get("message"), dict):
        return data["message"]
    return data


def _output_text(data: dict) -> str:
    """Join the ``output_text`` parts of a Responses API object's message items."""
    texts = []
    for item in data.get("output") or ():
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or ():
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
    return "".join(texts)


def _message_text(data: dict) -> str:
    """Join the ``text`` blocks of a Messages API object's ``content``."""
    texts = []
    for block in data.get("content") or ():
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "".join(texts)


def _is_completion(data: dict, choice: dict) -> bool:
    """Whether ``data`` is a ``text_completion`` (``/completions``) payload."""
    kind = data.get("object")
    if kind is not None:
        return kind == "text_completion"
    return "text" in choice and "message" not in choice and "delta" not in choice


def _chat_tool_names(message: dict) -> list[str]:
    """The names of the functions a chat message calls."""
    names = []
    for call in message.get("tool_calls") or ():
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        names.append(name if isinstance(name, str) and name else "a tool")
    return names


def _response_tool_names(data: dict) -> list[str]:
    """The tools a Responses API object calls: its ``*_call`` output items.

    A function call is named by its ``name``, a built-in tool call
    (``web_search_call`` and the like) by its type.
    """
    names = []
    for item in data.get("output") or ():
        kind = item.get("type") if isinstance(item, dict) else None
        if isinstance(kind, str) and kind.endswith("_call"):
            name = item.get("name")
            names.append(name if isinstance(name, str) and name else kind)
    return names


def _message_tool_names(data: dict) -> list[str]:
    """The tools a Messages API object calls: its ``*tool_use`` blocks.

    ``tool_use`` is a call of the caller's own tool; ``server_tool_use`` and
    the like are built-in tools. Each is named by its ``name``, else its type.
    """
    names = []
    for block in data.get("content") or ():
        kind = block.get("type") if isinstance(block, dict) else None
        if isinstance(kind, str) and kind.endswith("tool_use"):
            name = block.get("name")
            names.append(name if isinstance(name, str) and name else kind)
    return names


def _log_no_text(tools: list[str], truncated: bool, warning: str, detail: Any) -> None:
    """Log why :func:`text_of` found no text.

    A tool call is the expected answer in a tool loop, so it gets a DEBUG line
    only. Every other empty answer gets the warning, and so does a truncated
    tool call: its arguments may be cut off.
    """
    if tools and not truncated:
        log.debug("text_of: no text, the response calls %s", ", ".join(tools))
    else:
        log.warning(warning, detail)


def text_of(response: Any) -> str:
    """Extract the generated text from a chat, RAG, completion, Responses
    API or Messages API response.

    For chat and completions it reads the first choice's
    ``message.content`` (chat) or ``text`` (``text_completion``). For a
    Responses API object it joins every ``output_text`` part of every
    ``message`` item and skips reasoning, as the OpenAI SDK's
    ``Response.output_text`` does. For a Messages API object it joins every
    ``text`` block and skips ``thinking``. A response whose token budget ran
    out (``finish_reason: "length"``, ``status: "incomplete"``,
    ``stop_reason: "max_tokens"``) still gives the text so far.

    Full nil-safety: an empty ``choices`` list, a missing ``message`` key,
    a ``None`` ``content`` field or a response without output text all
    collapse to ``""`` rather than raising, and log a warning at this
    module's logger so silent regressions surface in logs. A response that
    calls a tool instead of answering also gives ``""`` but logs only at
    DEBUG, since in a tool loop that is the expected answer; the calls are
    in ``message.tool_calls`` (chat), the ``function_call`` items of
    ``output`` (Responses API) or the ``tool_use`` blocks of ``content``
    (Messages API). A truncated one (``finish_reason: "length"``,
    ``status: "incomplete"``, ``stop_reason: "max_tokens"``) keeps the
    warning, because its arguments may be cut off.

    Works for the response returned by:

    - :meth:`ChatCompletions.create <saia_python.chat.ChatCompletions.create>`
    - :meth:`ArcanaService.chat <saia_python.arcana.ArcanaService.chat>`
    - :meth:`CompletionsService.create
      <saia_python.completions.CompletionsService.create>`
    - :meth:`ResponsesService.create
      <saia_python.responses_api.ResponsesService.create>`, and a Responses
      stream's final ``response.completed`` event
    - :meth:`MessagesService.create
      <saia_python.messages.MessagesService.create>`
    - ``client.openai.chat.completions.create(...)``,
      ``client.openai.completions.create(...)`` and
      ``client.openai.responses.create(...)`` — the SDK objects directly,
      or their ``model_dump()``

    Args:
        response: A response dict, or an SDK object with ``model_dump()``.

    Returns:
        The generated text, or ``""`` if the response carries no usable
        content.

    Example::

        resp = client.arcana.chat(
            model="...", messages=[...], arcana_id="...",
        )
        answer = saia_python.text_of(resp)
    """
    data = _unwrap_event(_as_dict(response))
    if not isinstance(data, dict):
        log.warning("text_of: not a response: %s", type(response).__name__)
        return ""
    if data.get("object") == "response":
        text = _output_text(data)
        if not text:
            status = data.get("status")
            _log_no_text(
                _response_tool_names(data),
                status == "incomplete",
                "text_of: response has no output text; status=%r",
                status,
            )
        return text
    if data.get("type") == "message":
        text = _message_text(data)
        if not text:
            stop_reason = data.get("stop_reason")
            _log_no_text(
                _message_tool_names(data),
                stop_reason == "max_tokens",
                "text_of: message has no text; stop_reason=%r",
                stop_reason,
            )
        return text
    choices = data.get("choices") or []
    if not choices:
        log.warning(
            "text_of: response has no choices; keys=%s",
            list(data.keys()),
        )
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message: dict = {}
    if _is_completion(data, first):
        content = first.get("text")
    else:
        message = first.get("message") or {}
        content = message.get("content")
    if not content:
        finish_reason = first.get("finish_reason")
        _log_no_text(
            _chat_tool_names(message),
            finish_reason == "length",
            "text_of: first choice has empty content; finish_reason=%r",
            finish_reason,
        )
        return ""
    return str(content)


def _stream_error(chunk: dict) -> Any:
    """What a stream chunk reports as an error, or ``None``.

    - vLLM sends ``{"error": {"message": …, "type": …, "code": …}}`` when
      generation fails after the stream has begun; older versions send
      ``{"object": "error", "message": …}``.
    - The Responses API has an ``error`` event (``{"type": "error",
      "message": …}``) and ``response.failed``, whose response holds the
      ``error``.
    - The Messages API's ``error`` event nests it: ``{"type": "error",
      "error": {"type": …, "message": …}}``.
    """
    kind = chunk.get("type")
    if kind == "response.failed":
        response = chunk.get("response")
        error = response.get("error") if isinstance(response, dict) else None
        return error or "the response failed"
    if kind == "error":
        return chunk.get("error") or chunk
    if chunk.get("object") == "error":
        return chunk
    return chunk.get("error")


def _raise_for_stream_error(chunk: dict) -> None:
    """Raise :class:`~saia_python.APIError` when a stream chunk reports an error.

    Without this check the stream would just end and look complete.
    """
    error = _stream_error(chunk)
    if not error:
        return
    message = error.get("message") if isinstance(error, dict) else error
    raise APIError(
        f"Error inside the stream: {message or 'no message'}",
        response_body=json.dumps(chunk, default=str),
    )


def _chunk_text(chunk: Any) -> str | None:
    """The answer text one stream chunk or event adds, or ``None``."""
    data = _as_dict(chunk)
    if not isinstance(data, dict):
        return None
    _raise_for_stream_error(data)
    kind = data.get("type")
    if isinstance(kind, str):  # a typed event (Responses API, Messages API)
        delta = data.get("delta")
        if kind == "content_block_delta":  # text, thinking or tool arguments
            if not isinstance(delta, dict) or delta.get("type") != "text_delta":
                return None
            delta = delta.get("text")
        elif kind != "response.output_text.delta":
            return None
        return delta if isinstance(delta, str) else None
    for choice in data.get("choices") or ():
        if not isinstance(choice, dict) or (choice.get("index") or 0) != 0:
            continue
        delta = choice.get("delta")
        text = delta.get("content") if isinstance(delta, dict) else choice.get("text")
        return text if isinstance(text, str) else None
    return None


class _ReadState:
    """What a reading generator reports back to its iterator.

    A separate object, so the generator holds no reference to the iterator:
    with that cycle, an early ``break`` would leave the stream open until
    the garbage collector ran.
    """

    def __init__(self, references: bool, strip_separator: bool) -> None:
        self.last: Any = None
        self.references: ParsedReferences | None = None
        self.usage: dict[str, int] = {}
        self._splitter = (
            ReferencesSplitter(strip_separator=strip_separator) if references else None
        )

    def text(self, chunk: Any) -> str | None:
        """Note ``chunk`` as the last one; return the text to yield from it."""
        self.last = chunk
        data = _as_dict(chunk)
        self._note_usage(data)
        text = _chunk_text(data)
        if text and self._splitter is not None:
            return self._splitter.feed(text)
        return text

    def _note_usage(self, data: Any) -> None:
        """Merge the token counts ``data`` reports, if any, into :attr:`usage`.

        Streams report running totals, not increments, so a later count
        replaces an earlier one. A total comes only from the report that
        carries it; without one, :func:`usage_of` adds up the merged counts.
        """
        report = _usage_report(data)
        if report is None:
            return
        counts = {
            key: value
            for key, value in report.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        if counts:
            self.usage.pop("total_tokens", None)
            self.usage.update(counts)

    def finish(self) -> str:
        """The stream has ended: return held-back text, keep the references."""
        if self._splitter is None:
            return ""
        tail = self._splitter.flush()
        self.references = self._splitter.result
        return tail


def _read_text(stream: Iterable[Any], state: _ReadState) -> Generator[str, None, None]:
    """Yield the text of ``stream``'s chunks, reporting to ``state``."""
    try:
        for chunk in stream:
            text = state.text(chunk)
            if text:
                yield text
        tail = state.finish()
        if tail:
            yield tail
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


async def _aread_text(
    stream: AsyncIterable[Any], state: _ReadState
) -> AsyncGenerator[str, None]:
    """The async twin of :func:`_read_text`."""
    try:
        async for chunk in stream:
            text = state.text(chunk)
            if text:
                yield text
        tail = state.finish()
        if tail:
            yield tail
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


class TextIterator(Iterator[str]):
    """The text pieces of a stream, as :func:`iter_text` returns them.

    Iterate it as you would a generator. Along the way it keeps the token
    counts the stream reports in :attr:`usage`, the last chunk or event it
    read in :attr:`last` and, with ``references=True``, the parsed ARCANA
    references in :attr:`references`.
    """

    def __init__(
        self,
        stream: Iterable[Any],
        *,
        references: bool = False,
        strip_separator: bool = True,
    ) -> None:
        self._state = _ReadState(references, strip_separator)
        self._pieces = _read_text(stream, self._state)

    @property
    def usage(self) -> dict[str, int | None]:
        """The token counts the stream has reported so far, as
        :func:`usage_of` returns them.

        SAIA's chat, completion and Responses streams report them once, in
        their last chunk or event (seen 2026-11-20). A Messages stream
        reports them twice: the input tokens in ``message_start``, the final
        counts in ``message_delta``, which precedes its last event,
        ``message_stop`` (seen 2026-11-22). Each report gives the counts so
        far, not an increment, so a later count replaces an earlier one.
        Once the text is through, this holds the request's final counts;
        before the first report, every count is ``None``.
        """
        return usage_of({"usage": self._state.usage})

    @property
    def last(self) -> Any:
        """The last chunk or event read, as the stream gave it (a dict or an
        SDK object), or ``None`` before the first one.

        After a chat or completion stream, that is the final usage chunk;
        after a Responses stream, the ``response.completed`` event, which
        :func:`text_of` reads too; after a Messages stream, ``message_stop``,
        which carries nothing else. After an error, the chunk that reported
        it.
        """
        return self._state.last

    @property
    def references(self) -> ParsedReferences | None:
        """With ``references=True``, the ARCANA answer's References block,
        parsed, once the stream has been read to its end; else ``None``.

        It is the :class:`~saia_python.arcana_references.ParsedReferences`
        that :func:`~saia_python.arcana_references.parse_arcana_references`
        gives for the complete answer, with ``answer``, ``separator``,
        ``references``, ``anchors``, ``by_number`` and ``dangling``. The
        pieces joined give its ``answer`` (its ``prose`` with
        ``strip_separator=False``).
        """
        return self._state.references

    def __next__(self) -> str:
        return next(self._pieces)

    def close(self) -> None:
        """Stop reading and close the stream."""
        self._pieces.close()


class AsyncTextIterator(AsyncIterator[str]):
    """The text pieces of an async stream, as :func:`aiter_text` returns them.

    The async twin of :class:`TextIterator`, with the same :attr:`usage`,
    :attr:`last` and :attr:`references`.
    """

    def __init__(
        self,
        stream: AsyncIterable[Any],
        *,
        references: bool = False,
        strip_separator: bool = True,
    ) -> None:
        self._state = _ReadState(references, strip_separator)
        self._pieces = _aread_text(stream, self._state)

    @property
    def usage(self) -> dict[str, int | None]:
        """The token counts the stream has reported so far, as
        :func:`usage_of` returns them; see :attr:`TextIterator.usage`."""
        return usage_of({"usage": self._state.usage})

    @property
    def last(self) -> Any:
        """The last chunk or event read, or ``None`` before the first one."""
        return self._state.last

    @property
    def references(self) -> ParsedReferences | None:
        """With ``references=True``, the parsed References block once the
        stream has been read to its end; else ``None``."""
        return self._state.references

    async def __anext__(self) -> str:
        return await self._pieces.__anext__()

    async def aclose(self) -> None:
        """Stop reading and close the stream."""
        await self._pieces.aclose()


def iter_text(
    stream: Iterable[Any], *, references: bool = False, strip_separator: bool = True
) -> TextIterator:
    """Iterate over the text of a chat, completion, Responses or Messages
    stream.

    Accepts the native :class:`~saia_python.SSEStream` (dict chunks), an
    SDK's stream (chunk or event objects) or any iterable of chunks. From
    chat and completion streams it yields the non-empty text of the first
    choice only, so a stream with several choices (``n`` > 1, or a list of
    prompts) is not interleaved; from a Responses stream, the
    ``response.output_text.delta`` events; from a Messages stream, the
    ``text_delta`` of the ``content_block_delta`` events. Role-only chunks,
    reasoning and thinking deltas, tool-call arguments, usage chunks and
    lifecycle events are skipped. The stream is closed when iteration ends,
    also when the consumer stops early.

    Args:
        stream: The stream to read.
        references: Read the stream as an ARCANA answer: GWDG's
            ``References:`` block is held back instead of yielded, an
            anchor such as ``[RREF2]`` is never split between two pieces,
            and once the stream is through,
            :attr:`~saia_python.TextIterator.references` holds the parsed
            block. Text waits only while it could still be the start of the
            block or of an anchor (see
            :class:`~saia_python.arcana_references.ReferencesSplitter`).
        strip_separator: With ``references=True``, also leave out the
            horizontal rule GWDG puts under the answer's last line, which
            Markdown would render as a heading underline. ``False`` yields
            it too.

    Returns:
        A :class:`~saia_python.TextIterator` over the text pieces, in order;
        joined they give what :func:`text_of` reads from the complete
        response (with ``references=True``: its ``answer``, without the
        References block). Once the text is through, its
        :attr:`~saia_python.TextIterator.usage` holds the token counts.

    Raises:
        APIError: While iterating, when a chunk reports an error (an error
            chunk, an ``error`` event or ``response.failed``), which a
            server sends when generation fails after the stream has begun.
            ``response_body`` holds the chunk as JSON; ``status_code`` is
            ``None``, since the HTTP response itself succeeded.

    Example::

        stream = client.completions.create(
            model, "Once upon a time", max_tokens=64, stream=True
        )
        text = iter_text(stream)
        for piece in text:
            print(piece, end="", flush=True)
        text.usage  # the token counts, once the text is through

    A streamed ARCANA answer, without GWDG's verbose References block::

        stream = client.arcana.chat(model, messages, arcana_id, stream=True)
        text = iter_text(stream, references=True)
        for piece in text:
            print(piece, end="", flush=True)
        for ref in text.references.references:
            print(ref.n, ref.filename)
    """
    return TextIterator(stream, references=references, strip_separator=strip_separator)


def aiter_text(
    stream: AsyncIterable[Any],
    *,
    references: bool = False,
    strip_separator: bool = True,
) -> AsyncTextIterator:
    """Iterate over the text of an async chat, completion, Responses or
    Messages stream.

    The async twin of :func:`iter_text`, with the same options, for the native
    :class:`~saia_python.aio.AsyncSSEStream` or an SDK's async stream. It
    returns an :class:`~saia_python.AsyncTextIterator`, with the same
    :attr:`~saia_python.AsyncTextIterator.usage`,
    :attr:`~saia_python.AsyncTextIterator.last` and, with
    ``references=True``, :attr:`~saia_python.AsyncTextIterator.references`.
    Raises :class:`~saia_python.APIError` on an error chunk, and closes the
    stream when iteration ends.

    Example::

        stream = await aclient.completions.create(
            model, "Once upon a time", max_tokens=64, stream=True
        )
        text = aiter_text(stream)
        async for piece in text:
            print(piece, end="", flush=True)
        text.usage
    """
    return AsyncTextIterator(
        stream, references=references, strip_separator=strip_separator
    )


def _count(usage: dict, *keys: str) -> int | None:
    """The first of ``keys`` that holds an integer count, else ``None``."""
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _usage_report(data: Any) -> dict | None:
    """The ``usage`` a response, stream chunk or event carries, or ``None``."""
    data = _unwrap_event(data)
    usage = data.get("usage") if isinstance(data, dict) else None
    return usage if isinstance(usage, dict) else None


def usage_of(response: Any) -> dict[str, int | None]:
    """Return a response's token counts as one dict.

    Reads the ``usage`` of a chat, RAG, completion, Responses API or Messages
    API response (a native dict or an SDK object), or of a stream chunk or
    event that carries one: a chat or completion stream's final usage chunk,
    a Responses stream's ``response.completed`` event, a Messages stream's
    ``message_start`` or ``message_delta``. For a stream read with
    :func:`iter_text`, :attr:`TextIterator.usage
    <saia_python.TextIterator.usage>` gives the same dict without picking
    the chunk. Both spellings map onto the same keys: ``prompt_tokens`` /
    ``completion_tokens`` (chat, completions) and ``input_tokens`` /
    ``output_tokens`` (Responses and Messages API). ``total_tokens`` is
    computed when the usage leaves it out.

    Args:
        response: A response dict or stream chunk, or an SDK object with
            ``model_dump()``.

    Returns:
        ``{"input_tokens", "output_tokens", "total_tokens"}``. A count the
        response does not carry is ``None``, without a warning: most stream
        chunks carry no usage.

    Example::

        usage_of(client.completions.create(model, "Hi", max_tokens=8))
        # {'input_tokens': 1, 'output_tokens': 8, 'total_tokens': 9}
    """
    usage = _usage_report(_as_dict(response)) or {}
    input_tokens = _count(usage, "prompt_tokens", "input_tokens")
    output_tokens = _count(usage, "completion_tokens", "output_tokens")
    total_tokens = _count(usage, "total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
