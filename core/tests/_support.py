"""Shared helpers for the ocgo test suite."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager

_PREFERRED_TMP = "/tmp/opencode"


@contextmanager
def temp_dir():
    """TemporaryDirectory, preferring /tmp/opencode when it exists."""
    base = _PREFERRED_TMP if os.path.isdir(_PREFERRED_TMP) else None
    with tempfile.TemporaryDirectory(dir=base) as path:
        yield path
