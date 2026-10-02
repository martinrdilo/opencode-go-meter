#!/usr/bin/env python3
"""Heuristic guard against method/property name collisions in the extension.

Instance properties assigned as ``this.name = ...`` shadow prototype methods
defined as ``name(...) {`` — the class of bug that broke enable() in v2
(``_panelBox`` was both the panel container and the setting reader).

Exits non-zero when a collision is found.
"""

import pathlib
import re
import sys

EXTENSION_JS = pathlib.Path(__file__).resolve().parents[1] / "extension.js"

PROPERTY_RE = re.compile(r"this\.([A-Za-z_][A-Za-z0-9_]*)\s*=[^=]")
METHOD_RE = re.compile(r"^ {4}([A-Za-z_][A-Za-z0-9_]*)\([^)]*\)\s*\{", re.MULTILINE)


def main() -> int:
    text = EXTENSION_JS.read_text(encoding="utf-8")
    properties = set(PROPERTY_RE.findall(text))
    methods = set(METHOD_RE.findall(text))
    collisions = sorted(properties & methods)
    if collisions:
        for name in collisions:
            print(f"collision: '{name}' is both an instance property and a method")
        return 1
    print("ok: no method/property collisions in extension.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
