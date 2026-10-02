"""Tests for ocgo.cache (temp dirs only, no network)."""

import os
import unittest
from pathlib import Path
from unittest import mock

from _support import temp_dir
from ocgo import accounts, cache


class CachePathTests(unittest.TestCase):
    def test_xdg_cache_home_wins(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg-cache"}, clear=True):
            self.assertEqual(cache.cache_path(), Path("/xdg-cache/ocgo/status.json"))

    def test_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                cache.cache_path(), Path("/home/tester/.cache/ocgo/status.json")
            )


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


class CacheAccountPathTests(unittest.TestCase):
    def test_default_and_none_keep_the_legacy_path(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg-cache"}, clear=True):
            self.assertEqual(cache.cache_path(), Path("/xdg-cache/ocgo/status.json"))
            self.assertEqual(
                cache.cache_path("default"), Path("/xdg-cache/ocgo/status.json")
            )

    def test_named_account_path(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg-cache"}, clear=True):
            self.assertEqual(
                cache.cache_path("work"),
                Path("/xdg-cache/ocgo/accounts/work/status.json"),
            )

    def test_named_account_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                cache.cache_path("work"),
                Path("/home/tester/.cache/ocgo/accounts/work/status.json"),
            )

    def test_invalid_id_is_rejected(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg-cache"}, clear=True):
            with self.assertRaises(accounts.AccountError):
                cache.cache_path("../escape")


class RemoveAccountCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))
        patcher = mock.patch.dict(
            os.environ, {"XDG_CACHE_HOME": str(self.tmp)}, clear=True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_removes_file_and_empty_dir(self):
        path = cache.cache_path("work")
        cache.save({"schema": 1}, path)
        cache.remove_account_cache("work")
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_ignores_absence(self):
        cache.remove_account_cache("work")

    def test_keeps_other_account_caches(self):
        work = cache.cache_path("work")
        personal = cache.cache_path("personal")
        cache.save({"schema": 1}, work)
        cache.save({"schema": 1}, personal)
        cache.remove_account_cache("work")
        self.assertFalse(work.exists())
        self.assertTrue(personal.exists())

    def test_never_touches_the_legacy_cache(self):
        legacy = cache.cache_path()
        cache.save({"schema": 1}, legacy)
        cache.remove_account_cache("default")
        self.assertTrue(legacy.exists())


if __name__ == "__main__":
    unittest.main()
