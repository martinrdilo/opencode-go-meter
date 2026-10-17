"""Tests for ocgo.cache (temp dirs only, no network)."""

import os
import unittest
from pathlib import Path
from unittest import mock

from _support import temp_dir
from ocgo import cache


class CachePathTests(unittest.TestCase):
    def test_xdg_cache_home_wins(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg-cache"}, clear=True):
            self.assertEqual(cache.cache_path(), Path("/xdg-cache/ocgo/status.json"))

    def test_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                cache.cache_path(), Path("/home/tester/.cache/ocgo/status.json")
            )

    def test_no_account_argument(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg-cache"}, clear=True):
            with self.assertRaises(TypeError):
                cache.cache_path("work")


class RemovedAccountSurfaceTests(unittest.TestCase):
    """The per-account cache surface is gone with the registry (T2)."""

    def test_remove_account_cache_is_gone(self):
        self.assertFalse(hasattr(cache, "remove_account_cache"))


class CacheIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))

    def test_load_missing_returns_none(self):
        self.assertIsNone(cache.load(self.tmp / "status.json"))

    def test_save_then_load_round_trip(self):
        path = self.tmp / "nested" / "status.json"
        data = {"schema": 1, "windows": {}}
        returned = cache.save(data, path)
        self.assertEqual(returned, path)
        self.assertEqual(cache.load(path), data)
        self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_save_leaves_no_temp_files(self):
        path = self.tmp / "status.json"
        cache.save({"schema": 1}, path)
        self.assertEqual([entry.name for entry in self.tmp.iterdir()], ["status.json"])

    def test_save_cleans_up_when_replace_fails(self):
        path = self.tmp / "status.json"
        with mock.patch("ocgo.cache.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                cache.save({"schema": 1}, path)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_load_corrupt_cache_raises(self):
        path = self.tmp / "status.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(cache.CacheError):
            cache.load(path)

    def test_load_non_object_raises(self):
        path = self.tmp / "status.json"
        path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(cache.CacheError):
            cache.load(path)

    def test_raw_text_is_verbatim(self):
        path = self.tmp / "status.json"
        raw = '{\n  "schema": 1\n}\n'
        path.write_text(raw, encoding="utf-8")
        self.assertEqual(cache.raw_text(path), raw)

    def test_raw_text_missing_is_friendly(self):
        with self.assertRaises(cache.CacheError) as caught:
            cache.raw_text(self.tmp / "status.json")
        self.assertIn("ocgo refresh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
