"""Read-only credential discovery for OpenCode Go.

Resolution order:

1. ``OCGO_TOKEN`` environment variable (manual/testing override).
2. The local OpenCode database, opened read-only. With a pinned
   ``credential_id``, exactly that row is read; otherwise the ``active = 1``
   credential wins (the one ``opencode auth switch`` marked) and the newest
   ``time_updated`` row is the fallback.
3. The legacy OpenCode ``auth.json`` login file (``$XDG_DATA_HOME/opencode``
   or ``~/.local/share/opencode``), read only when the database yields no
   credential and no specific ``credential_id`` was requested.

The token is never logged, printed in full, cached, or written anywhere.
:func:`list_db_credentials` exposes display metadata only (id, label, active,
email, org name) for CLI pickers.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

NO_CREDENTIAL_MESSAGE = (
    "No OpenCode credential found. Open OpenCode once with your account, "
    "or set OCGO_TOKEN."
)
EXPIRED_MESSAGE = "OpenCode credential expired — open OpenCode to refresh it."

_ENV_TOKEN = "OCGO_TOKEN"
_ENV_DB = "OCGO_DB"
_SOURCE_ENV = "OCGO_TOKEN environment"
_SOURCE_DB = "OpenCode local database"
_SOURCE_AUTH_JSON = "OpenCode auth.json file"
_ACTIVE_QUERY = (
    "SELECT value FROM credential WHERE integration_id = 'opencode' "
    "AND active = 1 ORDER BY time_updated DESC LIMIT 1"
)
_FALLBACK_QUERY = (
    "SELECT value FROM credential WHERE integration_id = 'opencode' "
    "ORDER BY time_updated DESC LIMIT 1"
)
_PINNED_QUERY = (
    "SELECT value FROM credential WHERE integration_id = 'opencode' "
    "AND id = ? LIMIT 1"
)
_LIST_QUERY = (
    "SELECT id, label, active, value FROM credential "
    "WHERE integration_id = 'opencode' ORDER BY time_updated DESC"
)
_EXISTS_QUERY = "SELECT 1 FROM credential WHERE integration_id = 'opencode' LIMIT 1"


def _missing_credential_message(credential_id: str) -> str:
    return (
        f"The OpenCode credential '{credential_id}' no longer exists in the "
        "local database — remove this account or sign in again in OpenCode."
    )


class CredentialError(Exception):
    """No usable credential is available."""


@dataclass(frozen=True)
class Credential:
    """A resolved token plus where it came from (never the full value)."""

    token: str = field(repr=False)
    source: str
    expires_ms: int | None = None

    @property
    def expires_at(self) -> datetime | None:
        if self.expires_ms is None:
            return None
        try:
            return datetime.fromtimestamp(self.expires_ms / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None


@dataclass(frozen=True)
class DbCredential:
    """Display metadata for one database credential; never carries a token."""

    id: str
    label: str
    active: bool
    email: str | None = None
    org_name: str | None = None


def default_db_path() -> Path:
    """``$XDG_DATA_HOME/opencode/opencode.db`` or the ``~/.local/share`` fallback."""
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / "opencode" / "opencode.db"
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def default_auth_json_path() -> Path:
    """``$XDG_DATA_HOME/opencode/auth.json`` or the ``~/.local/share`` fallback."""
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / "opencode" / "auth.json"
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _effective_db_path() -> Path:
    """The database the module reads: the ``OCGO_DB`` override or the default."""
    return Path(os.environ.get(_ENV_DB) or default_db_path()).expanduser()


def mask_token(token: str) -> str:
    """Return a hint that can never reveal the full token."""
    if len(token) <= 12:
        return "…"
    return f"{token[:6]}…{token[-4:]}"


def resolve_credential(
    *, credential_id: str | None = None, now_ms: int | None = None
) -> Credential:
    """Resolve the credential to use; ``OCGO_TOKEN`` wins over the stores.

    ``credential_id`` pins the lookup to that database row; ``None`` follows
    the database's active credential (fallback: newest ``time_updated``) and,
    when the database yields no credential, the legacy ``auth.json`` login —
    expired logins on either path raise ``EXPIRED_MESSAGE``. A pinned id
    never falls back: the original database error is re-raised.
    """
    env_token = os.environ.get(_ENV_TOKEN, "").strip()
    if env_token:
        return Credential(token=env_token, source=_SOURCE_ENV)
    try:
        return _resolve_db_credential(credential_id=credential_id, now_ms=now_ms)
    except CredentialError:
        if credential_id is not None:
            raise
        legacy = _read_legacy_login()
        if legacy is None:
            raise
        _raise_if_expired(legacy.expires_ms, now_ms)
        return legacy


def _read_legacy_login() -> Credential | None:
    """Read the legacy ``auth.json`` login; any problem reads as "no login".

    The file is keyed by integration id, mirroring OpenCode's own migration:
    keys match as ``opencode`` after trimming trailing ``/``; ``oauth``
    entries carry the token in ``access`` (with ``expires`` in ms-epoch
    terms), ``api`` entries in ``key``.
    """
    path = default_auth_json_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Missing, unreadable, non-UTF-8, or malformed: not a login.
        return None
    if not isinstance(payload, dict):
        return None
    entry = None
    for key, value in payload.items():
        if key.rstrip("/") == "opencode":
            entry = value
            break
    if not isinstance(entry, dict):
        return None
    if entry.get("type") == "oauth":
        token = entry.get("access")
        expires_ms = _parse_expiry(entry.get("expires"))
    elif entry.get("type") == "api":
        token = entry.get("key")
        expires_ms = None
    else:
        return None
    if not isinstance(token, str) or not token.strip():
        return None
    return Credential(
        token=token.strip(), source=_SOURCE_AUTH_JSON, expires_ms=expires_ms
    )


def _raise_if_expired(expires_ms: int | None, now_ms: int | None) -> None:
    """Raise ``EXPIRED_MESSAGE`` when the ms-epoch expiry has passed.

    ``now_ms`` overrides the clock for tests; ``None`` reads the wall clock.
    Shared by the database and legacy paths so both gate expiry identically.
    """
    if expires_ms is None:
        return
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if expires_ms <= now:
        raise CredentialError(EXPIRED_MESSAGE)


def _resolve_db_credential(
    *, credential_id: str | None = None, now_ms: int | None = None
) -> Credential:
    db_path = _effective_db_path()
    if not db_path.is_file():
        if credential_id is not None:
            raise CredentialError(_missing_credential_message(credential_id))
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    token, expires_ms = _read_db_row(db_path, credential_id=credential_id)
    _raise_if_expired(expires_ms, now_ms)
    return Credential(token=token, source=_SOURCE_DB, expires_ms=expires_ms)


def list_db_credentials() -> list[DbCredential]:
    """List the database's OpenCode credentials for pickers (never tokens).

    Rows come newest-``time_updated`` first. Malformed ``value`` JSON leaves
    the row listed with ``email``/``org_name`` as ``None``; an unreadable
    database raises :class:`CredentialError` with ``NO_CREDENTIAL_MESSAGE``.
    """
    db_path = _effective_db_path()
    if not db_path.is_file():
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            rows = connection.execute(_LIST_QUERY).fetchall()
    except sqlite3.Error as exc:
        raise CredentialError(NO_CREDENTIAL_MESSAGE) from exc
    credentials = []
    for credential_id, label, active, value in rows:
        email, org_name = _metadata_strings(value)
        credentials.append(
            DbCredential(
                id=str(credential_id),
                label=label.strip() if isinstance(label, str) else "",
                active=bool(active),
                email=email,
                org_name=org_name,
            )
        )
    return credentials


def has_stored_login() -> bool:
    """True when a login exists: ``OCGO_TOKEN``, a database row, or legacy.

    The database check only asks whether an ``opencode`` row exists, on
    stable columns — a schema without the listing's ``label`` reads the same
    way. Rows count regardless of expiry: an expired login still drives the
    seeded default's refresh messaging, and so does a legacy ``auth.json``
    login (presence, not expiry, is the question here).
    """
    if os.environ.get(_ENV_TOKEN, "").strip():
        return True
    if _db_has_stored_login():
        return True
    return _read_legacy_login() is not None


def _db_has_stored_login() -> bool:
    """True when the database holds at least one ``opencode`` row."""
    db_path = _effective_db_path()
    if not db_path.is_file():
        return False
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            row = connection.execute(_EXISTS_QUERY).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def store_status() -> dict:
    """Where credentials can live and whether any login is present.

    Reports the same paths the resolution reads so a caller (CLI, applet,
    dialog) can show them verbatim. Every value is JSON-safe and the check
    never raises: an unreadable store simply reads as absent.
    """
    db_path = _effective_db_path()
    auth_json_path = default_auth_json_path()
    return {
        "db_path": str(db_path),
        "db_exists": db_path.is_file(),
        "auth_json_path": str(auth_json_path),
        "auth_json_exists": auth_json_path.is_file(),
        "auth_json_login": _read_legacy_login() is not None,
        "has_login": has_stored_login(),
    }


def _metadata_strings(value: object) -> tuple[str | None, str | None]:
    """Extract ``(email, org_name)`` from a credential ``value`` payload.

    Absent, non-object, or non-string members read as ``None``.
    """
    if not isinstance(value, str):
        return None, None
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None, None
    email = metadata.get("email")
    org_name = metadata.get("orgName")
    return (
        email if isinstance(email, str) else None,
        org_name if isinstance(org_name, str) else None,
    )


def _read_db_row(
    db_path: Path, *, credential_id: str | None = None
) -> tuple[str, int | None]:
    """Read one credential row: pinned by id, else active, else newest.

    A pinned ``credential_id`` that cannot produce a usable token raises the
    actionable "no longer exists" message instead of the generic one.
    """
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            if credential_id is not None:
                row = connection.execute(_PINNED_QUERY, (credential_id,)).fetchone()
            else:
                # Prefer the credential that ``opencode auth switch`` marked active.
                row = connection.execute(_ACTIVE_QUERY, ()).fetchone()
                if not row:
                    row = connection.execute(_FALLBACK_QUERY, ()).fetchone()
    except sqlite3.Error as exc:
        raise CredentialError(NO_CREDENTIAL_MESSAGE) from exc
    if not row or not row[0]:
        raise _unusable_row_error(credential_id)
    try:
        value = json.loads(row[0])
        token = value["access"]
    except (TypeError, ValueError, KeyError) as exc:
        raise _unusable_row_error(credential_id) from exc
    if not isinstance(token, str) or not token.strip():
        raise _unusable_row_error(credential_id)
    return token.strip(), _parse_expiry(value.get("expires"))


def _unusable_row_error(credential_id: str | None) -> CredentialError:
    """The error for a row that cannot yield a token (pinned rows name it)."""
    if credential_id is not None:
        return CredentialError(_missing_credential_message(credential_id))
    return CredentialError(NO_CREDENTIAL_MESSAGE)


def _parse_expiry(value: object) -> int | None:
    """Return a sane ms-epoch expiry, or None when absent/malformed.

    Non-finite values (NaN, inf) and timestamps outside ``datetime``'s range
    are treated as "no expiry" so a corrupt credential row cannot crash the CLI.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    expires_ms = int(value)
    try:
        datetime.fromtimestamp(expires_ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return expires_ms
