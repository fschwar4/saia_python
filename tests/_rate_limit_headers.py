"""Rate-limit headers as SAIA sends them, shared by the tests.

``CURRENT_OK`` and ``CURRENT_429`` (plus its body) were recorded from the live
gateway on 2026-11-19. ``LEGACY_OK`` is the earlier (Kong) scheme, which the
parser still supports. Tests of the normal path use the current scheme, so a
renamed header shows up as a failing test rather than as silently empty limits.
"""

from __future__ import annotations

#: A successful (or 400-probe) response: 10 per 10 s, 400 per hour, 800 per day.
CURRENT_OK = {
    "x-ratelimit-limit-requests-10s": "10",
    "x-ratelimit-remaining-requests-10s": "9",
    "x-ratelimit-reset-requests-10s": "18",
    "x-ratelimit-limit-requests-hour": "400",
    "x-ratelimit-remaining-requests-hour": "398",
    "x-ratelimit-reset-requests-hour": "6328",
    "x-ratelimit-limit-requests-day": "800",
    "x-ratelimit-remaining-requests-day": "750",
    "x-ratelimit-reset-requests-day": "27928",
}

#: The 429 after ten requests within one 10-second window.
CURRENT_429 = {
    "retry-after": "9",
    "x-should-retry": "true",
    "x-ratelimit-limit-requests-10s": "10",
    "x-ratelimit-remaining-requests-10s": "0",
    "x-ratelimit-reset-requests-10s": "19",
    "x-ratelimit-limit-requests-hour": "400",
    "x-ratelimit-remaining-requests-hour": "387",
    "x-ratelimit-reset-requests-hour": "6269",
    "x-ratelimit-limit-requests-day": "800",
    "x-ratelimit-remaining-requests-day": "739",
    "x-ratelimit-reset-requests-day": "27869",
    "x-ratelimit-scope": "user",
}

CURRENT_429_MESSAGE = (
    "Rate limit exceeded: user 10s request limit reached (10 of 10). "
    "Retry after 9 seconds."
)

#: The JSON body of that 429.
CURRENT_429_BODY = {
    "error": {
        "message": CURRENT_429_MESSAGE,
        "type": "rate_limit_exceeded",
        "param": None,
        "code": "rate_limit_exceeded",
    }
}

#: The earlier scheme: a single reset for the shortest (minute) window.
LEGACY_OK = {
    "x-ratelimit-limit-minute": "30",
    "x-ratelimit-remaining-minute": "29",
}
