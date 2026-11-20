"""Helpers for reading generation responses and streams.

They read what the native services return (plain dicts, and streams of dict
chunks) and the OpenAI SDK's objects alike: anything with ``model_dump()`` is
dumped to a dict first. The shapes understood so far:

- ``chat.completion`` from ``/chat/completions`` (chat and ARCANA RAG): the
  text is ``choices[0].message.content``, a stream chunk's
  ``choices[0].delta.content``.
- ``text_completion`` from ``/completions``: the text is ``choices[0].text``,
  in a stream chunk too.

Every caller would otherwise write the same lookup chain. The helpers make it
safe and uniform: empty ``choices`` lists and missing ``content`` fields
return ``""`` (with a logged warning) so downstream string-handling code
doesn't have to special-case them.

Despite the module name, this is **not** a wrapper for OpenAI's Responses API.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any

from .exceptions import APIError

log = logging.getLogger(__name__)


def _as_dict(obj: Any) -> Any:
    """Return ``obj`` as plain data: SDK objects (pydantic models) are dumped."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    return dump() if callable(dump) else obj


def _is_completion(data: dict, choice: dict) -> bool:
    """Whether ``data`` is a ``text_completion`` (``/completions``) payload."""
    kind = data.get("object")
    if kind is not None:
        return kind == "text_completion"
    return "text" in choice and "message" not in choice and "delta" not in choice


def text_of(response: Any) -> str:
    """Extract the generated text from a chat, RAG or completion response.

    Reads ``choices[0].message.content`` (chat) or ``choices[0].text``
    (``text_completion``) with full nil-safety: an empty ``choices`` list,
    a missing ``message`` key, or a ``None`` ``content`` field all collapse
    to ``""`` rather than raising. Both empty-response cases log a warning
    at this module's logger so silent regressions surface in logs.

    Works for the response returned by:

    - :meth:`ChatService.completions <saia_python.chat.ChatService.completions>`
    - :meth:`ArcanaService.chat <saia_python.arcana.ArcanaService.chat>`
    - :meth:`CompletionsService.create
      <saia_python.completions.CompletionsService.create>`
    - ``client.openai.chat.completions.create(...)`` and
      ``client.openai.completions.create(...)`` — the SDK objects directly,
      or their ``model_dump()``

    Args:
        response: A response dict, or an SDK object with ``model_dump()``.

    Returns:
        The first choice's text, or ``""`` if the response carries no
        usable content.

    Example::

        resp = client.arcana.chat(
            model="...", messages=[...], arcana_id="...",
        )
        answer = saia_python.text_of(resp)
    """
    data = _as_dict(response)
    if not isinstance(data, dict):
        log.warning("text_of: not a response: %s", type(response).__name__)
        return ""
    choices = data.get("choices") or []
    if not choices:
        log.warning(
            "text_of: response has no choices; keys=%s",
            list(data.keys()),
        )
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    if _is_completion(data, first):
        content = first.get("text")
    else:
        message = first.get("message") or {}
        content = message.get("content")
    if not content:
        log.warning(
            "text_of: first choice has empty content; finish_reason=%r",
            first.get("finish_reason"),
        )
        return ""
    return str(content)


def _raise_for_stream_error(chunk: dict) -> None:
    """Raise :class:`~saia_python.APIError` when a stream chunk reports an error.

    vLLM sends ``{"error": {"message": …, "type": …, "code": …}}`` when
    generation fails after the stream has begun (older versions send
    ``{"object": "error", "message": …}``). Without this check the stream
    would just end and look complete.
    """
    error = chunk.get("error")
    if error is None and chunk.get("object") == "error":
        error = chunk
    if not error:
        return
    message = error.get("message") if isinstance(error, dict) else error
    raise APIError(
        f"Error inside the stream: {message or 'no message'}",
        response_body=json.dumps(chunk, default=str),
    )


def _chunk_text(chunk: Any) -> str | None:
    """The text a stream chunk adds to the first choice, or ``None``."""
    data = _as_dict(chunk)
    if not isinstance(data, dict):
        return None
    _raise_for_stream_error(data)
    for choice in data.get("choices") or ():
        if not isinstance(choice, dict) or (choice.get("index") or 0) != 0:
            continue
        delta = choice.get("delta")
        text = delta.get("content") if isinstance(delta, dict) else choice.get("text")
        return text if isinstance(text, str) else None
    return None


def iter_text(stream: Iterable[Any]) -> Iterator[str]:
    """Yield the text deltas of a chat or completion stream.

    Accepts the native :class:`~saia_python.SSEStream` (dict chunks), the
    OpenAI SDK's stream (chunk objects) or any iterable of chunks. Yields the
    non-empty text of the first choice only, so a stream with several choices
    (``n`` > 1, or a list of prompts) is not interleaved. Role-only chunks,
    reasoning deltas and the final usage chunk are skipped. The stream is
    closed when iteration ends, also when the consumer stops early.

    Args:
        stream: The stream to read.

    Yields:
        Text pieces, in order; joined they give the first choice's text.

    Raises:
        APIError: A chunk reports an error, which a server sends when
            generation fails after the stream has begun. ``response_body``
            holds the chunk as JSON; ``status_code`` is ``None``, since the
            HTTP response itself succeeded.

    Example::

        stream = client.completions.create(
            model, "Once upon a time", max_tokens=64, stream=True
        )
        for piece in iter_text(stream):
            print(piece, end="", flush=True)
    """
    try:
        for chunk in stream:
            text = _chunk_text(chunk)
            if text:
                yield text
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


async def aiter_text(stream: AsyncIterable[Any]) -> AsyncIterator[str]:
    """Yield the text deltas of an async chat or completion stream.

    The async twin of :func:`iter_text`, for the native
    :class:`~saia_python.aio.AsyncSSEStream` or the OpenAI SDK's async
    stream. Raises :class:`~saia_python.APIError` on an error chunk, and
    closes the stream when iteration ends.

    Example::

        stream = await aclient.completions.create(
            model, "Once upon a time", max_tokens=64, stream=True
        )
        async for piece in aiter_text(stream):
            print(piece, end="", flush=True)
    """
    try:
        async for chunk in stream:
            text = _chunk_text(chunk)
            if text:
                yield text
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


def _count(usage: dict, *keys: str) -> int | None:
    """The first of ``keys`` that holds an integer count, else ``None``."""
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def usage_of(response: Any) -> dict[str, int | None]:
    """Return a response's token counts as one dict.

    Reads the ``usage`` of a chat, RAG or completion response (a native dict
    or an SDK object), or of a stream's final usage chunk. Both spellings
    map onto the same keys: ``prompt_tokens`` / ``completion_tokens`` (chat,
    completions) and ``input_tokens`` / ``output_tokens``. ``total_tokens`` is
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
    data = _as_dict(response)
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        usage = {}
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
