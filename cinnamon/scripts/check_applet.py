#!/usr/bin/env python3
"""Static checks for the Cinnamon applet.

Validates that ``metadata.json`` and ``settings-schema.json`` parse as JSON,
that ``applet.js`` passes ``node --check``, that the metadata uuid matches the
directory name Cinnamon will load the applet from, and that ``applet.js``
defines the ``main`` entry point. Every ``imports.*`` module ``applet.js``
uses must exist in the oldest supported Cinnamon release (5.4):
``imports.ui.dialog``, for example, only exists from Cinnamon 6.4.

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


# Modules ``applet.js`` may import: checked against Cinnamon 5.4.13, the oldest
# supported release (Linux Mint 21). A new module goes in only after verifying
# it exists there ('imports.ui.dialog', for example, only exists from 6.4).
ALLOWED_UI_MODULES = frozenset(
    {"applet", "main", "modalDialog", "popupMenu", "radioButton", "settings"}
)
ALLOWED_MISC_MODULES = frozenset({"util"})
ALLOWED_ROOT_MODULES = frozenset({"mainloop"})

# Anchored to the 'const X = imports.<module>;' declaration so module names
# mentioned in comments are not matched. The guard is deliberately
# declaration-syntax only: `let`, destructuring patterns, inline uses and a
# missing semicolon are not caught (the applet uses the const form uniformly).
IMPORT_DECL_RE = re.compile(r"^\s*const\s+\w+\s*=\s*imports\.([\w.]+)\s*;", re.MULTILINE)


def _allowed_import(module: str) -> bool:
    parts = module.split(".")
    if len(parts) == 1:
        return module in ALLOWED_ROOT_MODULES
    if len(parts) == 2 and parts[0] == "gi":
        return True
    if len(parts) == 2 and parts[0] == "ui":
        return parts[1] in ALLOWED_UI_MODULES
    if len(parts) == 2 and parts[0] == "misc":
        return parts[1] in ALLOWED_MISC_MODULES
    return False


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

    for module in IMPORT_DECL_RE.findall(source):
        if _allowed_import(module):
            continue
        return fail(
            f"cinnamon/applet.js imports 'imports.{module}', which is not in "
            "the Cinnamon 5.4 allowlist; verify it exists in the oldest "
            "supported Cinnamon release, then add it to ALLOWED_UI_MODULES, "
            "ALLOWED_MISC_MODULES or ALLOWED_ROOT_MODULES in this script"
        )

    print(f"ok: cinnamon applet checks passed ({uuid})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
