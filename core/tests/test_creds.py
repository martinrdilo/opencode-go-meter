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


def _write_db(path: Path, rows: list[tuple]) -> None:
    """Create a credential table mirroring production and insert ``rows``.

    Each row is ``(integration_id, value)`` — stored with a generated id,
    ``active = 0`` and ``time_updated = 0`` — or
    ``(id, integration_id, value, active, time_updated)``.
    """
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE credential ("
        "id TEXT PRIMARY KEY, "
        "integration_id TEXT NOT NULL, "
        "value TEXT NOT NULL, "
        "active INTEGER NOT NULL DEFAULT 0, "
        "time_updated INTEGER NOT NULL DEFAULT 0)"
    )
    for index, row in enumerate(rows):
        if len(row) == 2:
            integration_id, value = row
            entry = (f"row-{index}", integration_id, value, 0, 0)
        else:
            entry = tuple(row)
        connection.execute(
            "INSERT INTO credential "
            "(id, integration_id, value, active, time_updated) "
            "VALUES (?, ?, ?, ?, ?)",
            entry,
        )
    connection.commit()
    connection.close()


class EnvTestCase(unittest.TestCase):
    """Temp dir plus an isolated process environment."""

    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))

    def _env(self, **values):
        """Isolate the process env and set only the given values."""
        patcher = mock.patch.dict(os.environ, values, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)


def _write_labelled_db(path: Path, rows: list[tuple]) -> None:
    """Create a labelled credential table mirroring production and insert ``rows``.

    Each row is ``(id, integration_id, label, value, active, time_updated)``.
    """
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE credential ("
        "id TEXT PRIMARY KEY, "
        "integration_id TEXT NOT NULL, "
        "label TEXT NOT NULL, "
        "value TEXT NOT NULL, "
        "active INTEGER NOT NULL DEFAULT 0, "
        "time_updated INTEGER NOT NULL DEFAULT 0)"
    )
    for row in rows:
        connection.execute(
            "INSERT INTO credential "
            "(id, integration_id, label, value, active, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            tuple(row),
        )
    connection.commit()
    connection.close()


class CredentialResolutionTests(EnvTestCase):
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
                ("a-old", "opencode", json.dumps({"access": "old-token"}), 0, 100),
                ("b-other", "other", json.dumps({"access": "other-token"}), 0, 300),
                ("c-new", "opencode", json.dumps({"access": "new-token"}), 0, 200),
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.resolve_credential().token, "new-token")

    def test_active_row_wins_over_newer_id_and_timestamp(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                # The active login is older and lexically smaller: the old
                # "ORDER BY id DESC" query would have picked the other row.
                (
                    "aaa-active",
                    "opencode",
                    json.dumps({"access": "active-token"}),
                    1,
                    100,
                ),
                (
                    "zzz-newer",
                    "opencode",
                    json.dumps({"access": "newer-token"}),
                    0,
                    200,
                ),
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.resolve_credential().token, "active-token")

    def test_fallback_uses_newest_time_updated_without_active(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "zzz-old",
                    "opencode",
                    json.dumps({"access": "older-token"}),
                    0,
                    100,
                ),
                (
                    "aaa-new",
                    "opencode",
                    json.dumps({"access": "newest-token"}),
                    0,
                    200,
                ),
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.resolve_credential().token, "newest-token")

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


