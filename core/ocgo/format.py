"""Pure formatting helpers for ocgo (no I/O; callers inject ``now``)."""

from __future__ import annotations

from datetime import datetime, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

GREEN = "green"
AMBER = "amber"
RED = "red"

AMBER_AT = 50  # >= 50 is amber
RED_AT = 85  # >= 85 is red

CREDITS_LOW_MICROCENTS = 500_000_000  # console low-balance threshold ($5.00)


def credits_state(
    available_microcents: int, *, prepaid: bool, auto_recharge_healthy: bool
) -> str:
    """Console credits state: ``ok`` / ``low`` / ``empty``.

    Mirrors the console: only prepaid balances can run low or empty; a low
    balance is suppressed while auto-recharge is healthy (it would refill).
    """
    if not prepaid:
        return "ok"
    if available_microcents <= 0:
        return "empty"
    if available_microcents < CREDITS_LOW_MICROCENTS and not auto_recharge_healthy:
        return "low"
    return "ok"


def percent(used_microcents: int, limit_microcents: int) -> int:
    """Single calibration point for the usage percentage.

    Mirrors the console: ``round(used / limit * 100)`` clamped to 0-100.
    Python's ``round()`` uses banker's rounding on exact .5 values; this is
    the only place to change if the console ever disagrees.
    """
    if limit_microcents <= 0:
        return 0
    return max(0, min(100, round(used_microcents / limit_microcents * 100)))


def usd_from_microcents(microcents: int) -> float:
    """Convert micro-cents (1e-8 USD) to USD rounded to 4 decimals."""
    return round(microcents * 1e-8, 4)


def countdown(now: datetime, target: datetime) -> str:
    """Remaining time in console format: ``Xd Yh`` / ``Xh Ym`` / ``Xm``.

    Targets in the past (or exactly now) render as ``0m``.
    """
    seconds = max(int((_as_utc(target) - _as_utc(now)).total_seconds()), 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def color_for(value: int) -> str:
    """Traffic-light color name for a 0-100 usage percentage."""
    if value >= RED_AT:
        return RED
    if value >= AMBER_AT:
        return AMBER
    return GREEN


def parse_iso(value: str | None) -> datetime | None:
    """Parse an API/ISO timestamp into an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_utc(parsed).astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    """Format a datetime as UTC ISO seconds (``2026-10-01T23:30:00Z``)."""
    return (
        _as_utc(value)
        .astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime(ISO_FORMAT)
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
