"""Accounts registry and secret storage for ocgo.

The registry (``$XDG_CONFIG_HOME/ocgo/accounts.json``) is the single source of
truth for the account list and the active account. It is fully user-owned: the
list may be empty, ``active`` may be ``null``, and every account — of kind
``api-key`` or ``opencode-db`` — can be added and removed. Absent or v1
registries materialize the seeded ``default`` (``opencode-db``) account in
memory; the next mutation writes v2 with the effective list.

Secrets are resolved in this order: the ``OCGO_TOKEN_<ID>`` environment
variable, the GNOME keyring through the ``secret-tool`` CLI, and finally an
opt-in 0600 file under ``keys_dir()``. Secret values never appear in argv,
logs, exception messages, or the registry; only masked hints are stored.

The registry targets a single-user CLI: mutations are not locked or serialized
against concurrent writers. Account hints must always be masked values
returned by :func:`store_secret`; callers must never pass a raw secret.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .creds import mask_token

DEFAULT_ACCOUNT_ID = "default"
DEFAULT_LABEL = "Default"
KIND_OPENCODE_DB = "opencode-db"
KIND_API_KEY = "api-key"
REGISTRY_VERSION = 2

_SECRET_TOOL = "secret-tool"
_SECRET_TIMEOUT = 10
_SECRET_FILE_SUFFIX = ".key"

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_UNSAFE_ID_CHARS = re.compile(r"[^a-z0-9]")

_NO_SECRET_TOOL_MESSAGE = (
    "secret-tool is not available — install libsecret-tools to use the "
    "keyring, or use the 'file' backend ('--store file')"
)


class AccountError(Exception):
    """The accounts registry or its secrets cannot be used."""


@dataclass(frozen=True)
class Account:
    """A registered account; ``hint`` is always a masked value or ``None``."""

    id: str
    label: str
    kind: str
    hint: str | None = None


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/ocgo`` or the ``~/.config/ocgo`` fallback."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "ocgo"
    return Path.home() / ".config" / "ocgo"


def registry_path() -> Path:
    """Path of the accounts registry JSON file."""
    return config_dir() / "accounts.json"


def keys_dir() -> Path:
    """Directory holding opt-in 0600 secret files."""
    return config_dir() / "keys"


def secret_file_path(account_id: str) -> Path:
    """Path of the file-backend secret for ``account_id``."""
    _require_valid_id(account_id)
    return keys_dir() / f"{account_id}{_SECRET_FILE_SUFFIX}"


def env_var_for(account_id: str) -> str:
    """``OCGO_TOKEN_<ID>``, uppercased with non-alphanumerics mapped to ``_``."""
    return f"OCGO_TOKEN_{_UNSAFE_ID_CHARS.sub('_', account_id).upper()}"


def validate_account_id(account_id: str) -> str:
    """Validate an account id (``default`` is a regular id since v2)."""
    return _require_valid_id(account_id)


def load_registry() -> dict | None:
    """Return the parsed registry, or ``None`` when it does not exist yet."""
    path = registry_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AccountError(
            f"cannot read the accounts registry at {path}: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AccountError(f"the accounts registry at {path} is corrupt: {exc}") from exc
    _validate_registry(data, path)
    return data


def _seeded_default_entry() -> dict:
    return {
        "id": DEFAULT_ACCOUNT_ID,
        "label": DEFAULT_LABEL,
        "kind": KIND_OPENCODE_DB,
        "hint": None,
    }


def _effective_registry() -> dict:
    """Return a v2 view: absent and v1 registries materialize the seeded default."""
    registry = load_registry()
    if registry is None:
        return {
            "version": REGISTRY_VERSION,
            "active": DEFAULT_ACCOUNT_ID,
            "accounts": [_seeded_default_entry()],
        }
    if registry["version"] == 1:
        return {
            "version": REGISTRY_VERSION,
            "active": registry["active"],
            "accounts": [_seeded_default_entry(), *registry["accounts"]],
        }
    return registry


def _account_from_entry(entry: dict) -> Account:
    return Account(entry["id"], entry["label"], entry["kind"], entry.get("hint"))


def _effective_active(entries: list[dict], stored: str | None) -> str | None:
    if stored is not None and any(entry["id"] == stored for entry in entries):
        return stored
    return entries[0]["id"] if entries else None


def list_accounts() -> tuple[list[Account], str | None]:
    """Return ``(accounts, active_id)``.

    ``active_id`` is a listed id, else the first account's id, else ``None``.
    """
    registry = _effective_registry()
    entries = [_account_from_entry(entry) for entry in registry["accounts"]]
    active = _effective_active(registry["accounts"], registry["active"])
    return entries, active


def get_active_id() -> str | None:
    """Return the active account id, or ``None`` when no account is listed."""
    return list_accounts()[1]


def add_account(
    account_id: str,
    label: str,
    *,
    kind: str = KIND_API_KEY,
    hint: str | None = None,
) -> Account:
    """Register an account (``api-key`` or ``opencode-db``) and return it.

    When the current effective list is empty the added account becomes active.
    """
    _require_valid_id(account_id)
    if kind not in (KIND_API_KEY, KIND_OPENCODE_DB):
        raise AccountError(f"unsupported account kind {kind!r}")
    if not isinstance(label, str) or not label.strip():
        raise AccountError("the account label must be a non-empty string")
    if hint is not None and not isinstance(hint, str):
        raise AccountError("the account hint must be a string or None")
    if kind == KIND_OPENCODE_DB and hint is not None:
        raise AccountError("opencode-db accounts cannot have a hint")
    registry = _effective_registry()
    if any(entry["id"] == account_id for entry in registry["accounts"]):
        raise AccountError(f"account '{account_id}' already exists")
    current_active = _effective_active(registry["accounts"], registry["active"])
    entry = {
        "id": account_id,
        "label": label.strip(),
        "kind": kind,
        "hint": hint,
    }
    registry["accounts"].append(entry)
    registry["active"] = current_active if current_active is not None else account_id
    _save_registry(registry)
    return Account(account_id, entry["label"], kind, hint)


def remove_account(account_id: str) -> None:
    """Remove any account, including the seeded default.

    The secret of an ``api-key`` account is deleted before the registry entry:
    a real delete failure aborts the removal and leaves the registry untouched.
    ``opencode-db`` accounts have no secret. The active account falls back to
    the first remaining account, or ``None`` when none remain.
    """
    _require_valid_id(account_id)
    registry = _effective_registry()
    entry = next(
        (item for item in registry["accounts"] if item["id"] == account_id), None
    )
    if entry is None:
        raise AccountError(f"account '{account_id}' does not exist")
    if entry["kind"] == KIND_API_KEY:
        delete_secret(account_id)
    current_active = _effective_active(registry["accounts"], registry["active"])
    remaining = [item for item in registry["accounts"] if item["id"] != account_id]
    registry["accounts"] = remaining
    if current_active == account_id:
        registry["active"] = remaining[0]["id"] if remaining else None
    else:
        registry["active"] = current_active
    _save_registry(registry)


def set_active(account_id: str) -> None:
    """Switch the active account; the id must be listed in the registry."""
    _require_valid_id(account_id)
    registry = _effective_registry()
    if not any(entry["id"] == account_id for entry in registry["accounts"]):
        raise AccountError(f"account '{account_id}' does not exist")
    registry["active"] = account_id
    _save_registry(registry)


def update_hint(account_id: str, hint: str | None) -> Account:
    """Replace an account's masked hint and return the updated account.

    ``hint`` must come from :func:`store_secret`; never pass a raw secret.
    ``opencode-db`` accounts cannot have a hint.
    """
    _require_valid_id(account_id)
    normalized: str | None = None
    if isinstance(hint, str):
        normalized = hint.strip() or None
    elif hint is not None:
        raise AccountError("the account hint must be a string or None")
    registry = _effective_registry()
    for entry in registry["accounts"]:
        if entry["id"] == account_id:
            if entry["kind"] == KIND_OPENCODE_DB and normalized is not None:
                raise AccountError(
                    f"account '{account_id}' uses the OpenCode login and has no hint"
                )
            entry["hint"] = normalized
            _save_registry(registry)
            return _account_from_entry(entry)
    raise AccountError(f"account '{account_id}' does not exist")


def secret_available() -> bool:
    """True when ``secret-tool`` is resolvable on PATH."""
    return shutil.which(_SECRET_TOOL) is not None


def store_secret(account_id: str, secret: str, *, backend: str = "auto") -> str:
    """Store a secret and return its masked hint.

    The selected backend becomes authoritative: the other backend's copy is
    removed before writing ("move" semantics). Rotating to ``file`` verifies
    with a keyring lookup that the keyring copy is gone and aborts with
    ``AccountError`` when a stale copy is still visible; a clear that cannot
    be verified (the lookup itself failing) stays best-effort. The caller
    registers the account first; this function only touches secret storage.
    Backends: ``auto`` (keyring, error when unavailable), ``keyring`` and
    ``file`` (0600 file under ``keys_dir()``).
    """
    _require_valid_id(account_id)
    if not isinstance(secret, str) or not secret.strip():
        raise AccountError("the secret must be a non-empty string")
    secret = secret.strip()
    if backend == "auto":
        if not secret_available():
            raise AccountError(_NO_SECRET_TOOL_MESSAGE)
        backend = "keyring"
    if backend == "keyring":
        if not secret_available():
            raise AccountError(_NO_SECRET_TOOL_MESSAGE)
        _remove_secret_file(account_id)
        _keyring_store(account_id, secret)
    elif backend == "file":
        _clear_keyring_secret(account_id)
        remaining = _keyring_lookup(account_id)
        if remaining:
            raise AccountError(
                f"the keyring entry for account '{account_id}' could not be "
                "cleared and would shadow the file store; no changes were made"
            )
        _write_secret_file(account_id, secret)
    else:
        raise AccountError(
            f"unknown secret backend {backend!r}; use 'auto', 'keyring', or 'file'"
        )
    return mask_token(secret)


def read_secret(account_id: str) -> str:
    """Resolve a secret: env var, then keyring, then the 0600 file backend."""
    _require_valid_id(account_id)
    env_value = os.environ.get(env_var_for(account_id), "").strip()
    if env_value:
        return env_value
    if secret_available():
        keyring_value = _keyring_lookup(account_id)
        if keyring_value:
            return keyring_value
    file_value = _read_secret_file(account_id)
    if file_value:
        return file_value
    raise AccountError(
        f"no secret found for account '{account_id}' — run "
        f"'ocgo account set-key {account_id}' or set {env_var_for(account_id)}"
    )


def delete_secret(account_id: str) -> None:
    """Clear the keyring and file backends; absence is not an error."""
    _require_valid_id(account_id)
    _clear_keyring_secret(account_id)
    _remove_secret_file(account_id)


def _clear_keyring_secret(account_id: str) -> None:
    """Best-effort keyring clear; absence and failure are indistinguishable."""
    if secret_available():
        _keyring_clear(account_id)


def _remove_secret_file(account_id: str) -> None:
    """Delete the file-backend secret; missing is fine, real errors raise."""
    path = secret_file_path(account_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise AccountError(f"cannot remove the secret file at {path}: {exc}") from exc


def has_secret(account_id: str) -> bool:
    """True when any backend (env, keyring, or file) holds a secret.

    An unreadable-but-present file raises ``AccountError`` instead of
    masquerading as "no secret".
    """
    _require_valid_id(account_id)
    if os.environ.get(env_var_for(account_id), "").strip():
        return True
    if secret_available() and _keyring_lookup(account_id):
        return True
    return _read_secret_file(account_id) is not None


def _require_valid_id(account_id: str) -> str:
    if not isinstance(account_id, str) or not _ID_PATTERN.match(account_id):
        raise AccountError(
            f"invalid account id {account_id!r}: expected 1-64 characters "
            "matching [a-z0-9][a-z0-9._-]*"
        )
    return account_id


def _registry_error(path: Path, detail: str) -> AccountError:
    return AccountError(f"the accounts registry at {path} is malformed: {detail}")


def _validate_registry(data: object, path: Path) -> None:
    if not isinstance(data, dict):
        raise _registry_error(path, "expected a JSON object")
    version = data.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in (1, 2)
    ):
        raise _registry_error(path, f"unsupported version {version!r}")
    active = data.get("active")
    if version == 1:
        if not isinstance(active, str) or not _ID_PATTERN.match(active):
            raise _registry_error(
                path, f"'active' must be a valid account id, got {active!r}"
            )
    elif active is not None and (
        not isinstance(active, str) or not _ID_PATTERN.match(active)
    ):
        raise _registry_error(
            path, f"'active' must be a valid account id or null, got {active!r}"
        )
    entries = data.get("accounts")
    if not isinstance(entries, list):
        raise _registry_error(path, "'accounts' must be a list")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        _validate_entry(entry, index, seen, path, version)


def _validate_entry(
    entry: object, index: int, seen: set[str], path: Path, version: int
) -> None:
    if not isinstance(entry, dict):
        raise _registry_error(path, f"account #{index} is not an object")
    account_id = entry.get("id")
    if not isinstance(account_id, str) or not _ID_PATTERN.match(account_id):
        raise _registry_error(path, f"account #{index} has an invalid id {account_id!r}")
    if version == 1 and account_id == DEFAULT_ACCOUNT_ID:
        raise _registry_error(path, "the reserved 'default' account must not be stored")
    if account_id in seen:
        raise _registry_error(path, f"duplicate account id {account_id!r}")
    seen.add(account_id)
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        raise _registry_error(path, f"account '{account_id}' has an invalid label")
    kind = entry.get("kind")
    allowed = (KIND_API_KEY,) if version == 1 else (KIND_API_KEY, KIND_OPENCODE_DB)
    if kind not in allowed:
        raise _registry_error(
            path, f"account '{account_id}' has an unsupported kind {kind!r}"
        )
    hint = entry.get("hint")
    if hint is not None and not isinstance(hint, str):
        raise _registry_error(path, f"account '{account_id}' has an invalid hint")
    if kind == KIND_OPENCODE_DB and hint is not None:
        raise _registry_error(
            path, f"account '{account_id}' is opencode-db and cannot have a hint"
        )


def _save_registry(data: dict) -> None:
    path = registry_path()
    try:
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        _atomic_write_text(path, payload)
    except OSError as exc:
        raise AccountError(
            f"cannot write the accounts registry at {path}: {exc}"
        ) from exc


def _write_secret_file(account_id: str, secret: str) -> None:
    path = secret_file_path(account_id)
    try:
        _atomic_write_text(path, secret + "\n")
    except OSError as exc:
        raise AccountError(f"cannot write the secret file at {path}: {exc}") from exc


def _read_secret_file(account_id: str) -> str | None:
    """Read the file backend; a missing file is ``None``, a read error raises."""
    path = secret_file_path(account_id)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AccountError(
            f"cannot read the secret file at {path} for account "
            f"'{account_id}': {exc}"
        ) from exc
    return text.strip() or None


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError as exc:
        raise AccountError(f"cannot restrict permissions on {path}: {exc}") from exc


def _atomic_write_text(target: Path, text: str) -> None:
    """Atomically write ``text``: temp file in the same dir, then ``os.replace``."""
    _ensure_private_dir(target.parent)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".ocgo-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1  # ownership transferred to the file object
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _redact(text: str, secret: str) -> str:
    """Best-effort removal of the secret from diagnostic text."""
    if not secret:
        return text
    return text.replace(secret, "[redacted]").strip()


def _keyring_store(account_id: str, secret: str) -> None:
    argv = [
        _SECRET_TOOL,
        "store",
        "--label",
        f"ocgo {account_id}",
        "service",
        "ocgo",
        "account",
        account_id,
    ]
    try:
        result = subprocess.run(
            argv,
            input=secret,
            capture_output=True,
            text=True,
            timeout=_SECRET_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = _redact(str(exc), secret)
        raise AccountError(
            f"secret-tool could not store the secret for account "
            f"'{account_id}': {detail}"
        ) from exc
    if result.returncode != 0:
        detail = _redact(result.stderr, secret)
        message = (
            f"secret-tool could not store the secret for account "
            f"'{account_id}' (exit {result.returncode})"
        )
        if detail:
            message += f": {detail}"
        raise AccountError(message)


def _keyring_lookup(account_id: str) -> str | None:
    argv = [_SECRET_TOOL, "lookup", "service", "ocgo", "account", account_id]
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=_SECRET_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _keyring_clear(account_id: str) -> None:
    argv = [_SECRET_TOOL, "clear", "service", "ocgo", "account", account_id]
    try:
        subprocess.run(argv, capture_output=True, timeout=_SECRET_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        pass
