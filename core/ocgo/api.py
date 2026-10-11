"""OpenCode Go status API client and cache-schema mapping (stdlib only)."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .format import credits_state, iso_utc, parse_iso, percent, usd_from_microcents

API_URL = "https://opencode.ai/console/api/go/status"
BILLING_STATUS_URL = "https://opencode.ai/console/api/billing/status"
BILLING_AUTO_RECHARGE_URL = "https://opencode.ai/console/api/billing/auto-recharge"
ZEN_API_URL = "https://opencode.ai/zen/go/v1/usage"
TIMEOUT_SECONDS = 20
USER_AGENT = "ocgo/0.1"

CREDENTIAL_REJECTED = (
    "credential rejected (HTTP {code}) — open OpenCode to refresh it, "
    "or check your account."
)
BILLING_REJECTED = (
    "billing request rejected (HTTP {code}) — credits are available only "
    "for the OpenCode login account"
)
NETWORK_ERROR = "network error contacting opencode.ai: {reason}"
ZEN_AUTH_REJECTED = "the API key was rejected (HTTP 401)"
ZEN_NO_SUBSCRIPTION = "this account has no active OpenCode Go subscription"

# cache window name -> API meter key
WINDOW_METERS = (("rolling", "fiveHour"), ("weekly", "week"), ("monthly", "month"))
# zen usage meter names (cache window names are identical)
ZEN_USAGE_FIELDS = ("rolling", "weekly", "monthly")

Transport = Callable[..., Any]


class ApiError(Exception):
    """A refresh could not produce usable usage data."""


class ApiAuthError(ApiError):
    """The zen endpoint rejected the API key (HTTP 401)."""


class ApiEntitlementError(ApiError):
    """The API key is valid but the account has no Go subscription (HTTP 403)."""


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


def _fetch_console_json(
    url: str,
    token: str,
    *,
    rejected: str,
    transport: Transport | None,
    timeout: int,
) -> dict:
    """GET a console JSON endpoint sharing ``fetch_status``' contract.

    HTTP 401/403 raise ``ApiError(rejected.format(code=...))``; every other
    failure maps to the standard network error.
    """
    request = urllib.request.Request(
        url,
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
            raise ApiError(rejected.format(code=exc.code)) from exc
        raise ApiError(NETWORK_ERROR.format(reason=f"HTTP {exc.code}")) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise ApiError(NETWORK_ERROR.format(reason=reason)) from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(NETWORK_ERROR.format(reason="invalid JSON response")) from exc


def fetch_billing_status(
    token: str, *, transport: Transport | None = None, timeout: int = TIMEOUT_SECONDS
) -> dict:
    """GET the console billing status endpoint and return the decoded JSON.

    Same transport contract as :func:`fetch_status`; HTTP 401/403 raise a
    credits-specific ``ApiError`` because billing is only readable with a
    login-account token.
    """
    return _fetch_console_json(
        BILLING_STATUS_URL,
        token,
        rejected=BILLING_REJECTED,
        transport=transport,
        timeout=timeout,
    )


def fetch_auto_recharge(
    token: str, *, transport: Transport | None = None, timeout: int = TIMEOUT_SECONDS
) -> dict:
    """GET the console auto-recharge endpoint (same contract as billing)."""
    return _fetch_console_json(
        BILLING_AUTO_RECHARGE_URL,
        token,
        rejected=BILLING_REJECTED,
        transport=transport,
        timeout=timeout,
    )


def fetch_zen_status(
    token: str, *, transport: Transport | None = None, timeout: int = TIMEOUT_SECONDS
) -> dict:
    """GET the zen usage endpoint and return the decoded JSON payload.

    ``transport`` is injectable for tests (same contract as ``fetch_status``).
    HTTP 401 raises :class:`ApiAuthError`; HTTP 403 with an ``EntitlementError``
    body raises :class:`ApiEntitlementError`; anything else raises ``ApiError``.
    """
    request = urllib.request.Request(
        ZEN_API_URL,
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
        if exc.code == 401:
            raise ApiAuthError(ZEN_AUTH_REJECTED) from exc
        if exc.code == 403 and _is_entitlement_error(exc):
            raise ApiEntitlementError(ZEN_NO_SUBSCRIPTION) from exc
        raise ApiError(NETWORK_ERROR.format(reason=f"HTTP {exc.code}")) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise ApiError(NETWORK_ERROR.format(reason=reason)) from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(NETWORK_ERROR.format(reason="invalid JSON response")) from exc


def _is_entitlement_error(exc: urllib.error.HTTPError) -> bool:
    """True when a 403 body declares ``error.type == "EntitlementError"``."""
    try:
        body = exc.read()
        payload = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001 — a bodyless/malformed 403 is not entitlement
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    return isinstance(error, dict) and error.get("type") == "EntitlementError"


def to_cache_schema_zen(payload: dict, *, now: datetime) -> dict:
    """Map a zen usage payload to cache schema v1.

    ``used_usd``/``limit_usd`` are always ``null``: the zen endpoint reports
    percentages only. ``renewal_ends_at`` mirrors the monthly meter reset.
    ``extra_usage`` and ``credits`` are always ``null``: API-key accounts
    have neither the switch nor billing access.
    """
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        raise _unexpected("missing usage")
    windows: dict[str, dict] = {}
    for name in ZEN_USAGE_FIELDS:
        meter = usage.get(name)
        if not isinstance(meter, dict):
            raise _unexpected(f"missing usage meter '{name}'")
        windows[name] = {
            "percent": _zen_percent(meter.get("percent"), name),
            "used_usd": None,
            "limit_usd": None,
            "resets_at": _iso_or_none(meter.get("resetsAt")),
        }
    return {
        "schema": 1,
        "fetched_at": iso_utc(now),
        "last_error": None,
        "last_error_at": None,
        "product": "go",
        "renewal_ends_at": windows["monthly"]["resets_at"],
        "windows": windows,
        "extra_usage": None,
        "credits": None,
    }


def to_cache_schema(payload: dict, *, now: datetime) -> dict:
    """Map an API payload to cache schema v1 (see odd/tasks/opencode-go-meter.md).

    ``monthly.resets_at`` is always ``null``: the month meter has no
    ``resetsAt`` and the console counts down to ``access.endsAt`` instead.
    ``extra_usage`` mirrors ``useBalance`` (``null`` when absent/non-bool);
    ``credits`` stays ``null`` here and is filled by the CLI after the
    best-effort billing fetch.
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

    use_balance = payload.get("useBalance")
    return {
        "schema": 1,
        "fetched_at": iso_utc(now),
        "last_error": None,
        "last_error_at": None,
        "product": payload.get("product") or "go",
        "renewal_ends_at": _iso_or_none(access.get("endsAt")),
        "windows": windows,
        "extra_usage": use_balance if isinstance(use_balance, bool) else None,
        "credits": None,
    }


