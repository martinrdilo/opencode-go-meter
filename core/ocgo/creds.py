"""Read-only credential discovery for OpenCode Go.

Resolution order:

1. ``OCGO_TOKEN`` environment variable (manual/testing override).
2. The local OpenCode database, opened read-only. Inside the database the
   ``active = 1`` credential wins (the one ``opencode auth switch`` marked);
   when no row is active, the newest ``time_updated`` row wins.

The token is never logged, printed in full, cached, or written anywhere.
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
_ACTIVE_QUERY = (
    "SELECT value FROM credential WHERE integration_id = 'opencode' "
    "AND active = 1 ORDER BY time_updated DESC LIMIT 1"
)
_FALLBACK_QUERY = (
    "SELECT value FROM credential WHERE integration_id = 'opencode' "
    "ORDER BY time_updated DESC LIMIT 1"
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


def default_db_path() -> Path:
    """``$XDG_DATA_HOME/opencode/opencode.db`` or the ``~/.local/share`` fallback."""
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / "opencode" / "opencode.db"
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def mask_token(token: str) -> str:
    """Return a hint that can never reveal the full token."""
    if len(token) <= 12:
        return "…"
    return f"{token[:6]}…{token[-4:]}"


def resolve_credential(*, now_ms: int | None = None) -> Credential:
    """Resolve the credential to use; ``OCGO_TOKEN`` wins over the DB."""
    env_token = os.environ.get(_ENV_TOKEN, "").strip()
    if env_token:
        return Credential(token=env_token, source=_SOURCE_ENV)
    return _resolve_db_credential(now_ms=now_ms)


def _resolve_db_credential(*, now_ms: int | None = None) -> Credential:
    db_path = Path(os.environ.get(_ENV_DB) or default_db_path()).expanduser()
    if not db_path.is_file():
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    token, expires_ms = _read_db_row(db_path)
    if expires_ms is not None:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if expires_ms <= now:
            raise CredentialError(EXPIRED_MESSAGE)
    return Credential(token=token, source=_SOURCE_DB, expires_ms=expires_ms)


def _read_db_row(db_path: Path) -> tuple[str, int | None]:
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            # Prefer the credential that ``opencode auth switch`` marked active.
            row = connection.execute(_ACTIVE_QUERY).fetchone()
            if not row:
                row = connection.execute(_FALLBACK_QUERY).fetchone()
    except sqlite3.Error as exc:
        raise CredentialError(NO_CREDENTIAL_MESSAGE) from exc
    if not row or not row[0]:
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    try:
        value = json.loads(row[0])
        token = value["access"]
    except (TypeError, ValueError, KeyError) as exc:
        raise CredentialError(NO_CREDENTIAL_MESSAGE) from exc
    if not isinstance(token, str) or not token.strip():
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    return token.strip(), _parse_expiry(value.get("expires"))


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
