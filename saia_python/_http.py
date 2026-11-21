"""Shared HTTP plumbing used by more than one service.

Kept in one place so the generation request (chat, ARCANA chat, raw-text
completions, Responses API), the 429 retry policy and the background-thread
``Session`` helper each have a single implementation, rather than being copied
across :mod:`saia_python.chat`, :mod:`saia_python.arcana`,
:mod:`saia_python.completions`, :mod:`saia_python.responses_api` and
:mod:`saia_python.voice`.
"""

from __future__ import annotations

import logging
import math
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
        max_retries: Maximum retries that follow a server hint
            (``Retry-After`` or a window's reset).
        max_waiting_time: The longest a single wait may block, in seconds
            (default 60). A hint further out than this fails fast (raises)
            rather than blocking; settable per client.
        fallback_wait: Seconds to wait when the server sends no usable hint.
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


#: Windows longer than a minute. The earlier header scheme timed only the
#: shortest window, so when one of these ran out its reset was unknowable.
_LONG_WINDOWS = frozenset({"hour", "day", "month"})


def _server_wait(info: RateLimitInfo) -> float | None:
    """How long the 429's headers say to wait, in seconds.

    In order of trust:

    1. ``Retry-After``: the server's own answer for whichever window is
       binding.
    2. The resets of the exhausted windows (current scheme). Waiting for the
       latest one is safe; on a sliding window it overstates the wait, because
       a window's reset is when it is fully clear.
    3. The earlier scheme's single reset, which times only the shortest window.
       When a longer window ran out instead, the wait cannot be timed:
       ``math.inf``, so the caller gives up.

    Returns ``None`` when the headers hold no usable hint.
    """
    if info.retry_after is not None and info.retry_after >= 0:
        return float(info.retry_after)
    exhausted = info.exhausted_windows()
    if exhausted:
        resets = [getattr(info, f"reset_{w}") for w in exhausted]
        known = [r for r in resets if isinstance(r, int) and r > 0]
        if len(known) == len(resets):
            return float(max(known)) + 1.0
        if _LONG_WINDOWS.intersection(exhausted):
            return math.inf
    reset = info.reset_seconds
    if isinstance(reset, int) and reset > 0:
        return float(reset) + 1.0
    return None


def _plan(info: RateLimitInfo, policy: RetryPolicy, attempt: int) -> float | None:
    """Seconds to wait before the next attempt, or ``None`` to give up (→ raise).

    Waits as long as the headers say (:func:`_server_wait`) but gives up when
    that is longer than ``policy.max_waiting_time`` or the retries are spent —
    we will not block for ~an hour inside a call. Without any hint it falls
    back to a bounded blind wait.
    """
    wait = _server_wait(info)
    if wait is None:
        # No usable hint → conservative, bounded blind fallback.
        return None if attempt >= policy.fallback_max_retries else policy.fallback_wait
    if wait > policy.max_waiting_time or attempt >= policy.max_retries:
        return None
    return wait


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


def post_generation(
    session: requests.Session,
    url: str,
    body: dict,
    *,
    headers: dict | None = None,
    stream: bool = False,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> dict | SSEStream:
    """POST a generation request and normalise the response.

    The one transport for every route that generates text:
    ``/chat/completions`` (:meth:`ChatService.completions
    <saia_python.chat.ChatService.completions>` and :meth:`ArcanaService.chat
    <saia_python.arcana.ArcanaService.chat>`), ``/completions``
    (:meth:`CompletionsService.create
    <saia_python.completions.CompletionsService.create>`) and ``/responses``
    (:meth:`ResponsesService.create
    <saia_python.responses_api.ResponsesService.create>`). They share the
    stream/non-stream handling, the 429 retry and the rate-limit surfacing; the
    URL, the ``body`` fields and the auth ``headers`` stay with the caller.

    Args:
        session: The authenticated :class:`requests.Session`.
        url: The fully-qualified route URL.
        body: The request JSON body (already assembled by the caller).
        headers: Per-request headers. ``None`` uses the session defaults
            (the Bearer auth + ``Accept: application/json``).
        stream: When ``True``, request SSE and return an :class:`SSEStream`.
        policy: Rate-limit :class:`RetryPolicy`; ``None`` uses the defaults
            (retry on). A 429 means nothing was generated, so the call counts
            as idempotent and an initial 429 is retried per the policy — and
            for streaming the retry happens *before* the stream is exposed
            (never mid-stream).
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


#: The earlier, chat-specific name of :func:`post_generation`, kept as an alias.
post_chat_completion = post_generation
