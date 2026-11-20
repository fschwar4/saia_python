"""Rate-limit header parsing for SAIA API responses.

SAIA has sent two header schemes. Both are parsed, so a response of either kind
fills :class:`RateLimitInfo`:

* **Current scheme** (seen since 2026-11-19): one limit, remaining count and
  reset per window, plus ``Retry-After`` on a 429::

      x-ratelimit-{limit,remaining,reset}-requests-{10s,hour,day}

  The windows appear to slide. A window's reset is when its count is back to
  the full limit, which can be up to twice the window length away;
  ``Retry-After`` says when the next request is admitted, which is usually
  sooner.
* **Earlier scheme** (Kong): limit and remaining count per window, and a single
  reset that times only the shortest window::

      x-ratelimit-{limit,remaining}-{minute,hour,day,month}
      ratelimit-reset

The headers come only on requests that name a served model (see
:meth:`~saia_python.SAIAClient.get_rate_limits`).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

#: The window names, shortest first. ``10s`` comes from the current scheme,
#: ``minute`` and ``month`` from the earlier one, ``hour`` and ``day`` from both.
WINDOWS = ("10s", "minute", "hour", "day", "month")


@dataclass
class RateLimitInfo:
    """Parsed rate-limit information from SAIA API response headers.

    Every window in :data:`WINDOWS` has three fields: ``limit_<window>``,
    ``remaining_<window>`` and ``reset_<window>`` (seconds), e.g.
    ``remaining_10s``. A field is ``None`` when the server did not send it, so
    which ones are filled depends on the header scheme (see the module docs).

    Attributes:
        reset_seconds: The single reset of the earlier scheme
            (``ratelimit-reset``), in seconds.
        retry_after: ``Retry-After`` in seconds, sent with a 429: how long to
            wait until the next request is admitted.
    """

    limit_minute: int | None = None
    limit_hour: int | None = None
    limit_day: int | None = None
    limit_month: int | None = None
    remaining_minute: int | None = None
    remaining_hour: int | None = None
    remaining_day: int | None = None
    remaining_month: int | None = None
    reset_seconds: int | None = None
    # Added for the current scheme. Appended, so positional construction and
    # the key order of to_dict() stay as they were.
    limit_10s: int | None = None
    remaining_10s: int | None = None
    reset_10s: int | None = None
    reset_minute: int | None = None
    reset_hour: int | None = None
    reset_day: int | None = None
    reset_month: int | None = None
    retry_after: int | None = None

    def to_dict(self) -> dict:
        """Return a plain, JSON-serializable dict of all rate-limit fields."""
        return asdict(self)

    def exhausted_windows(self) -> list[str]:
        """Names of the windows with nothing remaining, shortest first."""
        return [w for w in WINDOWS if getattr(self, f"remaining_{w}") == 0]

    def __str__(self):
        rows = []
        for window in WINDOWS:
            limit = getattr(self, f"limit_{window}")
            if limit is None:
                continue
            remaining = getattr(self, f"remaining_{window}")
            reset = getattr(self, f"reset_{window}")
            rows.append(
                (
                    window,
                    str(remaining) if remaining is not None else "?",
                    limit,
                    str(limit - remaining) if remaining is not None else "?",
                    f"  resets in {_duration(reset)}" if reset is not None else "",
                )
            )

        if not rows:
            return "SAIA Rate Limits: (no data)"

        w_win = max(len(r[0]) for r in rows)
        w_rem = max(len(r[1]) for r in rows)
        w_lim = max(len(str(r[2])) for r in rows)
        w_used = max(len(r[3]) for r in rows)

        lines = ["SAIA Rate Limits:"]
        for window, remaining, limit, used, reset in rows:
            lines.append(
                f"  {window:<{w_win}}  "
                f"{remaining:>{w_rem}} / {limit:>{w_lim}}  "
                f"remaining  "
                f"({used:>{w_used}} used){reset}"
            )
        if self.reset_seconds is not None:
            lines.append(f"  Resets in {self.reset_seconds}s")
        if self.retry_after is not None:
            lines.append(f"  Retry after {_duration(self.retry_after)}")
        return "\n".join(lines)


def _duration(seconds: int) -> str:
    """Render seconds as ``45s``, ``12m 5s`` or ``7h 44m``."""
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _header_map() -> dict[str, str]:
    """Map every known header name to its :class:`RateLimitInfo` field.

    The earlier scheme comes first, so where both name the same field the
    current scheme wins.
    """
    mapping = {
        f"x-ratelimit-{kind}-{window}": f"{kind}_{window}"
        for window in WINDOWS
        for kind in ("limit", "remaining")
    }
    mapping["ratelimit-reset"] = "reset_seconds"
    mapping.update(
        {
            f"x-ratelimit-{kind}-requests-{window}": f"{kind}_{window}"
            for window in WINDOWS
            for kind in ("limit", "remaining", "reset")
        }
    )
    return mapping


_HEADER_MAP = _header_map()


def _parse_retry_after(value: object, date: object = None) -> int | None:
    """Seconds from a ``Retry-After`` value: delay-seconds or an HTTP-date.

    An HTTP-date is measured from the response's ``Date`` header when there is
    one, else from the local clock. Rounds up and never returns less than 0.
    """
    if value is None:
        return None
    text = str(value).strip()
    try:
        return max(0, math.ceil(float(text)))
    except (ValueError, OverflowError):
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    now = datetime.now(timezone.utc)
    if date is not None:
        try:
            now = parsedate_to_datetime(str(date))
        except (TypeError, ValueError):
            pass
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, math.ceil((when - now).total_seconds()))


def parse_rate_limits(headers) -> RateLimitInfo:
    """Parse rate-limit info from HTTP response headers.

    Understands both header schemes SAIA has used (see the module docs) and
    ``Retry-After``.

    Args:
        headers: A dict-like object (e.g. ``requests.Response.headers`` or
            ``httpx.Response.headers``).

    Returns:
        RateLimitInfo with populated fields for each header found.
    """
    kwargs = {}
    for header_name, field_name in _HEADER_MAP.items():
        value = headers.get(header_name)
        if value is not None:
            try:
                kwargs[field_name] = int(value)
            except (ValueError, TypeError):
                pass
    retry_after = _parse_retry_after(headers.get("retry-after"), headers.get("date"))
    if retry_after is not None:
        kwargs["retry_after"] = retry_after
    return RateLimitInfo(**kwargs)


def format_rate_limit_error(info: RateLimitInfo, detail: str | None = None) -> str:
    """Build a human-readable message for a 429 (rate-limit) response.

    Pure — parses nothing, does no I/O — so both the sync and async transports
    raise the *same* informative :class:`~saia_python.RateLimitError` message
    when retry is off or the budget is spent, instead of a bare server string.
    Summarises the remaining per-window quota, when to retry, and how to make
    the call wait automatically.

    Args:
        info: The parsed rate-limit headers from the 429 response.
        detail: The server's own error detail, appended when present.
    """
    parts = ["SAIA rate limit exceeded (HTTP 429)."]
    windows = []
    for window in WINDOWS:
        limit = getattr(info, f"limit_{window}")
        remaining = getattr(info, f"remaining_{window}")
        if limit is not None:
            rem = remaining if remaining is not None else "?"
            windows.append(f"{window} {rem}/{limit}")
    if windows:
        parts.append("Remaining — " + ", ".join(windows) + ".")
    parts.extend(_when_to_retry(info))
    parts.append(
        "Pass retry=True (or a RetryPolicy) to wait for the reset and retry "
        "automatically; retry=False fails fast with this error."
    )
    if detail and detail.strip():
        parts.append(f"Server detail: {detail.strip()}")
    return " ".join(parts)


def _when_to_retry(info: RateLimitInfo) -> list[str]:
    """The sentences of a 429 message that say when a retry can succeed."""
    if info.retry_after is not None:
        return [f"The server asks to retry in ~{_duration(info.retry_after)}."]
    resets = []
    for window in info.exhausted_windows():
        reset = getattr(info, f"reset_{window}")
        if reset is not None and reset > 0:
            resets.append(f"The {window} window resets in ~{_duration(reset)}.")
    if resets:
        return resets
    if info.reset_seconds is not None and info.reset_seconds > 0:
        return [f"The minute window resets in ~{info.reset_seconds}s."]
    return []