class PinnedCredentialTests(EnvTestCase):
    """``resolve_credential(credential_id=...)`` pins the database row."""

    def test_pinned_row_wins_over_active_and_newest(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "aaa-active",
                    "opencode",
                    json.dumps({"access": "active-token-1"}),
                    1,
                    100,
                ),
                (
                    "zzz-newest",
                    "opencode",
                    json.dumps({"access": "newest-token-1"}),
                    0,
                    300,
                ),
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential(credential_id="zzz-newest")
        self.assertEqual(credential.token, "newest-token-1")
        self.assertEqual(credential.source, "OpenCode local database")
        # The auto path still follows the active row.
        self.assertEqual(creds.resolve_credential().token, "active-token-1")

    def test_pinned_row_returns_token_and_expiry(self):
        expires = int(time.time() * 1000) + 3_600_000
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "cred-pin",
                    "opencode",
                    json.dumps({"access": "pinned-token-1234", "expires": expires}),
                    0,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential(credential_id="cred-pin")
        self.assertEqual(credential.token, "pinned-token-1234")
        self.assertEqual(credential.expires_ms, expires)
        self.assertIsNotNone(credential.expires_at)

    def test_pinned_missing_row_is_actionable(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db, [("cred-1", "opencode", json.dumps({"access": "tok-1"}), 0, 100)]
        )
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(credential_id="ghost")
        self.assertEqual(
            str(caught.exception),
            "The OpenCode credential 'ghost' no longer exists in the local "
            "database — remove this account or sign in again in OpenCode.",
        )

    def test_pinned_missing_db_file_is_actionable(self):
        self._env(OCGO_DB=str(self.tmp / "nope.db"))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(credential_id="ghost")
        message = str(caught.exception)
        self.assertIn("ghost", message)
        self.assertIn("no longer exists", message)

    def test_pinned_malformed_row_is_actionable(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("cred-1", "opencode", "{not json", 0, 100)])
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(credential_id="cred-1")
        self.assertIn("no longer exists", str(caught.exception))

    def test_expired_pinned_row_uses_expired_message(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "cred-pin",
                    "opencode",
                    json.dumps({"access": "pinned-token-1234", "expires": now_ms - 1}),
                    0,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(credential_id="cred-pin", now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_env_token_still_wins_when_pinned(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db, [("cred-1", "opencode", json.dumps({"access": "db-token"}), 0, 100)]
        )
        self._env(OCGO_TOKEN="env-token", OCGO_DB=str(db))
        credential = creds.resolve_credential(credential_id="cred-1")
        self.assertEqual(credential.token, "env-token")
        self.assertEqual(credential.source, "OCGO_TOKEN environment")


class ListDbCredentialsTests(EnvTestCase):
    """``list_db_credentials`` exposes display metadata only."""

    def test_fields_metadata_and_order(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-new",
                    "opencode",
                    "New",
                    json.dumps(
                        {
                            "access": "new-access-token",
                            "metadata": {"email": "new@example.com", "orgName": "ACME"},
                        }
                    ),
                    1,
                    200,
                ),
                (
                    "cred-old",
                    "opencode",
                    "Old",
                    json.dumps({"access": "old-access-token"}),
                    0,
                    100,
                ),
            ],
        )
        self._env(OCGO_DB=str(db))
        credentials = creds.list_db_credentials()
        self.assertEqual(
            [credential.id for credential in credentials], ["cred-new", "cred-old"]
        )
        self.assertEqual(
            credentials[0],
            creds.DbCredential(
                id="cred-new",
                label="New",
                active=True,
                email="new@example.com",
                org_name="ACME",
            ),
        )
        self.assertEqual(
            credentials[1],
            creds.DbCredential(
                id="cred-old",
                label="Old",
                active=False,
                email=None,
                org_name=None,
            ),
        )

    def test_malformed_value_still_lists_the_row(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(db, [("cred-1", "opencode", "Default", "{not json", 0, 100)])
        self._env(OCGO_DB=str(db))
        credentials = creds.list_db_credentials()
        self.assertEqual(len(credentials), 1)
        self.assertEqual(credentials[0].id, "cred-1")
        self.assertEqual(credentials[0].label, "Default")
        self.assertFalse(credentials[0].active)
        self.assertIsNone(credentials[0].email)
        self.assertIsNone(credentials[0].org_name)

    def test_metadata_members_of_wrong_types_are_none(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-1",
                    "opencode",
                    "Default",
                    json.dumps(
                        {
                            "access": "token-value",
                            "metadata": {"email": 7, "orgName": None},
                        }
                    ),
                    1,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.list_db_credentials()[0]
        self.assertIsNone(credential.email)
        self.assertIsNone(credential.org_name)

    def test_non_object_metadata_is_none(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-1",
                    "opencode",
                    "Default",
                    json.dumps({"access": "token-value", "metadata": ["x"]}),
                    1,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.list_db_credentials()[0]
        self.assertIsNone(credential.email)
        self.assertIsNone(credential.org_name)

    def test_no_token_material_in_results(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-1",
                    "opencode",
                    "Default",
                    json.dumps(
                        {
                            "access": "secret-access-token",
                            "refresh": "secret-refresh-token",
                        }
                    ),
                    1,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credentials = creds.list_db_credentials()
        self.assertEqual(
            set(creds.DbCredential.__dataclass_fields__),
            {"id", "label", "active", "email", "org_name"},
        )
        rendered = " ".join(repr(credential) for credential in credentials)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("secret-refresh-token", rendered)

    def test_other_integrations_are_excluded(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-google",
                    "google",
                    "Google",
                    json.dumps({"access": "g"}),
                    1,
                    300,
                ),
                (
                    "cred-open",
                    "opencode",
                    "Open",
                    json.dumps({"access": "o"}),
                    1,
                    200,
                ),
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertEqual(
            [credential.id for credential in creds.list_db_credentials()],
            ["cred-open"],
        )

    def test_empty_table_lists_nothing(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(db, [])
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.list_db_credentials(), [])

    def test_missing_db_is_no_credential_message(self):
        self._env(OCGO_DB=str(self.tmp / "nope.db"))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.list_db_credentials()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_file_that_is_not_sqlite_is_no_credential_message(self):
        db = self.tmp / "opencode.db"
        db.write_text("this is not a database", encoding="utf-8")
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.list_db_credentials()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_db_without_the_table_is_no_credential_message(self):
        db = self.tmp / "opencode.db"
        sqlite3.connect(db).close()
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.list_db_credentials()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)


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
