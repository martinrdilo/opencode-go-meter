"""Command line interface for ocgo."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from . import __version__, api, cache, creds
from . import format as fmt

WINDOW_LABELS = (
    ("rolling", "Rolling usage"),
    ("weekly", "Weekly usage"),
    ("monthly", "Monthly usage"),
)
ANSI_COLORS = {"green": "\x1b[32m", "amber": "\x1b[33m", "red": "\x1b[31m"}
ANSI_RESET = "\x1b[0m"

WINDOW_WIDTH = 15  # label column width, matching the console layout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocgo",
        description=(
            "OpenCode Go usage meter. Reads the same console API as "
            "opencode.ai/console and caches the result locally."
        ),
    )
    parser.add_argument("--version", action="version", version=f"ocgo {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="fetch usage and update the cache")
    refresh.set_defaults(func=cmd_refresh)

    status = subparsers.add_parser("status", help="show the cached usage")
    status.add_argument(
        "--json", action="store_true", help="print the raw cache file and exit"
    )
    status.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    status.set_defaults(func=cmd_status)

    auth = subparsers.add_parser("auth", help="credential information")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    show = auth_sub.add_parser(
        "show", help="show the credential source and a masked token hint"
    )
    show.set_defaults(func=cmd_auth_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


def cmd_refresh(_args: argparse.Namespace) -> int:
    try:
        credential = creds.resolve_credential()
    except creds.CredentialError as exc:
        return _fail(exc)

    now = datetime.now(timezone.utc)
    try:
        payload = api.fetch_status(credential.token)
        data = api.to_cache_schema(payload, now=now)
    except api.ApiError as exc:
        return _record_refresh_failure(exc, now)

    try:
        cache.save(data)
    except OSError as exc:
        return _fail(f"could not write the cache: {exc}")

    print(f"Refreshed OpenCode Go: {_summary(data['windows'])}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if args.json:
        try:
            raw = cache.raw_text()
        except cache.CacheError as exc:
            return _fail(exc)
        sys.stdout.write(raw if raw.endswith("\n") else raw + "\n")
        return 0

    try:
        data = cache.load()
    except cache.CacheError as exc:
        return _fail(exc)
    if data is None:
        return _fail(
            f"no cached usage yet ({cache.cache_path()}) — run 'ocgo refresh' first"
        )

    colors = colors_enabled(args.no_color)
    now = datetime.now(timezone.utc)
    windows = data.get("windows")
    if not isinstance(windows, dict):
        windows = {}
    for name, label in WINDOW_LABELS:
        window = windows.get(name)
        if not isinstance(window, dict):
            window = {}
        value = window.get("percent")
        if isinstance(value, int):
            pct_text = f"{value:>3}%"
            color = fmt.color_for(value)
        else:
            pct_text = "n/a"
            color = None
        target = _window_target(name, window, data)
        remaining = "n/a" if target is None else fmt.countdown(now, target)
        row = f"{label:<{WINDOW_WIDTH}}{pct_text}   Resets in {remaining}"
        if colors and color is not None:
            row = f"{ANSI_COLORS[color]}{row}{ANSI_RESET}"
        print(row)

    if data.get("last_error"):
        print(
            f"Warning: last refresh failed at {data.get('last_error_at')}: "
            f"{data.get('last_error')} "
            f"(showing data from {data.get('fetched_at')})",
            file=sys.stderr,
        )
    return 0


def cmd_auth_show(_args: argparse.Namespace) -> int:
    try:
        credential = creds.resolve_credential()
    except creds.CredentialError as exc:
        return _fail(exc)

    print(f"Source:  {credential.source}")
    print(f"Token:   {creds.mask_token(credential.token)}")
    if credential.expires_at is not None:
        remaining = fmt.countdown(datetime.now(timezone.utc), credential.expires_at)
        print(f"Expires: {fmt.iso_utc(credential.expires_at)} (in {remaining})")
    return 0


def colors_enabled(no_color: bool, stream=None) -> bool:
    """Colors only on a TTY, unless disabled with --no-color or NO_COLOR."""
    output = stream if stream is not None else sys.stdout
    if no_color or os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(output, "isatty", lambda: False)())


def _window_target(name: str, window: dict, data: dict):
    if name == "monthly":
        # The month meter has no resetsAt; the console counts down to renewal.
        return fmt.parse_iso(data.get("renewal_ends_at"))
    return fmt.parse_iso(window.get("resets_at"))


def _summary(windows: dict) -> str:
    parts = []
    for name, _label in WINDOW_LABELS:
        value = (windows.get(name) or {}).get("percent")
        parts.append(f"{name} {value}%" if isinstance(value, int) else f"{name} n/a")
    return " · ".join(parts)


def _record_refresh_failure(error: Exception, now: datetime) -> int:
    """Keep the last good values and persist the error alongside them."""
    try:
        previous = cache.load()
    except cache.CacheError:
        previous = None
    if previous is not None:
        previous["last_error"] = str(error)
        previous["last_error_at"] = fmt.iso_utc(now)
        try:
            cache.save(previous)
        except OSError as exc:
            print(f"ocgo: could not update the cache: {exc}", file=sys.stderr)
    return _fail(error)


def _fail(message: object) -> int:
    print(f"ocgo: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
