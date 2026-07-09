"""Custom exceptions and shared HTTP error handling for the SAIA Python wrapper.

:func:`raise_for_status` is transport-agnostic: it inspects only ``status_code``,
``headers``, ``json()`` and ``text`` — the attributes ``requests.Response`` and
``httpx.Response`` share — so the sync and async paths raise the *same* typed
errors. Every error now carries ``status_code`` + ``response_body`` (so a gateway
can reframe the upstream response faithfully), and a 429 carries both the parsed
``rate_limits`` and an informative message (which window, when it resets, how to
auto-retry).
"""

from __future__ import annotations

import json as _json
from typing import Any

from .rate_limits import format_rate_limit_error, parse_rate_limits


class SAIAError(Exception):
    """Base exception for all SAIA API errors.

    Args:
        message: Human-readable error message.
        status_code: The upstream HTTP status, when the error came from a
            response (``None`` for client-side errors).
        response_body: The raw upstream body, preserved so a caller can surface
            exactly what the server sent.
    """

    def __init__(
        self,
        message: object,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AuthenticationError(SAIAError):
    """Raised on 401/403 responses — invalid or missing API key."""


class RateLimitError(SAIAError):
    """Raised on 429 responses — rate limit exceeded.

    Carries :attr:`rate_limits` (the parsed :class:`~saia_python.RateLimitInfo`)
    and, when raised by :func:`raise_for_status`, an informative message built
    by :func:`~saia_python.rate_limits.format_rate_limit_error`.
    """

    def __init__(
        self,
        message: object,
        rate_limits: object = None,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.rate_limits = rate_limits


class APIError(SAIAError):
    """Raised on unexpected HTTP errors."""

    def __init__(
        self,
        message: object,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(message, status_code=status_code, response_body=response_body)


def _extract_detail(resp: Any) -> str:
    """Try to extract a human-readable message from a JSON error body.

    The SAIA API typically returns ``{"detail": "..."}`` on errors.
    Falls back to the raw response text. Works with any response exposing
    ``json()`` / ``text`` (``requests`` or ``httpx``).
    """
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return body["detail"]
    except (_json.JSONDecodeError, ValueError):
        pass
    return resp.text


def raise_for_status(resp: Any) -> None:
    """Raise a typed SAIA exception for HTTP error responses.

    The single implementation shared by every service, sync and async. Accepts
    a ``requests.Response`` (which has ``.ok``) or an ``httpx.Response`` (which
    does not — success is decided from ``status_code`` instead). For a streamed
    response the body must already be read (``await resp.aread()``) first.
    """
    ok = getattr(resp, "ok", None)
    if ok is None:
        ok = resp.status_code < 400
    if ok:
        return
    detail = _extract_detail(resp)
    body = resp.text
    if resp.status_code in (401, 403):
        raise AuthenticationError(
            detail, status_code=resp.status_code, response_body=body
        )
    if resp.status_code == 429:
        info = parse_rate_limits(resp.headers)
        raise RateLimitError(
            format_rate_limit_error(info, detail),
            rate_limits=info,
            status_code=resp.status_code,
            response_body=body,
        )
    # Any other non-2xx/3xx status. The early `return` above already handled
    # the success case, so reaching here always means an error response.
    raise APIError(detail, status_code=resp.status_code, response_body=body)
