"""Shared helpers for the ocgo test suite."""

from __future__ import annotations

import os
import tempfile
import warnings
from contextlib import contextmanager

_PREFERRED_TMP = "/tmp/opencode"


def quarantine_gc_warnings() -> None:
    """Quarantine the Python 3.14 urllib/tempfile GC ResourceWarning.

    Python 3.14 composes ``urllib.error.HTTPError`` on top of tempfile's
    wrapper (``urllib/response.py: addbase(tempfile._TemporaryFileWrapper)``),
    so a test fixture that builds an HTTPError without closing it warns
    "Implicitly cleaning up ..." whenever the garbage collector later reaches
    it — potentially inside a test that asserts stderr is empty. The leaking
    fixtures live in test_api.py, outside this work unit's surfaces; closing
    them is a separate cleanup.

    Callers that capture stderr must re-assert this filter: unittest's runner
    installs a blanket ``default`` filter around the whole run
    (unittest/main.py), which would otherwise precede the imported copy.
    """
    warnings.filterwarnings(
        "ignore",
        message=r"Implicitly cleaning up",
        category=ResourceWarning,
    )


quarantine_gc_warnings()


@contextmanager
def temp_dir():
    """TemporaryDirectory, preferring /tmp/opencode when it exists."""
    base = _PREFERRED_TMP if os.path.isdir(_PREFERRED_TMP) else None
    with tempfile.TemporaryDirectory(dir=base) as path:
        yield path
