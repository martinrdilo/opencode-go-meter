"""OpenCode Go status API client and cache-schema mapping (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .format import iso_utc, parse_iso, percent, usd_from_microcents

API_URL = "https://opencode.ai/console/api/go/status"
TIMEOUT_SECONDS = 20
USER_AGENT = "ocgo/0.1"

CREDENTIAL_REJECTED = (
    "credential rejected (HTTP {code}) — open OpenCode to refresh it, "
    "or check your account."
)
NETWORK_ERROR = "network error contacting opencode.ai: {reason}"

# cache window name -> API meter key
WINDOW_METERS = (("rolling", "fiveHour"), ("weekly", "week"), ("monthly", "month"))

Transport = Callable[..., Any]


class ApiError(Exception):
    """A refresh could not produce usable usage data."""


def fetch_status(
    token: str, *, transport: Transport | None = None, timeout: int = TIMEOUT_SECONDS
) -> dict:
    """GET the console status endpoint and return the decoded JSON payload.

    ``transport`` is injectable for tests; it defaults to
    ``urllib.request.urlopen`` and is called as ``transport(request, timeout=...)``.
    """
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    opener = transport if transport is not None else urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ApiError(CREDENTIAL_REJECTED.format(code=exc.code)) from exc
        raise ApiError(NETWORK_ERROR.format(reason=f"HTTP {exc.code}")) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise ApiError(NETWORK_ERROR.format(reason=reason)) from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(NETWORK_ERROR.format(reason="invalid JSON response")) from exc


def to_cache_schema(payload: dict, *, now: datetime) -> dict:
    """Map an API payload to cache schema v1 (see odd/tasks/opencode-go-meter.md).

    ``monthly.resets_at`` is always ``null``: the month meter has no
    ``resetsAt`` and the console counts down to ``access.endsAt`` instead.
    """
    access = payload.get("access") if isinstance(payload, dict) else None
    meters = access.get("meters") if isinstance(access, dict) else None
    if not isinstance(meters, dict):
        raise _unexpected("missing access.meters")

    windows: dict[str, dict] = {}
    for name, meter_key in WINDOW_METERS:
        meter = meters.get(meter_key)
        if not isinstance(meter, dict):
            raise _unexpected(f"missing meter '{meter_key}'")
        used = _as_int(meter.get("usedMicroCents"), meter_key)
        limit = _as_int(meter.get("limitMicroCents"), meter_key)
        windows[name] = {
            "percent": percent(used, limit),
            "used_usd": usd_from_microcents(used),
            "limit_usd": usd_from_microcents(limit),
            "resets_at": None
            if name == "monthly"
            else _iso_or_none(meter.get("resetsAt")),
        }

    return {
        "schema": 1,
        "fetched_at": iso_utc(now),
        "last_error": None,
        "last_error_at": None,
        "product": payload.get("product") or "go",
        "renewal_ends_at": _iso_or_none(access.get("endsAt")),
        "windows": windows,
    }


def _unexpected(reason: str) -> ApiError:
    return ApiError(NETWORK_ERROR.format(reason=f"unexpected response: {reason}"))


def _as_int(value: Any, meter_key: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _unexpected(f"bad value in '{meter_key}'") from exc


def _iso_or_none(value: Any) -> str | None:
    parsed = parse_iso(value) if isinstance(value, str) else None
    return iso_utc(parsed) if parsed is not None else None
