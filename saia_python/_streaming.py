"""Shared SSE (Server-Sent Events) streaming iterator."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import TYPE_CHECKING

from .exceptions import raise_for_status
from .rate_limits import parse_rate_limits

if TYPE_CHECKING:
    import requests


def iter_sse(response: requests.Response) -> Generator[dict, None, None]:
    """Yield parsed JSON chunks from an SSE stream.

    Handles the ``data: {...}`` / ``data: [DONE]`` protocol used by
    the OpenAI-compatible SAIA API.

    Args:
        response: A streaming :class:`requests.Response` (``stream=True``).

    Yields:
        Parsed JSON dicts for each ``data:`` line.
    """
    raise_for_status(response)
    try:
        for raw in response.iter_lines(decode_unicode=True):
            # decode_unicode=True yields str at runtime, but the requests type
            # stub still types iter_lines as bytes — normalize for both.
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue
    finally:
        # Release the underlying connection back to the pool whether the
        # stream finished, hit [DONE], errored, or the consumer broke early
        # (GeneratorExit). Without this, an abandoned stream leaks the socket
        # until garbage collection.
        response.close()


class SSEStream:
    """Iterable over SSE chunks that also exposes parsed rate-limit info.

    Wraps a streaming :class:`requests.Response` so callers can both iterate
    the decoded chunks (``for chunk in stream``) and read the rate-limit
    headers via :attr:`rate_limits` — available immediately, since headers
    arrive before the streamed body. Mirrors the ``_rate_limits`` key that
    non-streaming responses carry, giving both paths rate-limit parity.

    Attributes:
        rate_limits: A JSON-serializable dict of this response's rate-limit
            headers (the same shape as :class:`~saia_python.RateLimitInfo`
            via ``to_dict()``).
    """

    def __init__(self, response: requests.Response):
        self._response = response
        self.rate_limits: dict = parse_rate_limits(response.headers).to_dict()
        self._chunks = iter_sse(response)

    def __iter__(self) -> SSEStream:
        return self

    def __next__(self) -> dict:
        return next(self._chunks)

    def close(self) -> None:
        """Close the stream, releasing the underlying connection.

        Closes both the chunk generator (running its cleanup) and the
        response directly, so the connection is released even if iteration
        never started.
        """
        self._chunks.close()
        self._response.close()

    def __enter__(self) -> SSEStream:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
