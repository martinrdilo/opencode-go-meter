"""Command line interface for ocgo."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, accounts, api, cache, creds
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
    refresh_target = refresh.add_mutually_exclusive_group()
    refresh_target.add_argument("--account", metavar="ID", help="refresh this account")
    refresh_target.add_argument(
        "--all", action="store_true", help="refresh every account"
    )
    refresh.set_defaults(func=cmd_refresh)

    status = subparsers.add_parser("status", help="show the cached usage")
    status.add_argument(
        "--json", action="store_true", help="print the raw cache file and exit"
    )
    status.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    status.add_argument("--account", metavar="ID", help="show this account")
    status.set_defaults(func=cmd_status)

    auth = subparsers.add_parser("auth", help="credential information")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    show = auth_sub.add_parser(
        "show", help="show the credential source and a masked token hint"
    )
    show.add_argument("--account", metavar="ID", help="show this account")
    show.set_defaults(func=cmd_auth_show)

    account = subparsers.add_parser("account", help="manage OpenCode Go accounts")
    account_sub = account.add_subparsers(dest="account_command", required=True)

    add = account_sub.add_parser(
        "add", help="validate and register an account from an API key"
    )
    add.add_argument("id", metavar="ID")
    add.add_argument("--label", help="human label (defaults to the id)")
    add.add_argument(
        "--store", choices=("auto", "file"), default="auto", help="secret backend"
    )
    add.set_defaults(func=cmd_account_add)

    set_key = account_sub.add_parser(
        "set-key", help="validate and replace an account's API key"
    )
    set_key.add_argument("id", metavar="ID")
    set_key.add_argument(
        "--store", choices=("auto", "file"), default="auto", help="secret backend"
    )
    set_key.set_defaults(func=cmd_account_set_key)

    listing = account_sub.add_parser(
        "list", help="list accounts and the active one"
    )
    listing.add_argument("--json", action="store_true", help="print a JSON document")
    listing.set_defaults(func=cmd_account_list)

    use = account_sub.add_parser("use", help="switch the active account")
    use.add_argument("id", metavar="ID")
    use.set_defaults(func=cmd_account_use)

    remove = account_sub.add_parser("remove", help="remove an account")
    remove.add_argument("id", metavar="ID")
    remove.set_defaults(func=cmd_account_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


def cmd_refresh(args: argparse.Namespace) -> int:
    try:
        registry = accounts.load_registry()
        targets = _refresh_targets(args)
    except accounts.AccountError as exc:
        return _fail(exc)

    failures = 0
    for account in targets:
        ok, message = _refresh_one(account)
        if ok:
            if account.id == accounts.DEFAULT_ACCOUNT_ID and registry is None:
                print(f"Refreshed OpenCode Go: {message}")
            else:
                print(f"Refreshed OpenCode Go ({account.id}): {message}")
            continue
        failures += 1
        label = ""
        if args.all or account.id != accounts.DEFAULT_ACCOUNT_ID:
            label = f"account '{account.id}': "
        print(f"ocgo: {label}{message}", file=sys.stderr)
    return 1 if failures else 0


def _refresh_targets(args: argparse.Namespace) -> list[accounts.Account]:
    if getattr(args, "all", False):
        entries, _active = accounts.list_accounts()
        return entries
    return [_find_account(getattr(args, "account", None))]


def _refresh_one(account: accounts.Account) -> tuple[bool, str]:
    """Refresh one account; returns ``(ok, summary_or_error)``."""
    path = cache.cache_path(account.id)
    now = datetime.now(timezone.utc)
    try:
        if account.id == accounts.DEFAULT_ACCOUNT_ID:
            token = creds.resolve_credential().token
            payload = api.fetch_status(token)
            data = api.to_cache_schema(payload, now=now)
        else:
            token = accounts.read_secret(account.id)
            payload = api.fetch_zen_status(token)
            data = api.to_cache_schema_zen(payload, now=now)
    except (creds.CredentialError, accounts.AccountError) as exc:
        return False, str(exc)
    except api.ApiError as exc:
        _record_refresh_failure(exc, now, path)
        return False, str(exc)

    try:
        cache.save(data, path)
    except OSError as exc:
        return False, f"could not write the cache: {exc}"
    return True, _summary(data["windows"])


def _find_account(account_id: str | None) -> accounts.Account:
    """Return the requested account, or the active one when id is None."""
    entries, active_id = accounts.list_accounts()
    target = account_id or active_id
    for account in entries:
        if account.id == target:
            return account
    raise accounts.AccountError(f"account '{target}' does not exist")


def cmd_status(args: argparse.Namespace) -> int:
    try:
        account = _find_account(getattr(args, "account", None))
    except accounts.AccountError as exc:
        return _fail(exc)
    path = cache.cache_path(account.id)

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
    try:
        account = _find_account(getattr(args, "account", None))
    except accounts.AccountError as exc:
        return _fail(exc)
    if account.id != accounts.DEFAULT_ACCOUNT_ID:
        return _show_stored_key(account)

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


def _show_stored_key(account: accounts.Account) -> int:
    hint = account.hint
    if hint is None:
        try:
            hint = creds.mask_token(accounts.read_secret(account.id))
        except accounts.AccountError as exc:
            return _fail(exc)
    print(f"Source:  stored API key (account '{account.id}')")
    print(f"Token:   {hint}")
    return 0


def cmd_account_add(args: argparse.Namespace) -> int:
    account_id = args.id
    try:
        accounts.validate_account_id(account_id)
        registry = accounts.load_registry()
    except accounts.AccountError as exc:
        return _fail(exc)
    if registry is not None and any(
        entry["id"] == account_id for entry in registry["accounts"]
    ):
        return _fail(f"account '{account_id}' already exists")

    key = _read_api_key().strip()
    if not key:
        return _fail("no API key provided")
    no_subscription = False
    try:
        api.fetch_zen_status(key)
    except api.ApiEntitlementError:
        no_subscription = True
    except api.ApiError as exc:
        return _fail(exc)

    label = (args.label or account_id).strip() or account_id
    try:
        hint = accounts.store_secret(account_id, key, backend=args.store)
    except accounts.AccountError as exc:
        return _fail(exc)
    try:
        accounts.add_account(account_id, label, hint=hint)
    except accounts.AccountError as exc:
        _rollback_secret(account_id)
        return _fail(exc)

    print(f"Added account '{account_id}' ({hint})")
    if no_subscription:
        print(
            f"ocgo: account '{account_id}' stored, but this account has no "
            "active OpenCode Go subscription",
            file=sys.stderr,
        )
    return 0


def cmd_account_set_key(args: argparse.Namespace) -> int:
    account_id = args.id
    if account_id == accounts.DEFAULT_ACCOUNT_ID:
        return _fail(
            "the default account uses the local OpenCode login; "
            "there is no API key to set"
        )
    try:
        entries, _active = accounts.list_accounts()
    except accounts.AccountError as exc:
        return _fail(exc)
    if not any(account.id == account_id for account in entries):
        return _fail(f"account '{account_id}' does not exist")

    key = _read_api_key().strip()
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
        hint = accounts.store_secret(account_id, key, backend=args.store)
        accounts.update_hint(account_id, hint)
    except accounts.AccountError as exc:
        return _fail(exc)

    print(f"Updated key for account '{account_id}' ({hint})")
    if no_subscription:
        print(
            f"ocgo: account '{account_id}' updated, but this account has no "
            "active OpenCode Go subscription",
            file=sys.stderr,
        )
    return 0


def cmd_account_list(args: argparse.Namespace) -> int:
    try:
        entries, active = accounts.list_accounts()
    except accounts.AccountError as exc:
        return _fail(exc)
    if args.json:
        payload = {
            "schema": 1,
            "active": active,
            "accounts": [
                {
                    "id": account.id,
                    "label": account.label,
                    "kind": account.kind,
                    "hint": account.hint,
                    "active": account.id == active,
                }
                for account in entries
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    for account in entries:
        marker = "*" if account.id == active else " "
        if account.hint is None:
            details = account.kind
        else:
            details = f"{account.kind}, {account.hint}"
        print(f"{marker} {account.id:<12} {account.label}  ({details})")
    return 0


def cmd_account_use(args: argparse.Namespace) -> int:
    try:
        accounts.set_active(args.id)
    except accounts.AccountError as exc:
        return _fail(exc)
    print(f"Active account: {args.id}")
    return 0


def cmd_account_remove(args: argparse.Namespace) -> int:
    account_id = args.id
    if account_id == accounts.DEFAULT_ACCOUNT_ID:
        return _fail("the default account cannot be removed")
    try:
        cache.remove_account_cache(account_id)
        accounts.remove_account(account_id)
    except (accounts.AccountError, OSError) as exc:
        return _fail(exc)
    print(f"Removed account '{account_id}'")
    return 0


def _read_api_key() -> str:
    """Read an API key: hidden prompt on a TTY, one stdin line otherwise."""
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass("API key: ").strip()
    line = sys.stdin.readline() if sys.stdin is not None else ""
    return line.strip()


def _rollback_secret(account_id: str) -> None:
    try:
        accounts.delete_secret(account_id)
    except accounts.AccountError as exc:
        print(
            f"ocgo: could not clean up the secret for '{account_id}': {exc}",
            file=sys.stderr,
        )


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
