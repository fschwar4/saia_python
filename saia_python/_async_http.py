"""Async HTTP plumbing — the ``httpx.AsyncClient`` twin of :mod:`saia_python._http`.

Mirrors :func:`~saia_python._http.execute` and
:func:`~saia_python._http.post_chat_completion` over ``httpx.AsyncClient``,
**reusing the pure retry brains** (:class:`~saia_python._http.RetryPolicy`,
``_plan``, ``_jitter``) and :func:`~saia_python.rate_limits.parse_rate_limits`
unchanged — so the sync and async paths can never drift on rate-limit handling.
Only the socket-touching parts (``await client.request(...)`` /
``await resp.aclose()`` / ``await asyncio.sleep(...)``) are re-implemented.

This module never imports ``httpx`` at runtime — it only *calls methods* on a
client object the caller supplies, so it stays import-safe without the
``[async]`` extra and is trivially testable with a fake client. Construct the
client via :class:`saia_python.aio.AsyncSAIAClient` (or pass your own
``httpx.AsyncClient``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ._http import RetryPolicy, _jitter, _plan
from .exceptions import raise_for_status
from .rate_limits import parse_rate_limits

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)

#: An awaitable ``sleep(seconds)`` — ``asyncio.sleep`` in production; tests pass
#: a recorder so they never actually block.
AsyncSleep = Callable[..., Awaitable[Any]]


async def aexecute(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    policy: RetryPolicy,
    idempotent: bool,
    sleep: AsyncSleep = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request under a transport policy and return the response.

    The async analogue of :func:`saia_python._http.execute`: dispatches
    ``getattr(client, method)(url, **kwargs)`` (``method`` is the lowercase verb
    — ``"post"`` / ``"get"`` — matching the sync seam) and, on HTTP 429 that the
    ``policy`` permits, waits per :func:`~saia_python._http._plan` and retries.

    Like the sync version it returns the **raw response** unchanged on success
    *or* on give-up, so the caller's
    :func:`~saia_python.exceptions.raise_for_status` still raises
    :class:`~saia_python.RateLimitError` when retry is off, the budget is spent,
    or the window must not be waited on. Only status + headers are inspected —
    never the body — so a give-up never consumes the response. Streaming is a
    separate seam (:class:`saia_python.aio.AsyncSSEStream`), because ``httpx``
    exposes a streamed body only inside ``client.stream(...)``.
    """
    attempt = 0
    while True:
        resp = await getattr(client, method)(url, **kwargs)
        if resp.status_code != 429 or not policy.applies(idempotent):
            return resp
        wait = _plan(parse_rate_limits(resp.headers), policy, attempt)
        if wait is None:
            return resp
        await resp.aclose()
        attempt += 1
        wait += _jitter(policy)
        log.info("SAIA rate limit (429) — waiting %.1fs before retry %d", wait, attempt)
        await sleep(wait)


async def apost_chat_completion(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    *,
    headers: dict | None = None,
    stream: bool = False,
    policy: RetryPolicy | None = None,
    sleep: AsyncSleep = asyncio.sleep,
) -> dict | Any:
    """POST a chat-completion request and normalise the response (async).

    The async twin of :func:`saia_python._http.post_chat_completion`. For
    ``stream=False`` it returns the response dict with an extra
    ``"_rate_limits"`` key; for ``stream=True`` it returns a connected
    :class:`~saia_python.aio.AsyncSSEStream` (imported lazily to avoid a cycle),
    with the initial-429 retry already applied *before* the stream is exposed —
    never mid-stream, exactly like the sync path.
    """
    policy = policy if policy is not None else RetryPolicy()
    if stream:
        from ._async_streaming import AsyncSSEStream

        stream_body = {**body, "stream": True}
        stream_headers = {**(headers or {}), "Accept": "text/event-stream"}
        return await AsyncSSEStream.open(
            client,
            url,
            json=stream_body,
            headers=stream_headers,
            policy=policy,
            sleep=sleep,
        )

    resp = await aexecute(
        client,
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
