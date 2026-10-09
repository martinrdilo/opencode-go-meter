#!/usr/bin/env python3
"""Static checks for the Cinnamon applet.

Validates that ``metadata.json`` and ``settings-schema.json`` parse as JSON,
that ``applet.js`` passes ``node --check``, that the metadata uuid matches the
directory name Cinnamon will load the applet from, and that ``applet.js``
defines the ``main`` entry point.

Exits non-zero with a clear message on the first failure.
"""

import json
import pathlib
import re
import subprocess
import sys

APPLET_DIR = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = APPLET_DIR.parent / "Makefile"
METADATA = APPLET_DIR / "metadata.json"
SCHEMA = APPLET_DIR / "settings-schema.json"
APPLET_JS = APPLET_DIR / "applet.js"

UUID_RE = re.compile(r"^UUID\s*:=\s*(\S+)\s*$", re.MULTILINE)
MAIN_RE = re.compile(
    r"^\s*(?:function\s+main\s*\(|(?:var|let|const)\s+main\s*=)",
    re.MULTILINE,
)


def fail(message: str) -> int:
    print(f"error: {message}")
    return 1


def makefile_uuid():
    """The name the Makefile installs the applet under, or None."""
    try:
        text = MAKEFILE.read_text(encoding="utf-8")
    except OSError:
        return None
    match = UUID_RE.search(text)
    return match.group(1) if match else None


def main() -> int:
    for path in (METADATA, SCHEMA, APPLET_JS):
        if not path.exists():
            return fail(f"{path.relative_to(APPLET_DIR.parent)} is missing")

    try:
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"cinnamon/metadata.json is not valid JSON: {exc}")

    try:
        json.loads(SCHEMA.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"cinnamon/settings-schema.json is not valid JSON: {exc}")

    if not isinstance(metadata, dict):
        return fail("cinnamon/metadata.json must be a JSON object")

    uuid = metadata.get("uuid")
    if not isinstance(uuid, str) or not uuid:
        return fail("cinnamon/metadata.json: 'uuid' must be a non-empty string")

    # Cinnamon loads the applet from a directory named after the uuid: the
    # Makefile creates that symlink in the repo layout ('cinnamon/'), and an
    # installed copy carries the uuid as its own directory name.
    if APPLET_DIR.name != uuid:
        if APPLET_DIR.name != "cinnamon":
            return fail(
                f"applet directory '{APPLET_DIR.name}' does not match the "
                f"metadata uuid '{uuid}'"
            )
        declared = makefile_uuid()
        if declared != uuid:
            return fail(
                f"the Makefile installs the applet as '{declared}', but "
                f"cinnamon/metadata.json declares uuid '{uuid}'"
            )

    try:
        result = subprocess.run(
            ["node", "--check", str(APPLET_JS)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return fail("node is required for the applet.js syntax check")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return fail(f"node --check cinnamon/applet.js failed: {detail}")

    source = APPLET_JS.read_text(encoding="utf-8")
    if not MAIN_RE.search(source):
        return fail("cinnamon/applet.js does not define a main() entry point")

    print(f"ok: cinnamon applet checks passed ({uuid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
