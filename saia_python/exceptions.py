"""Custom exceptions and shared HTTP error handling for the SAIA Python wrapper."""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests


class SAIAError(Exception):
    """Base exception for all SAIA API errors."""


class AuthenticationError(SAIAError):
    """Raised on 401/403 responses — invalid or missing API key."""


class RateLimitError(SAIAError):
    """Raised on 429 responses — rate limit exceeded."""

    def __init__(self, message, rate_limits=None):
        super().__init__(message)
        self.rate_limits = rate_limits


class APIError(SAIAError):
    """Raised on unexpected HTTP errors."""

    def __init__(self, message, status_code=None, response_body=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def _extract_detail(resp: requests.Response) -> str:
    """Try to extract a human-readable message from a JSON error body.

    The SAIA API typically returns ``{"detail": "..."}`` on errors.
    Falls back to the raw response text.
    """
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return body["detail"]
    except (_json.JSONDecodeError, ValueError):
        pass
    return resp.text


def raise_for_status(resp: requests.Response) -> None:
    """Raise a typed SAIA exception for HTTP error responses.

    Called by all service modules — this is the single implementation.
    """
    if resp.ok:
        return
    detail = _extract_detail(resp)
    if resp.status_code in (401, 403):
        raise AuthenticationError(detail)
    if resp.status_code == 429:
        from .rate_limits import parse_rate_limits

        raise RateLimitError(detail, rate_limits=parse_rate_limits(resp.headers))
    if not resp.ok:
        raise APIError(detail, status_code=resp.status_code, response_body=resp.text)
