"""Tests for ocgo.creds (no network, temp sqlite DB only)."""

import json
import os
import sqlite3
import time
import unittest
from pathlib import Path
from unittest import mock

from _support import temp_dir
from ocgo import creds


def _write_db(path: Path, rows: list[tuple[str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE credential ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "integration_id TEXT NOT NULL, "
        "value TEXT NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO credential (integration_id, value) VALUES (?, ?)", rows
    )
    connection.commit()
    connection.close()


class CredentialResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))

    def _env(self, **values):
        """Isolate the process env and set only the given values."""
        patcher = mock.patch.dict(os.environ, values, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_env_token_wins_over_db(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"access": "db-token-1234567890"}))])
        self._env(OCGO_TOKEN="env-token", OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "env-token")
        self.assertEqual(credential.source, "OCGO_TOKEN environment")

    def test_env_token_is_stripped(self):
        self._env(OCGO_TOKEN="  spaced-token  ")
        self.assertEqual(creds.resolve_credential().token, "spaced-token")

    def test_db_token_is_read_with_expiry(self):
        expires = int(time.time() * 1000) + 3_600_000
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "db-token-abcdefgh", "expires": expires}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "db-token-abcdefgh")
        self.assertEqual(credential.source, "OpenCode local database")
        self.assertEqual(credential.expires_ms, expires)
        self.assertIsNotNone(credential.expires_at)

    def test_missing_expiry_is_allowed(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"access": "tok-abcdefgh"}))])
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertIsNone(credential.expires_ms)
        self.assertIsNone(credential.expires_at)

    def test_newest_opencode_row_wins(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                ("opencode", json.dumps({"access": "old-token"})),
                ("other", json.dumps({"access": "other-token"})),
                ("opencode", json.dumps({"access": "new-token"})),
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.resolve_credential().token, "new-token")

    def test_missing_db_file(self):
        self._env(OCGO_DB=str(self.tmp / "nope.db"))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_db_without_opencode_row(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("other", json.dumps({"access": "x"}))])
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_db_with_invalid_json(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", "{not json")])
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError):
            creds.resolve_credential()

    def test_db_json_without_access(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"refresh": "only"}))])
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError):
            creds.resolve_credential()

    def test_db_file_that_is_not_sqlite(self):
        db = self.tmp / "opencode.db"
        db.write_text("this is not a database", encoding="utf-8")
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_expired_credential(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "tok-abcdefgh", "expires": now_ms - 1}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_expires_exactly_now_is_expired(self):
        now_ms = 1_800_000_000_000
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "tok-abcdefgh", "expires": now_ms}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_expiry_nan_is_ignored(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "tok-abcdefgh", "expires": float("nan")}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertIsNone(credential.expires_ms)
        self.assertIsNone(credential.expires_at)

    def test_expiry_overflow_is_ignored(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "tok-abcdefgh", "expires": 1e30}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertIsNone(credential.expires_ms)
        self.assertIsNone(credential.expires_at)

    def test_expiry_non_numeric_string_is_ignored(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "tok-abcdefgh", "expires": "abc"}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertIsNone(credential.expires_ms)
        self.assertIsNone(credential.expires_at)


class DefaultPathTests(unittest.TestCase):
    def test_xdg_data_home_wins(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg"}, clear=True):
            self.assertEqual(
                creds.default_db_path(), Path("/xdg/opencode/opencode.db")
            )

    def test_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                creds.default_db_path(),
                Path("/home/tester/.local/share/opencode/opencode.db"),
            )


class MaskTokenTests(unittest.TestCase):
    def test_long_token_keeps_only_head_and_tail(self):
        masked = creds.mask_token("abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(masked, "abcdef…wxyz")

    def test_short_token_is_fully_hidden(self):
        self.assertEqual(creds.mask_token("short"), "…")
        self.assertEqual(creds.mask_token("twelve-chars"), "…")


class CredentialObjectTests(unittest.TestCase):
    def test_expires_at_returns_none_for_out_of_range_value(self):
        credential = creds.Credential(
            token="tok-abcdefgh", source="test", expires_ms=10**30
        )
        self.assertIsNone(credential.expires_at)

    def test_repr_does_not_expose_the_token(self):
        credential = creds.Credential(token="super-secret-token", source="test")
        self.assertNotIn("super-secret-token", repr(credential))
        self.assertIn("source='test'", repr(credential))


if __name__ == "__main__":
    unittest.main()
