"""Rate limit header parsing for SAIA API responses."""

from dataclasses import asdict, dataclass


@dataclass
class RateLimitInfo:
    """Parsed rate-limit information from SAIA API response headers."""

    limit_minute: int | None = None
    limit_hour: int | None = None
    limit_day: int | None = None
    limit_month: int | None = None
    remaining_minute: int | None = None
    remaining_hour: int | None = None
    remaining_day: int | None = None
    remaining_month: int | None = None
    reset_seconds: int | None = None

    def to_dict(self) -> dict:
        """Return a plain, JSON-serializable dict of all rate-limit fields."""
        return asdict(self)

    def __str__(self):
        rows = []
        for window in ("minute", "hour", "day", "month"):
            limit = getattr(self, f"limit_{window}")
            remaining = getattr(self, f"remaining_{window}")
            if limit is not None:
                rem_str = str(remaining) if remaining is not None else "?"
                used = str(limit - remaining) if remaining is not None else "?"
                rows.append((window, rem_str, limit, used))

        if not rows:
            return "SAIA Rate Limits: (no data)"

        w_rem = max(len(str(r[1])) for r in rows)
        w_lim = max(len(str(r[2])) for r in rows)
        w_used = max(len(str(r[3])) for r in rows)

        lines = ["SAIA Rate Limits:"]
        for window, remaining, limit, used in rows:
            lines.append(
                f"  {window:<6}  "
                f"{remaining:>{w_rem}} / {limit:>{w_lim}}  "
                f"remaining  "
                f"({used:>{w_used}} used)"
            )
        if self.reset_seconds is not None:
            lines.append(f"  Resets in {self.reset_seconds}s")
        return "\n".join(lines)


_HEADER_MAP = {
    "x-ratelimit-limit-minute": "limit_minute",
    "x-ratelimit-limit-hour": "limit_hour",
    "x-ratelimit-limit-day": "limit_day",
    "x-ratelimit-limit-month": "limit_month",
    "x-ratelimit-remaining-minute": "remaining_minute",
    "x-ratelimit-remaining-hour": "remaining_hour",
    "x-ratelimit-remaining-day": "remaining_day",
    "x-ratelimit-remaining-month": "remaining_month",
    "ratelimit-reset": "reset_seconds",
}


def parse_rate_limits(headers) -> RateLimitInfo:
    """Parse rate-limit info from HTTP response headers.

    Args:
        headers: A dict-like object (e.g. ``requests.Response.headers``).

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
    return RateLimitInfo(**kwargs)
