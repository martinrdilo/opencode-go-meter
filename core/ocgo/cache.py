"""JSON cache for the latest usage snapshot (schema v1, atomic writes)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1
_FILENAME = "status.json"


class CacheError(Exception):
    """The cache cannot be read."""


def cache_path() -> Path:
    """``$XDG_CACHE_HOME/ocgo/status.json`` or the ``~/.cache`` fallback."""
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home) / "ocgo" / _FILENAME
    return Path.home() / ".cache" / "ocgo" / _FILENAME


def raw_text(path: Path | None = None) -> str:
    """Return the cache file verbatim (used by ``status --json``)."""
    target = path or cache_path()
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CacheError(f"no cache at {target} — run 'ocgo refresh' first") from exc
    except OSError as exc:
        raise CacheError(f"cannot read cache at {target}: {exc}") from exc


def load(path: Path | None = None) -> dict | None:
    """Return the parsed cache, or ``None`` when it does not exist yet."""
    target = path or cache_path()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CacheError(f"cannot read cache at {target}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CacheError(f"cache at {target} is corrupt: {exc}") from exc
    if not isinstance(data, dict):
        raise CacheError(f"cache at {target} has an unexpected shape")
    return data


def save(data: dict, path: Path | None = None) -> Path:
    """Atomically write the cache: temp file in the same dir, then ``os.replace``."""
    target = path or cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".ocgo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
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
    return target
