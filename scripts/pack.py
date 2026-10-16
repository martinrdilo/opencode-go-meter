#!/usr/bin/env python3
"""Build the release archives for the GNOME extension and the Cinnamon applet.

Both artifacts land in the gitignored ``dist/`` directory:

- ``<UUID>.shell-extension.zip`` — GNOME extension; files sit at the archive
  root (``metadata.json``, ``extension.js``, ``prefs.js``, ``stylesheet.css``,
  and ``schemas/*.gschema.xml``); ``scripts/`` and ``gschemas.compiled`` are
  excluded.
- ``<UUID>.zip`` — Cinnamon spice; files nest under ``<UUID>/``
  (``metadata.json``, ``applet.js``, ``settings-schema.json``,
  ``stylesheet.css``); ``scripts/`` is excluded.

Every required source file must exist and both metadata files must declare the
expected uuid; the script exits non-zero with a clear message on the first
failure. Archives are deterministic (sorted entries, fixed timestamps), so
repeated runs are byte-for-byte identical.

Run through ``make pack`` or directly: ``python3 scripts/pack.py``.
"""

import json
import stat
import sys
import zipfile
from pathlib import Path

UUID = "opencode-go-meter@martinrdilo"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"

GNOME_FILES = ("metadata.json", "extension.js", "prefs.js", "stylesheet.css")
CINNAMON_FILES = (
    "metadata.json",
    "applet.js",
    "settings-schema.json",
    "stylesheet.css",
)

# Fixed timestamp (the ZIP epoch): archive bytes stay independent of the clock.
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FILE_MODE = stat.S_IFREG | 0o644


class PackError(Exception):
    """A missing source file or an invalid metadata contract."""


def check_sources(base, names, label):
    """Fail on the first missing required source file."""
    missing = [name for name in names if not (base / name).is_file()]
    if missing:
        raise PackError(f"{label}: missing required file(s): {', '.join(missing)}")


def check_uuid(base, label):
    """Fail unless ``base/metadata.json`` is an object with the expected uuid."""
    metadata_path = base / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError(f"{label}: cannot read {metadata_path.name}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise PackError(f"{label}: {metadata_path.name} is not a JSON object")
    actual = metadata.get("uuid")
    if actual != UUID:
        raise PackError(
            f"{label}: {metadata_path.name} uuid is {actual!r}, expected {UUID!r}"
        )


def write_archive(path, entries):
    """Write ``(archive name, source path)`` pairs as a deterministic zip."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, source in sorted(entries, key=lambda entry: entry[0]):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FILE_MODE << 16
            archive.writestr(info, source.read_bytes())


def gnome_extension():
    """Validate the GNOME sources and list the shell-extension archive."""
    base = REPO_ROOT / "gnome"
    label = "GNOME extension"
    check_sources(base, GNOME_FILES, label)
    check_uuid(base, label)
    schemas = sorted((base / "schemas").glob("*.gschema.xml"))
    if not schemas:
        raise PackError(f"{label}: no schemas/*.gschema.xml files found")
    names = list(GNOME_FILES) + [str(schema.relative_to(base)) for schema in schemas]
    entries = [(name, base / name) for name in names]
    return DIST_DIR / f"{UUID}.shell-extension.zip", entries


def cinnamon_applet():
    """Validate the Cinnamon sources and list the spice archive."""
    base = REPO_ROOT / "cinnamon"
    label = "Cinnamon applet"
    check_sources(base, CINNAMON_FILES, label)
    check_uuid(base, label)
    entries = [(f"{UUID}/{name}", base / name) for name in CINNAMON_FILES]
    return DIST_DIR / f"{UUID}.zip", entries


def main():
    """Build both archives; return a non-zero exit code on any failure."""
    try:
        archives = [gnome_extension(), cinnamon_applet()]
    except PackError as exc:
        print(f"pack: error: {exc}", file=sys.stderr)
        return 1

    DIST_DIR.mkdir(exist_ok=True)
    for path, entries in archives:
        write_archive(path, entries)
        size = path.stat().st_size
        print(
            f"{path.relative_to(REPO_ROOT)}: {len(entries)} entries, {size} bytes"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
