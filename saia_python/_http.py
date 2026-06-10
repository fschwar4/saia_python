"""Shared HTTP plumbing used by more than one service.

Kept in one place so the chat-completion request shape and the
background-thread ``Session`` helper each have a single implementation,
rather than being copied across :mod:`saia_python.chat`,
:mod:`saia_python.arcana`, and :mod:`saia_python.voice`.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from ._streaming import SSEStream
from .exceptions import raise_for_status
from .rate_limits import RateLimitInfo, parse_rate_limits

log = logging.getLogger(__name__)

# Default ``(connect, read)`` timeout in seconds for ARCANA management
# ("control-plane") requests that do not pass their own. A plain
# :class:`requests.Session` has NO default timeout, so a request the server
# accepts but never answers — common while an arcana is locked mid-(re)index —
# blocks forever on the socket read. Long-running "data-plane" calls (chat
# completions, voice transcription, document conversion) deliberately do not
# inherit this cap, since they can legitimately run for minutes.
DEFAULT_TIMEOUT: tuple[float, float] = (10.0, 60.0)


@dataclass
class RetryPolicy:
    """Transport-layer policy for HTTP 429 (rate-limit) responses.

    Applied at the session dispatch seam (:func:`execute`); ON by default and
    scoped to idempotent calls. See ``docs/proposals/rate-limit-handling.md``.

    Attributes:
        on_rate_limit: Master switch. When ``False`` a 429 is never retried —
            it propagates as :class:`~saia_python.RateLimitError`, i.e. today's
            behavior.
        max_retries: Maximum reset-driven retries (the minute window).
        max_waiting_time: The longest a single wait may block, in seconds
            (default 60). A reset further out than this fails fast (raises)
            rather than blocking; settable per client.
        fallback_wait: Seconds to wait when the server sends no reset hint.
        fallback_max_retries: How many times the blind fallback is tried.
        jitter: ``(low, high)`` seconds added to each wait to avoid a
            thundering herd across concurrent workers; ``(0, 0)`` disables it.
        retry_mutations: If ``True``, non-idempotent calls are retried too
            (off by default — replaying a mutation is unsafe in general).
    """

    on_rate_limit: bool = True
    max_retries: int = 5
    max_waiting_time: float = 60.0
    fallback_wait: float = 31.0
    fallback_max_retries: int = 2
    jitter: tuple[float, float] = (0.0, 2.0)
    retry_mutations: bool = False

    def applies(self, idempotent: bool) -> bool:
        """Whether a 429 on a call with this idempotency is eligible for retry."""
        return self.on_rate_limit and (idempotent or self.retry_mutations)


def coerce_retry(retry: RetryPolicy | bool | None) -> RetryPolicy:
    """Normalise a ``retry`` argument into a :class:`RetryPolicy`.

    A :class:`RetryPolicy` is returned unchanged; ``False`` disables retry;
    ``None`` / ``True`` give the defaults (retry on).
    """
    if isinstance(retry, RetryPolicy):
        return retry
    if retry is False:
        return RetryPolicy(on_rate_limit=False)
    return RetryPolicy()


def resolve_retry(
    default: RetryPolicy, override: RetryPolicy | bool | None
) -> RetryPolicy:
    """Pick the policy for one call: the per-call ``override`` when given, else
    the service ``default``. ``None`` means "use the default"."""
    return default if override is None else coerce_retry(override)


def _jitter(policy: RetryPolicy) -> float:
    low, high = policy.jitter
    return random.uniform(low, high) if high > low else low


def _plan(info: RateLimitInfo, policy: RetryPolicy, attempt: int) -> float | None:
    """Seconds to wait before the next attempt, or ``None`` to give up (→ raise).

    Honest about the single ``reset_seconds`` spanning four windows: we wait out
    the window we can time (the minute), but fail fast on a longer window whose
    reset is unknowable — we will not block for ~an hour inside a call.
    """
    # A longer window is exhausted → its reset is not the (minute) reset_seconds.
    for window in ("hour", "day", "month"):
        if getattr(info, f"remaining_{window}") == 0:
            return None
    reset = info.reset_seconds
    if isinstance(reset, (int, float)) and reset > 0:
        if reset > policy.max_waiting_time:
            return None
        return None if attempt >= policy.max_retries else float(reset) + 1.0
    # No usable reset hint → conservative, bounded blind fallback.
    return None if attempt >= policy.fallback_max_retries else policy.fallback_wait


def execute(
    session: requests.Session,
    method: str,
    url: str,
    *,
    policy: RetryPolicy,
    idempotent: bool,
    sleep: Callable[[float], object] = time.sleep,
    **kwargs,
) -> requests.Response:
    """Issue a request under a transport policy and return the response.

    Dispatches ``getattr(session, method)(url, **kwargs)`` (``method`` is the
    lowercase verb, matching the rest of the package). On HTTP 429 — when
    ``policy`` permits (enabled, and the call is idempotent or
    ``retry_mutations``) — it waits per :func:`_plan` and retries. It returns the
    **raw response** unchanged on success *or* on give-up, so the caller's
    :func:`~saia_python.exceptions.raise_for_status` still raises
    :class:`~saia_python.RateLimitError` when retry is off, the budget is spent,
    or the window must not be waited on.

    Only the status code and headers are inspected — never the body — so
    streaming and non-streaming requests behave identically and a streamed body
    is never consumed. The (possibly streamed) connection is released with
    ``close()`` before each wait.

    Note:
        A retry re-issues the request with the **same** ``kwargs``, so any file
        payload must be retry-safe (``bytes``, not a one-shot file handle). The
        file-upload callers (voice, documents) pass ``bytes``.
    """
    attempt = 0
    while True:
        resp = getattr(session, method)(url, **kwargs)
        if resp.status_code != 429 or not policy.applies(idempotent):
            return resp
        wait = _plan(parse_rate_limits(resp.headers), policy, attempt)
        if wait is None:
            return resp
        resp.close()
        attempt += 1
        wait += _jitter(policy)
        log.info("SAIA rate limit (429) — waiting %.1fs before retry %d", wait, attempt)
        sleep(wait)


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
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], object] = time.sleep,
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
        policy: Rate-limit :class:`RetryPolicy`; ``None`` uses the defaults
            (retry on). Chat completions are idempotent, so an initial 429 is
            retried per the policy — and for streaming the retry happens *before*
            the stream is exposed (never mid-stream).
        sleep: Injectable sleep hook (tests pass a recorder so they never block).

    Returns:
        When ``stream=False``: the response dict with an extra
        ``"_rate_limits"`` key (a JSON-serializable dict). When ``stream=True``:
        an :class:`SSEStream` whose ``rate_limits`` attribute holds the same dict.
    """
    policy = policy if policy is not None else RetryPolicy()
    if stream:
        stream_body = {**body, "stream": True}
        stream_headers = {**(headers or {}), "Accept": "text/event-stream"}
        resp = execute(
            session,
            "post",
            url,
            policy=policy,
            idempotent=True,
            sleep=sleep,
            json=stream_body,
            headers=stream_headers,
            stream=True,
        )
        return SSEStream(resp)

    resp = execute(
        session,
        "post",
        url,
        policy=policy,
        idempotent=True,
        sleep=sleep,
        json=body,
        headers=headers,
    )
    raise_for_status(resp)
    result = resp.json()
    result["_rate_limits"] = parse_rate_limits(resp.headers).to_dict()
    return result
