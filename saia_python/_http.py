"""Shared HTTP plumbing used by more than one service.

Kept in one place so the chat-completion request shape and the
background-thread ``Session`` helper each have a single implementation,
rather than being copied across :mod:`saia_python.chat`,
:mod:`saia_python.arcana`, and :mod:`saia_python.voice`.
"""

from __future__ import annotations

import requests

from ._streaming import SSEStream
from .exceptions import raise_for_status
from .rate_limits import parse_rate_limits

# Default ``(connect, read)`` timeout in seconds for ARCANA management
# ("control-plane") requests that do not pass their own. A plain
# :class:`requests.Session` has NO default timeout, so a request the server
# accepts but never answers — common while an arcana is locked mid-(re)index —
# blocks forever on the socket read. Long-running "data-plane" calls (chat
# completions, voice transcription, document conversion) deliberately do not
# inherit this cap, since they can legitimately run for minutes.
DEFAULT_TIMEOUT: tuple[float, float] = (10.0, 60.0)


def new_session_like(template: requests.Session) -> requests.Session:
    """Return a fresh :class:`requests.Session` mirroring ``template``'s headers.

    Background-thread work must not reuse the caller's ``Session`` —
    ``requests.Session`` is not guaranteed thread-safe, and sharing its
    connection pool across threads can corrupt in-flight requests. Both the
    non-blocking Voice path and the fire-and-forget ARCANA index trigger spin
    up their own ``Session`` through this helper so they never race the
    client's.
    """
    session = requests.Session()
    session.headers.update(template.headers)
    return session


def post_chat_completion(
    session: requests.Session,
    url: str,
    body: dict,
    *,
    headers: dict | None = None,
    stream: bool = False,
) -> dict | SSEStream:
    """POST a chat-completion request and normalise the response.

    Shared by :meth:`ChatService.completions` and :meth:`ArcanaService.chat`:
    both hit the same ``/chat/completions`` endpoint with identical
    stream/non-stream handling and rate-limit surfacing — only the request
    ``body`` fields and auth ``headers`` differ, so those stay with the caller.

    Args:
        session: The authenticated :class:`requests.Session`.
        url: The fully-qualified ``/chat/completions`` URL.
        body: The request JSON body (already assembled by the caller).
        headers: Per-request headers. ``None`` uses the session defaults
            (the Bearer auth + ``Accept: application/json``).
        stream: When ``True``, request SSE and return an :class:`SSEStream`.

    Returns:
        When ``stream=False``: the response dict with an extra
        ``"_rate_limits"`` key (a JSON-serializable dict). When ``stream=True``:
        an :class:`SSEStream` whose ``rate_limits`` attribute holds the same dict.
    """
    if stream:
        stream_body = {**body, "stream": True}
        stream_headers = {**(headers or {}), "Accept": "text/event-stream"}
        resp = session.post(url, json=stream_body, headers=stream_headers, stream=True)
        return SSEStream(resp)

    resp = session.post(url, json=body, headers=headers)
    raise_for_status(resp)
    result = resp.json()
    result["_rate_limits"] = parse_rate_limits(resp.headers).to_dict()
    return result
