"""Command line interface for ocgo."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

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

    auth = subparsers.add_parser(
        "auth", help="credential information and the fallback API key"
    )
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    show = auth_sub.add_parser(
        "show", help="show the credential source and a masked token hint"
    )
    show.add_argument("--json", action="store_true", help="print a JSON document")
    show.set_defaults(func=cmd_auth_show)

    set_key = auth_sub.add_parser(
        "set-key", help="validate and store the fallback API key"
    )
    set_key.add_argument("--stdin", action="store_true", help="read the key from stdin")
    set_key.set_defaults(func=cmd_auth_set_key)

    clear_key = auth_sub.add_parser(
        "clear-key", help="remove the stored fallback API key"
    )
    clear_key.set_defaults(func=cmd_auth_clear_key)

    set_data_dir = auth_sub.add_parser(
        "set-data-dir", help="use this OpenCode credentials directory"
    )
    set_data_dir.add_argument("path", metavar="PATH")
    set_data_dir.set_defaults(func=cmd_auth_set_data_dir)

    clear_data_dir = auth_sub.add_parser(
        "clear-data-dir",
        help="reset the OpenCode credentials directory to the automatic default",
    )
    clear_data_dir.set_defaults(func=cmd_auth_clear_data_dir)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


def cmd_refresh(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    try:
        credential = creds.resolve_credential()
    except creds.CredentialError as exc:
        _record_refresh_failure(exc, now)
        return _fail(exc)
    ok, message = _refresh(token=credential.token, kind=credential.kind, now=now)
    if not ok:
        return _fail(message)
    print(f"Refreshed OpenCode Go: {message}")
    return 0


def _refresh(*, token: str, kind: str, now: datetime) -> tuple[bool, str]:
    """Fetch usage for one credential and write the cache.

    Returns ``(ok, summary_or_error)``. A failed fetch records ``last_error``
    beside the last good values (never inventing them); ``"api"`` tokens hit
    the zen endpoint, everything else the console status endpoint.
    """
    try:
        if kind == creds.KIND_API:
            payload = api.fetch_zen_status(token)
            data = api.to_cache_schema_zen(payload, now=now)
        else:
            payload = api.fetch_status(token)
            data = api.to_cache_schema(payload, now=now)
    except api.ApiError as exc:
        _record_refresh_failure(exc, now)
        return False, str(exc)
    try:
        cache.save(data)
    except OSError as exc:
        return False, f"could not write the cache: {exc}"
    return True, _summary(data["windows"])


def cmd_status(args: argparse.Namespace) -> int:
    path = cache.cache_path()

    if args.json:
        try:
            raw = cache.raw_text(path)
        except cache.CacheError as exc:
            return _fail(exc)
        sys.stdout.write(raw if raw.endswith("\n") else raw + "\n")
        return 0

    try:
        data = cache.load(path)
    except cache.CacheError as exc:
        return _fail(exc)
    if data is None:
        return _fail(f"no cached usage yet ({path}) — run 'ocgo refresh' first")

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


def cmd_auth_show(args: argparse.Namespace) -> int:
    store = creds.store_status()
    try:
        credential = creds.resolve_credential()
    except creds.CredentialError as exc:
        if args.json:
            print(
                json.dumps(
                    {"schema": 1, "credential": None, "store": store},
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print("Source:  none")
        print(f"ocgo: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "schema": 1,
                    "credential": {
                        "source": credential.source,
                        "kind": credential.kind,
                        "token_hint": creds.mask_token(credential.token),
                        "expires_at": _iso_or_none(credential.expires_at),
                    },
                    "store": store,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print(f"Source:  {credential.source}")
    print(f"Token:   {creds.mask_token(credential.token)}")
    if credential.expires_at is not None:
        remaining = fmt.countdown(datetime.now(timezone.utc), credential.expires_at)
        print(f"Expires: {fmt.iso_utc(credential.expires_at)} (in {remaining})")
    return 0


def _iso_or_none(value: datetime | None) -> str | None:
    return fmt.iso_utc(value) if value is not None else None


def cmd_auth_set_key(args: argparse.Namespace) -> int:
    key = _read_api_key(args.stdin).strip()
    if not key:
        return _fail("no API key provided")
    no_subscription = False
    try:
        api.fetch_zen_status(key)
    except api.ApiEntitlementError:
        no_subscription = True
    except api.ApiError as exc:
        return _fail(exc)

    try:
        hint = creds.store_api_key(key)
    except (creds.CredentialError, OSError) as exc:
        return _fail(exc)

    # Refresh right away so the frontends pick the new key up. The cache
    # keeps its previous values with a recorded error when the fetch fails
    # (expected for an account without a Go subscription).
    now = datetime.now(timezone.utc)
    ok, message = _refresh(token=key, kind=creds.KIND_API, now=now)
    print(f"Stored API key {hint}")
    if no_subscription:
        print(
            "ocgo: this account has no active OpenCode Go subscription",
            file=sys.stderr,
        )
    if not ok and not no_subscription:
        return _fail(message)
    return 0


def cmd_auth_clear_key(args: argparse.Namespace) -> int:
    if creds.clear_api_key():
        print("Cleared the stored API key")
    else:
        print("No stored API key to clear")
    return 0


def cmd_auth_set_data_dir(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    if not path.is_dir():
        return _fail(f"not a directory: {path}")
    creds.set_configured_data_dir(str(path))
    print(f"OpenCode data directory set to {path}")
    return 0


def cmd_auth_clear_data_dir(args: argparse.Namespace) -> int:
    creds.set_configured_data_dir(None)
    print("OpenCode data directory reset to the default")
    return 0


def _read_api_key(force_stdin: bool = False) -> str:
    """Read an API key: one stdin line when asked or piped, else a hidden prompt."""
    stream = sys.stdin
    if force_stdin or stream is None or not stream.isatty():
        line = stream.readline() if stream is not None else ""
        return line.strip()
    return getpass.getpass("API key: ").strip()


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


def _record_refresh_failure(
    error: Exception, now: datetime, path: Path | None = None
) -> None:
    """Keep the last good values and persist the error alongside them."""
    target = path or cache.cache_path()
    try:
        previous = cache.load(target)
    except cache.CacheError:
        previous = None
    if previous is not None:
        previous["last_error"] = str(error)
        previous["last_error_at"] = fmt.iso_utc(now)
        try:
            cache.save(previous, target)
        except OSError as exc:
            print(f"ocgo: could not update the cache: {exc}", file=sys.stderr)


def _fail(message: object) -> int:
    print(f"ocgo: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