def credits_from_billing(billing: dict, auto_recharge: dict | None) -> dict:
    """Build the cache ``credits`` block from billing payloads.

    ``availableMicroCents`` is required (string or int); every other field is
    best-effort, so a partially shaped payload still yields a usable balance.
    ``auto_recharge`` is the raw auto-recharge payload, or ``None`` when it
    was not fetched.
    """
    if not isinstance(billing, dict):
        raise _unexpected("missing billing payload")
    available = _as_int(billing.get("availableMicroCents"), "availableMicroCents")
    billing_mode = billing.get("billingMode")
    if not isinstance(billing_mode, str):
        billing_mode = None
    healthy = (
        isinstance(auto_recharge, dict)
        and auto_recharge.get("enabled") is True
        and auto_recharge.get("failureReason") is None
    )
    return {
        "available_usd": usd_from_microcents(available),
        "state": credits_state(
            available,
            prepaid=billing_mode == "prepaid",
            auto_recharge_healthy=healthy,
        ),
        "billing_mode": billing_mode,
        "auto_recharge": _auto_recharge_block(auto_recharge),
    }


def _auto_recharge_block(payload: Any) -> dict | None:
    """Cache shape for auto-recharge; ``None`` when no payload was fetched."""
    if not isinstance(payload, dict):
        return None
    return {
        "enabled": payload.get("enabled") is True,
        "threshold_usd": _dollars_or_none(payload.get("thresholdDollars")),
        "amount_usd": _dollars_or_none(payload.get("rechargeAmountDollars")),
        "pending": payload.get("pending") is True,
        "failed": payload.get("failureReason") is not None,
    }


def _dollars_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unexpected(reason: str) -> ApiError:
    return ApiError(NETWORK_ERROR.format(reason=f"unexpected response: {reason}"))


def _as_int(value: Any, meter_key: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _unexpected(f"bad value in '{meter_key}'") from exc


def _zen_percent(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _unexpected(f"bad percent in '{name}'")
    if not math.isfinite(value):
        raise _unexpected(f"bad percent in '{name}'")
    return int(round(value))


def _iso_or_none(value: Any) -> str | None:
    parsed = parse_iso(value) if isinstance(value, str) else None
    return iso_utc(parsed) if parsed is not None else None
