"""Command line interface for ocgo."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
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

NO_ACCOUNTS_MESSAGE = "no accounts configured — run 'ocgo account add <id>'"

# Same 10-second budget as the secret-tool calls in accounts.py: a wedged
# OpenCode service must not hang account management.
_OPENCODE_SWITCH_TIMEOUT_SECONDS = 10


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
        "add", help="validate and register an account (OpenCode login or API key)"
    )
    add.add_argument("id", metavar="ID")
    add.add_argument("--label", help="human label (defaults to the id)")
    add.add_argument(
        "--store", choices=("auto", "file"), default="auto", help="secret backend"
    )
    add.add_argument(
        "--from-db",
        action="store_true",
        help="register the local OpenCode login as an account (no API key)",
    )
    add.add_argument(
        "--credential",
        metavar="ID_OR_LABEL",
        help="with --from-db: pin the account to this database credential",
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

    discover = account_sub.add_parser(
        "discover", help="list the OpenCode credentials in the local database"
    )
    discover.add_argument(
        "--json", action="store_true", help="print a JSON document"
    )
    discover.set_defaults(func=cmd_account_discover)

    activate = account_sub.add_parser(
        "activate-in-opencode",
        help="make a pinned login the active credential in OpenCode",
    )
    activate.add_argument("id", metavar="ID")
    activate.set_defaults(func=cmd_account_activate_in_opencode)

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
    if not targets:
        return _fail(NO_ACCOUNTS_MESSAGE)

    failures = 0
    for account in targets:
        ok, message = _refresh_one(account)
        if ok:
            if account.kind == accounts.KIND_OPENCODE_DB and registry is None:
                print(f"Refreshed OpenCode Go: {message}")
            else:
                print(f"Refreshed OpenCode Go ({account.id}): {message}")
            continue
        failures += 1
        label = ""
        if registry is not None:
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
    is_db = account.kind == accounts.KIND_OPENCODE_DB
    try:
        if is_db:
            token = creds.resolve_credential(
                credential_id=account.credential_id
            ).token
            payload = api.fetch_status(token)
            data = api.to_cache_schema(payload, now=now)
            try:
                billing = api.fetch_billing_status(token)
                try:
                    auto = api.fetch_auto_recharge(token)
                except api.ApiError:
                    auto = None
                data["credits"] = api.credits_from_billing(billing, auto)
            except api.ApiError as exc:
                data["credits"] = {"error": str(exc)}
        else:
            token = accounts.read_secret(account.id)
            payload = api.fetch_zen_status(token)
            data = api.to_cache_schema_zen(payload, now=now)
    except (creds.CredentialError, accounts.AccountError) as exc:
        # Recorded for every kind: the GUIs surface last_error in the popup,
        # and a lost or expired login must explain itself (no-op without a
        # prior cache — last good values are never invented).
        _record_refresh_failure(exc, now, path)
        return False, str(exc)
    except api.ApiError as exc:
        _record_refresh_failure(exc, now, path)
        return False, str(exc)

    try:
        cache.save(data, path)
    except OSError as exc:
        return False, f"could not write the cache: {exc}"
    return True, _summary(data["windows"], data.get("credits"))


def _find_account(account_id: str | None) -> accounts.Account:
    """Return the requested account, or the active one when id is None."""
    entries, active_id = accounts.list_accounts()
    if not entries:
        raise accounts.AccountError(NO_ACCOUNTS_MESSAGE)
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

    credits = data.get("credits")
    if isinstance(credits, dict):
        row, color = _credits_row(credits)
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
    if account.kind != accounts.KIND_OPENCODE_DB:
        return _show_stored_key(account)

    try:
        credential = creds.resolve_credential(credential_id=account.credential_id)
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
        entries, _active = accounts.list_accounts()
    except accounts.AccountError as exc:
        return _fail(exc)
    if args.credential is not None and not args.from_db:
        return _fail("--credential requires --from-db")
    if any(account.id == account_id for account in entries):
        return _fail(f"account '{account_id}' already exists")

    label = (args.label or account_id).strip() or account_id

    credential_id: str | None = None
    if args.credential is not None:
        try:
            credential_id = _resolve_credential_selector(args.credential)
        except (accounts.AccountError, creds.CredentialError) as exc:
            return _fail(exc)

    if args.from_db:
        try:
            creds.resolve_credential(credential_id=credential_id)
        except creds.CredentialError as exc:
            if credential_id is None:
                return _fail(
                    f"{exc} For an API key instead: ocgo account add "
                    f"{account_id} --label <label> (no --from-db)."
                )
            return _fail(exc)
        try:
            accounts.add_account(
                account_id,
                label,
                kind=accounts.KIND_OPENCODE_DB,
                credential_id=credential_id,
            )
        except accounts.AccountError as exc:
            return _fail(exc)
        if credential_id is None:
            print(f"Added account '{account_id}' (OpenCode login)")
        else:
            print(
                f"Added account '{account_id}' "
                f"(OpenCode login, credential '{credential_id}')"
            )
        return 0

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


def _resolve_credential_selector(selector: str) -> str:
    """Resolve a ``--credential`` selector: exact id first, then exact label."""
    candidates = creds.list_db_credentials()
    for credential in candidates:
        if credential.id == selector:
            return credential.id
    matches = [
        credential for credential in candidates if credential.label == selector
    ]
    if not matches:
        raise accounts.AccountError(
            f"no OpenCode credential matches '{selector}' — run "
            "'ocgo account discover' to list the available credentials"
        )
    if len(matches) > 1:
        ids = ", ".join(credential.id for credential in matches)
        raise accounts.AccountError(
            f"the credential label '{selector}' matches several credentials: {ids}"
        )
    return matches[0].id


def cmd_account_set_key(args: argparse.Namespace) -> int:
    account_id = args.id
    try:
        entries, _active = accounts.list_accounts()
    except accounts.AccountError as exc:
        return _fail(exc)
    account = next(
        (entry for entry in entries if entry.id == account_id), None
    )
    if account is None:
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

    # The UI routes existing ids here: an opencode-db account is converted to
    # an api-key account in place, every other account is a key replacement.
    converting = account.kind == accounts.KIND_OPENCODE_DB
    try:
        hint = accounts.store_secret(account_id, key, backend=args.store)
    except accounts.AccountError as exc:
        return _fail(exc)
    try:
        if converting:
            accounts.convert_to_api_key(account_id, hint)
        else:
            accounts.update_hint(account_id, hint)
    except accounts.AccountError as exc:
        if converting:
            _rollback_secret(account_id)
        return _fail(exc)

    if converting:
        print(
            f"Account '{account_id}' now uses a stored API key "
            f"({hint}; OpenCode login replaced)."
        )
        if no_subscription:
            print(
                f"ocgo: account '{account_id}' converted, but this account "
                "has no active OpenCode Go subscription",
                file=sys.stderr,
            )
        return 0

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
            # Schema stays 2: "credential_id" is an additive entry field, so
            # existing frontend consumers keep working unchanged.
            "schema": 2,
            "active": active,
            "accounts": [
                {
                    "id": account.id,
                    "label": account.label,
                    "kind": account.kind,
                    "hint": account.hint,
                    "active": account.id == active,
                    "credential_id": account.credential_id,
                }
                for account in entries
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if not entries:
        print("no accounts configured")
        return 0
    for account in entries:
        marker = "*" if account.id == active else " "
        if account.hint is None:
            details = account.kind
        else:
            details = f"{account.kind}, {account.hint}"
        print(f"{marker} {account.id:<12} {account.label}  ({details})")
    return 0


def cmd_account_discover(args: argparse.Namespace) -> int:
    try:
        credentials = creds.list_db_credentials()
    except creds.CredentialError as exc:
        return _fail(exc)
    if args.json:
        payload = {
            "schema": 1,
            "credentials": [
                {
                    "id": credential.id,
                    "label": credential.label,
                    "active": credential.active,
                    "email": credential.email,
                    "org_name": credential.org_name,
                }
                for credential in credentials
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if not credentials:
        print("no OpenCode credentials found in the local database")
        return 0
    id_width = max([len("ID")] + [len(credential.id) for credential in credentials])
    label_width = max(
        [len("LABEL")] + [len(credential.label) for credential in credentials]
    )
    print(f"{'ID':<{id_width}}  {'LABEL':<{label_width}}  {'ACTIVE':<6}  EMAIL")
    for credential in credentials:
        active = "yes" if credential.active else "no"
        email = credential.email or "-"
        print(
            f"{credential.id:<{id_width}}  {credential.label:<{label_width}}  "
            f"{active:<6}  {email}"
        )
    return 0


def cmd_account_activate_in_opencode(args: argparse.Namespace) -> int:
    try:
        account = _find_account(args.id)
    except accounts.AccountError as exc:
        return _fail(exc)
    if account.kind != accounts.KIND_OPENCODE_DB:
        return _fail(f"account '{account.id}' is not an OpenCode login account")
    if account.credential_id is None:
        return _fail(
            f"account '{account.id}' follows the active OpenCode credential; "
            "there is nothing to switch"
        )
    try:
        result = subprocess.run(
            ["opencode", "auth", "switch", "opencode", account.credential_id],
            capture_output=True,
            text=True,
            timeout=_OPENCODE_SWITCH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return _fail(
            "the 'opencode' command was not found on PATH — install OpenCode "
            "or add it to PATH"
        )
    except subprocess.TimeoutExpired:
        return _fail(
            "the 'opencode' command timed out; is the OpenCode service responsive?"
        )
    except OSError as exc:
        return _fail(f"could not run the 'opencode' command: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        message = (
            f"'opencode auth switch opencode {account.credential_id}' failed "
            f"(exit {result.returncode})"
        )
        if detail:
            message += f": {detail}"
        return _fail(message)
    print(
        f"Made account '{account.id}' the active credential in OpenCode "
        f"('{account.credential_id}')"
    )
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
    try:
        accounts.remove_account(account_id)
    except accounts.AccountError as exc:
        return _fail(exc)
    try:
        cache.remove_account_cache(account_id)
    except (accounts.AccountError, OSError) as exc:
        print(
            f"ocgo: removed account '{account_id}' but could not clean its "
            f"cache: {exc}",
            file=sys.stderr,
        )
    if account_id == accounts.DEFAULT_ACCOUNT_ID:
        # remove_account_cache never touches the legacy path (locked), so the
        # seeded default's cache is cleaned here, best-effort.
        try:
            cache.cache_path("default").unlink(missing_ok=True)
        except OSError as exc:
            print(
                f"ocgo: removed account '{account_id}' but could not clean its "
                f"cache: {exc}",
                file=sys.stderr,
            )
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


def _summary(windows: dict, credits: dict | None = None) -> str:
    parts = []
    for name, _label in WINDOW_LABELS:
        value = (windows.get(name) or {}).get("percent")
        parts.append(f"{name} {value}%" if isinstance(value, int) else f"{name} n/a")
    if isinstance(credits, dict):
        available = credits.get("available_usd")
        if isinstance(available, (int, float)) and not isinstance(available, bool):
            parts.append(f"${available:.2f}")
    return " · ".join(parts)


def _credits_row(credits: dict) -> tuple[str, str | None]:
    """Credits row text and color name, mirroring the window row layout."""
    if "error" in credits:
        value, suffix, color = "n/a", "unavailable", None
    else:
        available = credits.get("available_usd")
        if isinstance(available, bool) or not isinstance(available, (int, float)):
            available = None
        value = f"${available:.2f}" if available is not None else "n/a"
        state = credits.get("state")
        if state == "low":
            suffix, color = "Running low", fmt.AMBER
        elif state == "empty":
            suffix, color = "No credits left", fmt.RED
        else:
            suffix, color = "", None
    row = f"{'Credits':<{WINDOW_WIDTH}}{value}"
    if suffix:
        row = f"{row}   {suffix}"
    return row, color


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
