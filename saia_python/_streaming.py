"""Shared SSE (Server-Sent Events) streaming iterator."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Generator

from .exceptions import raise_for_status

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
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue
