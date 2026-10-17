"""Read-only credential discovery for OpenCode Go.

Resolution order:

1. ``OCGO_TOKEN`` environment variable (manual/testing override).
2. The local OpenCode store: the database (``opencode.db``), opened
   read-only, then the legacy ``auth.json`` login file. The
   preferred ``opencode*`` credential wins — ``opencode-go`` first, then
   ``opencode``, then any other ``opencode*`` id — active rows before
   inactive ones and the newest ``time_updated`` first inside a tier.
3. The user-supplied fallback API key file
   (``$XDG_CONFIG_HOME/ocgo/api.key``, mode ``0600``), read only when the
   local store has no usable (non-expired) credential.

The effective OpenCode data directory is the ``OCGO_DATA_DIR`` environment
variable, then ``opencode_data_dir`` in ``$XDG_CONFIG_HOME/ocgo/config.json``,
then ``$XDG_DATA_HOME/opencode`` (``~/.local/share/opencode``). ``OCGO_DB``
overrides the database path directly.

Credential values tolerate the shapes OpenCode v2 writes: one optional
``value`` wrapper around the credential object, the token in ``access``
(oauth) or ``key`` (api key), an optional ``type``, and a sane ms-epoch
``expires``. Resolved credentials carry a ``kind`` (``"oauth"`` or
``"api"``) so callers route to the matching usage endpoint.

The token is never logged, printed in full, cached, or written anywhere.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
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
_ENV_DATA_DIR = "OCGO_DATA_DIR"
_SOURCE_ENV = "OCGO_TOKEN environment"
_SOURCE_DB = "OpenCode local database"
_SOURCE_AUTH_JSON = "OpenCode auth.json file"
_SOURCE_API_KEY = "Configured API key"
_CONFIG_FILENAME = "config.json"
_API_KEY_FILENAME = "api.key"

KIND_OAUTH = "oauth"
KIND_API = "api"

# OpenCode-owned integrations: `opencode-go` preferred over `opencode` over
# any other `opencode*` id (the same ranking `_integration_rank` applies to
# legacy auth.json keys).
_ACCEPTED_IDS = "integration_id GLOB 'opencode*'"
_PREFERENCE_ORDER = (
    "ORDER BY CASE integration_id "
    "WHEN 'opencode-go' THEN 0 "
    "WHEN 'opencode' THEN 1 "
    "ELSE 2 END, active DESC, time_updated DESC"
)
_SELECT_QUERY = (
    f"SELECT value FROM credential WHERE {_ACCEPTED_IDS} "
    f"{_PREFERENCE_ORDER} LIMIT 1"
)
_EXISTS_QUERY = f"SELECT 1 FROM credential WHERE {_ACCEPTED_IDS} LIMIT 1"


def _integration_rank(integration_id: str) -> int | None:
    """Preference rank for an integration id: Go, Console, other, or none."""
    if integration_id == "opencode-go":
        return 0
    if integration_id == "opencode":
        return 1
    if integration_id.startswith("opencode"):
        return 2
    return None


class CredentialError(Exception):
    """No usable credential is available."""


@dataclass(frozen=True)
class Credential:
    """A resolved token plus where it came from (never the full value)."""

    token: str = field(repr=False)
    source: str
    expires_ms: int | None = None
    kind: str = KIND_OAUTH

    @property
    def expires_at(self) -> datetime | None:
        if self.expires_ms is None:
            return None
        try:
            return datetime.fromtimestamp(self.expires_ms / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None


def config_path() -> Path:
    """``$XDG_CONFIG_HOME/ocgo/config.json`` or the ``~/.config`` fallback."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "ocgo" / _CONFIG_FILENAME


def read_config() -> dict:
    """Read ``config.json``; missing, unreadable, or malformed reads as ``{}``."""
    try:
        payload = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_configured_data_dir() -> str | None:
    """The configured OpenCode data directory, or ``None`` when unset."""
    value = read_config().get("opencode_data_dir")
    if isinstance(value, str) and value.strip():
        return value
    return None


def set_configured_data_dir(path: str | None) -> None:
    """Persist (or clear) ``opencode_data_dir`` in ``config.json``.

    The write merges with any existing keys and is atomic: a temp file in
    the same directory, then ``os.replace``. ``None`` removes the key.
    """
    payload = read_config()
    if path is None:
        payload.pop("opencode_data_dir", None)
    else:
        payload["opencode_data_dir"] = path
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".ocgo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _effective_data_dir() -> Path:
    """OCGO_DATA_DIR, then the configured dir, then the XDG default."""
    env_dir = os.environ.get(_ENV_DATA_DIR, "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    configured = get_configured_data_dir()
    if configured is not None:
        return Path(configured).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "opencode"


def default_db_path() -> Path:
    """``<data dir>/opencode.db`` under the effective OpenCode data directory."""
    return _effective_data_dir() / "opencode.db"


def default_auth_json_path() -> Path:
    """``<data dir>/auth.json`` under the effective OpenCode data directory."""
    return _effective_data_dir() / "auth.json"


def _effective_db_path() -> Path:
    """The database the module reads: the ``OCGO_DB`` override or the default."""
    return Path(os.environ.get(_ENV_DB) or default_db_path()).expanduser()


def _api_key_path() -> Path:
    """``$XDG_CONFIG_HOME/ocgo/api.key`` beside ``config.json``."""
    return config_path().parent / _API_KEY_FILENAME


def mask_token(token: str) -> str:
    """Return a hint that can never reveal the full token."""
    if len(token) <= 12:
        return "…"
    return f"{token[:6]}…{token[-4:]}"


def store_api_key(token: str) -> str:
    """Store the fallback API key with ``0600`` permissions; returns a hint.

    The write is atomic (temp file in the same directory, then
    ``os.replace``, then ``chmod 0600``). A blank token raises
    :class:`CredentialError`.
    """
    value = token.strip()
    if not value:
        raise CredentialError("no API key provided")
    target = _api_key_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".ocgo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return mask_token(value)


def read_api_key() -> str | None:
    """The stored fallback API key, or ``None`` when absent or blank."""
    try:
        text = _api_key_path().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    token = text.strip()
    return token or None


def has_api_key() -> bool:
    """True when a non-blank fallback API key is stored."""
    return read_api_key() is not None


def clear_api_key() -> bool:
    """Remove the stored fallback API key; ``True`` when one was removed."""
    try:
        _api_key_path().unlink()
    except OSError:
        return False
    return True


def resolve_credential(*, now_ms: int | None = None) -> Credential:
    """Resolve the credential to use.

    ``OCGO_TOKEN`` wins, then the local OpenCode store (database, then
    legacy ``auth.json``), then the stored fallback API key. The key is
    used only when the store has no usable credential (missing or
    expired); otherwise the store's :class:`CredentialError` is re-raised.
    """
    env_token = os.environ.get(_ENV_TOKEN, "").strip()
    if env_token:
        return Credential(token=env_token, source=_SOURCE_ENV, kind=KIND_OAUTH)
    try:
        return _resolve_stored_credential(now_ms=now_ms)
    except CredentialError:
        token = read_api_key()
        if token is None:
            raise
        return Credential(token=token, source=_SOURCE_API_KEY, kind=KIND_API)


def _resolve_stored_credential(*, now_ms: int | None = None) -> Credential:
    """The local store credential: database row first, then the legacy file."""
    try:
        return _resolve_db_credential(now_ms=now_ms)
    except CredentialError:
        legacy = _read_legacy_login()
        if legacy is None:
            raise
        _raise_if_expired(legacy.expires_ms, now_ms)
        return legacy


def _read_legacy_login() -> Credential | None:
    """Read the legacy ``auth.json`` login; any problem reads as "no login".

    The file is keyed by integration id, mirroring OpenCode's own migration:
    keys match the same ids as the database (``opencode-go``, ``opencode``,
    or any other ``opencode*`` id after trimming trailing ``/``), preferred
    in that order and otherwise kept in file order. Entries accept the same
    tolerant shapes as the database values.
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
    best_rank = None
    for key, value in payload.items():
        rank = _integration_rank(key.rstrip("/"))
        if rank is None:
            continue
        if best_rank is None or rank < best_rank:
            entry = value
            best_rank = rank
    if not isinstance(entry, dict):
        return None
    fields = _credential_fields(entry)
    if fields is None:
        return None
    token, expires_ms, kind = fields
    return Credential(
        token=token, source=_SOURCE_AUTH_JSON, expires_ms=expires_ms, kind=kind
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


def _unwrap_value(payload: object) -> object:
    """Descend once into a dict ``value`` wrapper when present."""
    if isinstance(payload, dict):
        wrapper = payload.get("value")
        if isinstance(wrapper, dict):
            return wrapper
    return payload


def _credential_fields(payload: object) -> tuple[str, int | None, str] | None:
    """Extract ``(token, expires_ms, kind)`` from a credential payload.

    Tolerates one ``value`` wrapper around the credential object; the token
    is ``access`` (oauth, preferred) or ``key`` (api key) and ``type`` is
    optional. Anything that cannot yield a non-blank string token reads as
    ``None``.
    """
    payload = _unwrap_value(payload)
    if not isinstance(payload, dict):
        return None
    token = payload.get("access")
    kind = KIND_OAUTH
    if not isinstance(token, str) or not token.strip():
        token = payload.get("key")
        kind = KIND_API
    if not isinstance(token, str) or not token.strip():
        return None
    return token.strip(), _parse_expiry(payload.get("expires")), kind


def _resolve_db_credential(*, now_ms: int | None = None) -> Credential:
    db_path = _effective_db_path()
    if not db_path.is_file():
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    token, expires_ms, kind = _read_db_row(db_path)
    _raise_if_expired(expires_ms, now_ms)
    return Credential(
        token=token, source=_SOURCE_DB, expires_ms=expires_ms, kind=kind
    )


def has_stored_login() -> bool:
    """True when a credential exists: env token, a store login, or a key.

    The database check only asks whether an OpenCode-owned (``opencode*``)
    row exists, on stable columns. Rows count regardless of expiry: an
    expired login still drives the refresh messaging, and so does a legacy
    ``auth.json`` login (presence, not expiry, is the question here). A
    stored fallback API key is a login too.
    """
    if os.environ.get(_ENV_TOKEN, "").strip():
        return True
    if _db_has_stored_login():
        return True
    if _read_legacy_login() is not None:
        return True
    return has_api_key()


def _db_has_stored_login() -> bool:
    """True when the database holds at least one accepted OpenCode row."""
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

    Reports the same paths the resolution reads so a caller (CLI, frontend)
    can show them verbatim, plus the effective and configured data
    directories and the fallback API key state (hint masked). Every value is
    JSON-safe and the check never raises: an unreadable store simply reads
    as absent.
    """
    db_path = _effective_db_path()
    auth_json_path = default_auth_json_path()
    api_key = read_api_key()
    return {
        "db_path": str(db_path),
        "db_exists": db_path.is_file(),
        "auth_json_path": str(auth_json_path),
        "auth_json_exists": auth_json_path.is_file(),
        "auth_json_login": _read_legacy_login() is not None,
        "has_login": has_stored_login(),
        "data_dir": str(_effective_data_dir()),
        "configured_data_dir": get_configured_data_dir(),
        "api_key_configured": api_key is not None,
        "api_key_hint": mask_token(api_key) if api_key is not None else None,
    }


def _read_db_row(db_path: Path) -> tuple[str, int | None, str]:
    """Read the preferred credential row as ``(token, expires_ms, kind)``.

    The query follows the accepted-id preference order and, inside a tier,
    prefers the credential that ``opencode auth switch`` marked active. A row
    that cannot yield a usable token reads as no credential at all.
    """
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            row = connection.execute(_SELECT_QUERY, ()).fetchone()
    except sqlite3.Error as exc:
        raise CredentialError(NO_CREDENTIAL_MESSAGE) from exc
    if not row or not row[0]:
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError) as exc:
        raise CredentialError(NO_CREDENTIAL_MESSAGE) from exc
    fields = _credential_fields(payload)
    if fields is None:
        raise CredentialError(NO_CREDENTIAL_MESSAGE)
    return fields


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
