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

_KEY = "oc_sk_test_abcdefghijklmnop1234"


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


def _write_auth_json(root: Path, payload: object) -> Path:
    """Write an XDG-style legacy ``opencode/auth.json`` under ``root``."""
    path = root / "opencode" / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class EnvTestCase(unittest.TestCase):
    """Temp dir plus an isolated process environment.

    The base environment points every XDG directory (and ``HOME``) inside the
    temp dir so no test can read the real machine's config, cache, or stores.
    """

    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))

    def _env(self, **values):
        """Isolate the process env and set only the base values plus overrides."""
        base = {
            "HOME": str(self.tmp / "home"),
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "XDG_DATA_HOME": str(self.tmp / "data"),
        }
        base.update(values)
        patcher = mock.patch.dict(os.environ, base, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _api_key_path(self) -> Path:
        """The stored fallback API key path under the isolated config home."""
        return creds.config_path().parent / "api.key"


class CredentialResolutionTests(EnvTestCase):
    def test_env_token_wins_over_db(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"access": "db-token-1234567890"}))])
        self._env(OCGO_TOKEN="env-token", OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "env-token")
        self.assertEqual(credential.source, "OCGO_TOKEN environment")
        self.assertEqual(credential.kind, "oauth")

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
        self.assertEqual(credential.kind, "oauth")
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

    def test_opencode_go_row_resolves_with_expiry(self):
        expires = int(time.time() * 1000) + 3_600_000
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode-go",
                    json.dumps(
                        {
                            "type": "oauth",
                            "access": "go-token-1234",
                            "expires": expires,
                        }
                    ),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "go-token-1234")
        self.assertEqual(credential.source, "OpenCode local database")
        self.assertEqual(credential.expires_ms, expires)

    def test_opencode_go_wins_over_active_opencode(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "go-cred",
                    "opencode-go",
                    json.dumps({"access": "go-token-1234"}),
                    0,
                    100,
                ),
                (
                    "console-cred",
                    "opencode",
                    json.dumps({"access": "console-token-1"}),
                    1,
                    300,
                ),
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.resolve_credential().token, "go-token-1234")

    def test_other_opencode_prefixed_row_resolves(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode-x", json.dumps({"access": "prefixed-token"}))])
        self._env(OCGO_DB=str(db))
        self.assertEqual(creds.resolve_credential().token, "prefixed-token")

    def test_value_wrapper_row_resolves(self):
        expires = int(time.time() * 1000) + 3_600_000
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps(
                        {
                            "value": {
                                "type": "oauth",
                                "access": "wrapped-token-1",
                                "expires": expires,
                            }
                        }
                    ),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "wrapped-token-1")
        self.assertEqual(credential.kind, "oauth")
        self.assertEqual(credential.expires_ms, expires)

    def test_api_key_row_resolves_without_expiry(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [("opencode-go", json.dumps({"type": "api", "key": "row-api-key-1"}))],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "row-api-key-1")
        self.assertEqual(credential.source, "OpenCode local database")
        self.assertEqual(credential.kind, "api")
        self.assertIsNone(credential.expires_ms)

    def test_key_token_without_type_resolves_as_api(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"key": "untyped-key-1"}))])
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "untyped-key-1")
        self.assertEqual(credential.kind, "api")

    def test_access_wins_over_key_when_both_are_present(self):
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "access-token-1", "key": "key-token-1"}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "access-token-1")
        self.assertEqual(credential.kind, "oauth")

    def test_expired_opencode_go_row_raises_the_expired_message(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode-go",
                    json.dumps({"access": "go-token-1234", "expires": now_ms - 1}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

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


class FallbackApiKeyResolutionTests(EnvTestCase):
    """The stored API key backs the local store up when it has no login."""

    def test_stored_key_resolves_when_the_store_is_missing(self):
        self._env()
        creds.store_api_key(_KEY)
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, _KEY)
        self.assertEqual(credential.source, "Configured API key")
        self.assertEqual(credential.kind, "api")
        self.assertIsNone(credential.expires_ms)
        self.assertIsNone(credential.expires_at)

    def test_store_login_wins_over_the_stored_key(self):
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"access": "db-token-1"}))])
        self._env(OCGO_DB=str(db))
        creds.store_api_key(_KEY)
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "db-token-1")
        self.assertEqual(credential.source, "OpenCode local database")
        self.assertEqual(credential.kind, "oauth")

    def test_legacy_login_wins_over_the_stored_key(self):
        _write_auth_json(
            self.tmp, {"opencode": {"type": "oauth", "access": "legacy-token-1"}}
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        creds.store_api_key(_KEY)
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "legacy-token-1")
        self.assertEqual(credential.source, "OpenCode auth.json file")

    def test_expired_database_login_falls_back_to_the_stored_key(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "db-token-1", "expires": now_ms - 1}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        creds.store_api_key(_KEY)
        credential = creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(credential.token, _KEY)
        self.assertEqual(credential.source, "Configured API key")
        self.assertEqual(credential.kind, "api")

    def test_expired_legacy_login_falls_back_to_the_stored_key(self):
        now_ms = int(time.time() * 1000)
        _write_auth_json(
            self.tmp,
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-token-1",
                    "expires": now_ms - 1,
                }
            },
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        creds.store_api_key(_KEY)
        credential = creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(credential.token, _KEY)
        self.assertEqual(credential.kind, "api")

    def test_env_token_wins_over_the_stored_key(self):
        self._env(OCGO_TOKEN="env-token")
        creds.store_api_key(_KEY)
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "env-token")
        self.assertEqual(credential.kind, "oauth")

    def test_no_store_and_no_stored_key_raises_the_store_error(self):
        self._env()
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_expired_login_without_a_stored_key_raises_expired(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode.db"
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "db-token-1", "expires": now_ms - 1}),
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_ocgo_data_dir_points_at_the_legacy_store(self):
        base = self.tmp / "custom"
        _write_auth_json(
            base, {"opencode": {"type": "oauth", "access": "custom-access-1"}}
        )
        self._env(OCGO_DATA_DIR=str(base / "opencode"))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "custom-access-1")
        self.assertEqual(credential.source, "OpenCode auth.json file")

    def test_configured_data_dir_points_at_the_database(self):
        data_dir = self.tmp / "custom-opencode"
        data_dir.mkdir()
        _write_db(
            data_dir / "opencode.db",
            [("opencode", json.dumps({"access": "configured-db-token"}))],
        )
        self._env()
        creds.set_configured_data_dir(str(data_dir))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "configured-db-token")
        self.assertEqual(credential.source, "OpenCode local database")


class LegacyAuthJsonTests(EnvTestCase):
    """The legacy ``opencode/auth.json`` file backs the database up."""

    def _legacy_only(self, payload: object) -> Path:
        """An isolated XDG data home with auth.json and no database file."""
        path = _write_auth_json(self.tmp, payload)
        self._env(XDG_DATA_HOME=str(self.tmp))
        return path

    def test_legacy_oauth_login_resolves_with_expiry(self):
        expires = int(time.time() * 1000) + 3_600_000
        self._legacy_only(
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": expires,
                }
            }
        )
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "legacy-access-1")
        self.assertEqual(credential.source, "OpenCode auth.json file")
        self.assertEqual(credential.kind, "oauth")
        self.assertEqual(credential.expires_ms, expires)
        self.assertIsNotNone(credential.expires_at)

    def test_legacy_api_login_resolves_without_expiry(self):
        self._legacy_only({"opencode": {"type": "api", "key": "legacy-api-key-1"}})
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "legacy-api-key-1")
        self.assertEqual(credential.source, "OpenCode auth.json file")
        self.assertEqual(credential.kind, "api")
        self.assertIsNone(credential.expires_ms)
        self.assertIsNone(credential.expires_at)

    def test_legacy_opencode_go_login_resolves_with_expiry(self):
        expires = int(time.time() * 1000) + 3_600_000
        self._legacy_only(
            {
                "opencode-go": {
                    "type": "oauth",
                    "access": "legacy-go-access",
                    "expires": expires,
                }
            }
        )
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "legacy-go-access")
        self.assertEqual(credential.source, "OpenCode auth.json file")
        self.assertEqual(credential.expires_ms, expires)

    def test_legacy_opencode_go_wins_over_opencode(self):
        self._legacy_only(
            {
                "opencode": {"type": "oauth", "access": "console-access"},
                "opencode-go": {"type": "oauth", "access": "go-access"},
            }
        )
        self.assertEqual(creds.resolve_credential().token, "go-access")

    def test_legacy_value_wrapper_resolves(self):
        self._legacy_only(
            {"opencode-go": {"value": {"access": "wrapped-legacy-access"}}}
        )
        self.assertEqual(creds.resolve_credential().token, "wrapped-legacy-access")

    def test_legacy_key_shape_without_type_resolves(self):
        self._legacy_only({"opencode-go": {"key": "legacy-go-key"}})
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "legacy-go-key")
        self.assertEqual(credential.kind, "api")
        self.assertIsNone(credential.expires_ms)

    def test_legacy_unknown_type_with_access_still_resolves(self):
        self._legacy_only({"opencode": {"type": "legacy", "access": "tok-legacy"}})
        self.assertEqual(creds.resolve_credential().token, "tok-legacy")

    def test_legacy_other_opencode_prefixed_key_resolves(self):
        self._legacy_only({"opencode-x/": {"access": "prefixed-legacy-access"}})
        self.assertEqual(creds.resolve_credential().token, "prefixed-legacy-access")

    def test_trailing_slash_in_the_key_is_tolerated(self):
        self._legacy_only({"opencode/": {"type": "oauth", "access": "slash-access-1"}})
        self.assertEqual(creds.resolve_credential().token, "slash-access-1")

    def test_other_integrations_do_not_resolve(self):
        self._legacy_only({"google": {"type": "oauth", "access": "google-token-1"}})
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_missing_file_keeps_the_database_error(self):
        self._env(XDG_DATA_HOME=str(self.tmp))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_unreadable_path_keeps_the_database_error(self):
        (self.tmp / "opencode" / "auth.json").mkdir(parents=True)
        self._env(XDG_DATA_HOME=str(self.tmp))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_invalid_utf8_keeps_the_database_error(self):
        path = self.tmp / "opencode" / "auth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe{")
        self._env(XDG_DATA_HOME=str(self.tmp))
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_malformed_payloads_keep_the_database_error(self):
        path = self.tmp / "opencode" / "auth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._env(XDG_DATA_HOME=str(self.tmp))
        cases = {
            "malformed json": "{not json",
            "non-dict payload": json.dumps(["opencode"]),
            "non-dict entry": json.dumps({"opencode": ["oauth"]}),
            "oauth without access": json.dumps({"opencode": {"type": "oauth"}}),
            "oauth with non-string access": json.dumps(
                {"opencode": {"type": "oauth", "access": 7}}
            ),
            "oauth with blank access": json.dumps(
                {"opencode": {"type": "oauth", "access": "   "}}
            ),
            "api without key": json.dumps({"opencode": {"type": "api"}}),
            "api with non-string key": json.dumps(
                {"opencode": {"type": "api", "key": {"nested": "no"}}}
            ),
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(creds.CredentialError) as caught:
                    creds.resolve_credential()
                self.assertEqual(str(caught.exception), creds.NO_CREDENTIAL_MESSAGE)

    def test_database_wins_over_the_legacy_file(self):
        db = self.tmp / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        _write_db(db, [("opencode", json.dumps({"access": "db-token-1"}))])
        _write_auth_json(
            self.tmp, {"opencode": {"type": "oauth", "access": "legacy-access-1"}}
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "db-token-1")
        self.assertEqual(credential.source, "OpenCode local database")

    def test_expired_database_row_falls_back_to_the_legacy_file(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        _write_db(
            db,
            [
                (
                    "opencode",
                    json.dumps({"access": "db-token-1", "expires": now_ms - 1}),
                )
            ],
        )
        _write_auth_json(
            self.tmp,
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": now_ms + 3_600_000,
                }
            },
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        credential = creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(credential.token, "legacy-access-1")
        self.assertEqual(credential.source, "OpenCode auth.json file")

    def test_expired_legacy_login_raises_the_expired_message(self):
        now_ms = int(time.time() * 1000)
        self._legacy_only(
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": now_ms - 1,
                }
            }
        )
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_legacy_expiry_exactly_now_is_expired(self):
        now_ms = 1_800_000_000_000
        self._legacy_only(
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": now_ms,
                }
            }
        )
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential(now_ms=now_ms)
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_expired_legacy_login_uses_the_clock_without_now(self):
        self._legacy_only(
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": int(time.time() * 1000) - 60_000,
                }
            }
        )
        with self.assertRaises(creds.CredentialError) as caught:
            creds.resolve_credential()
        self.assertEqual(str(caught.exception), creds.EXPIRED_MESSAGE)

    def test_expired_legacy_login_does_not_mask_a_valid_database_row(self):
        db = self.tmp / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        _write_db(db, [("opencode", json.dumps({"access": "db-token-1"}))])
        _write_auth_json(
            self.tmp,
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": int(time.time() * 1000) - 1,
                }
            },
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "db-token-1")
        self.assertEqual(credential.source, "OpenCode local database")

    def test_legacy_login_with_malformed_expiry_still_resolves(self):
        self._legacy_only(
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": "soon",
                }
            }
        )
        credential = creds.resolve_credential()
        self.assertEqual(credential.token, "legacy-access-1")
        self.assertIsNone(credential.expires_ms)


class HasStoredLoginTests(EnvTestCase):
    """``has_stored_login`` backs the frontends' login hints."""

    def test_env_token_is_a_stored_login(self):
        self._env(OCGO_TOKEN="env-token-123456", OCGO_DB=str(self.tmp / "nope.db"))
        self.assertTrue(creds.has_stored_login())

    def test_blank_env_tokens_are_not_a_stored_login(self):
        self._env(OCGO_TOKEN="", OCGO_DB=str(self.tmp / "nope.db"))
        self.assertFalse(creds.has_stored_login())
        self._env(OCGO_TOKEN="   ", OCGO_DB=str(self.tmp / "nope.db"))
        self.assertFalse(creds.has_stored_login())

    def test_missing_database_is_not_a_stored_login(self):
        self._env(OCGO_DB=str(self.tmp / "nope.db"))
        self.assertFalse(creds.has_stored_login())

    def test_label_less_schema_still_counts_as_a_stored_login(self):
        # The existence probe must not depend on the production `label` column.
        db = self.tmp / "opencode.db"
        _write_db(db, [("opencode", json.dumps({"access": "tok-abcdefgh"}))])
        self._env(OCGO_DB=str(db))
        self.assertTrue(creds.has_stored_login())

    def test_unreadable_database_is_not_a_stored_login(self):
        db = self.tmp / "opencode.db"
        db.write_text("this is not a database", encoding="utf-8")
        self._env(OCGO_DB=str(db))
        self.assertFalse(creds.has_stored_login())

    def test_active_database_row_is_a_stored_login(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-1",
                    "opencode",
                    "Default",
                    json.dumps({"access": "tok-abcdefgh"}),
                    1,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertTrue(creds.has_stored_login())

    def test_opencode_go_row_is_a_stored_login(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-go",
                    "opencode-go",
                    "Go",
                    json.dumps({"access": "go-token-1"}),
                    1,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertTrue(creds.has_stored_login())

    def test_other_opencode_prefixed_row_is_a_stored_login(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-x",
                    "opencode-x",
                    "X",
                    json.dumps({"access": "x-token-1"}),
                    0,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertTrue(creds.has_stored_login())

    def test_expired_database_row_is_still_a_stored_login(self):
        now_ms = int(time.time() * 1000)
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [
                (
                    "cred-1",
                    "opencode",
                    "Default",
                    json.dumps({"access": "tok-abcdefgh", "expires": now_ms - 1}),
                    0,
                    100,
                )
            ],
        )
        self._env(OCGO_DB=str(db))
        self.assertTrue(creds.has_stored_login())

    def test_empty_database_has_no_stored_login(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(db, [])
        self._env(OCGO_DB=str(db))
        self.assertFalse(creds.has_stored_login())

    def test_other_integrations_are_not_a_stored_login(self):
        db = self.tmp / "opencode.db"
        _write_labelled_db(
            db,
            [("cred-google", "google", "Google", json.dumps({"access": "g"}), 1, 300)],
        )
        self._env(OCGO_DB=str(db))
        self.assertFalse(creds.has_stored_login())

    def test_legacy_oauth_login_is_a_stored_login(self):
        _write_auth_json(
            self.tmp, {"opencode": {"type": "oauth", "access": "legacy-access-1"}}
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        self.assertTrue(creds.has_stored_login())

    def test_legacy_api_login_is_a_stored_login(self):
        _write_auth_json(self.tmp, {"opencode": {"type": "api", "key": "legacy-key-1"}})
        self._env(XDG_DATA_HOME=str(self.tmp))
        self.assertTrue(creds.has_stored_login())

    def test_expired_legacy_login_is_still_a_stored_login(self):
        now_ms = int(time.time() * 1000)
        _write_auth_json(
            self.tmp,
            {
                "opencode": {
                    "type": "oauth",
                    "access": "legacy-access-1",
                    "expires": now_ms - 1,
                }
            },
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        self.assertTrue(creds.has_stored_login())

    def test_malformed_legacy_file_is_not_a_stored_login(self):
        path = self.tmp / "opencode" / "auth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self._env(XDG_DATA_HOME=str(self.tmp))
        self.assertFalse(creds.has_stored_login())

    def test_stored_api_key_is_a_stored_login(self):
        self._env()
        creds.store_api_key(_KEY)
        self.assertTrue(creds.has_stored_login())

    def test_blank_api_key_file_is_not_a_stored_login(self):
        self._env()
        path = self._api_key_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("   \n", encoding="utf-8")
        self.assertFalse(creds.has_stored_login())


class ApiKeyFileTests(EnvTestCase):
    """The fallback API key lives in a ``0600`` file under the config home."""

    def test_store_returns_a_hint_and_writes_0600(self):
        self._env()
        hint = creds.store_api_key(f"  {_KEY}  ")
        self.assertEqual(hint, creds.mask_token(_KEY))
        path = self._api_key_path()
        self.assertEqual(path.read_text(encoding="utf-8").strip(), _KEY)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual([entry.name for entry in path.parent.iterdir()], ["api.key"])

    def test_store_replaces_an_existing_key(self):
        self._env()
        creds.store_api_key("oc_sk_first_abcdefgh")
        hint = creds.store_api_key("oc_sk_second_zyxwvuts")
        self.assertEqual(creds.read_api_key(), "oc_sk_second_zyxwvuts")
        self.assertEqual(hint, creds.mask_token("oc_sk_second_zyxwvuts"))

    def test_store_blank_is_rejected(self):
        self._env()
        for blank in ("", "   ", "\n"):
            with self.subTest(value=repr(blank)):
                with self.assertRaises(creds.CredentialError):
                    creds.store_api_key(blank)
        self.assertFalse(self._api_key_path().exists())

    def test_read_missing_is_none(self):
        self._env()
        self.assertIsNone(creds.read_api_key())
        self.assertFalse(creds.has_api_key())

    def test_read_blank_is_none(self):
        self._env()
        path = self._api_key_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("  \n", encoding="utf-8")
        self.assertIsNone(creds.read_api_key())
        self.assertFalse(creds.has_api_key())

    def test_read_unreadable_is_none(self):
        self._env()
        self._api_key_path().mkdir(parents=True)  # a directory, not a file
        self.assertIsNone(creds.read_api_key())
        self.assertFalse(creds.has_api_key())

    def test_clear_reports_removal(self):
        self._env()
        creds.store_api_key(_KEY)
        self.assertTrue(creds.clear_api_key())
        self.assertFalse(self._api_key_path().exists())

    def test_clear_absent_is_false(self):
        self._env()
        self.assertFalse(creds.clear_api_key())


class ConfigFileTests(EnvTestCase):
    """``config.json`` holds the optional OpenCode data directory."""

    def test_missing_config_reads_as_empty(self):
        self._env()
        self.assertEqual(creds.read_config(), {})
        self.assertIsNone(creds.get_configured_data_dir())

    def test_malformed_config_reads_as_empty(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(creds.read_config(), {})
        self.assertIsNone(creds.get_configured_data_dir())

    def test_non_object_config_reads_as_empty(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(creds.read_config(), {})
        self.assertIsNone(creds.get_configured_data_dir())

    def test_non_string_value_reads_as_unset(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"opencode_data_dir": 7}), encoding="utf-8")
        self.assertIsNone(creds.get_configured_data_dir())

    def test_blank_value_reads_as_unset(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"opencode_data_dir": "   "}), encoding="utf-8"
        )
        self.assertIsNone(creds.get_configured_data_dir())

    def test_set_then_get_round_trip(self):
        self._env()
        target = self.tmp / "opencode-data"
        creds.set_configured_data_dir(str(target))
        self.assertEqual(creds.get_configured_data_dir(), str(target))
        self.assertEqual(creds.read_config(), {"opencode_data_dir": str(target)})

    def test_set_preserves_other_keys(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"theme": "dark", "opencode_data_dir": "/old"}),
            encoding="utf-8",
        )
        creds.set_configured_data_dir("/new")
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"theme": "dark", "opencode_data_dir": "/new"},
        )

    def test_set_replaces_a_malformed_config(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        creds.set_configured_data_dir("/new")
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"opencode_data_dir": "/new"},
        )

    def test_clear_removes_only_the_key(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"theme": "dark", "opencode_data_dir": "/old"}),
            encoding="utf-8",
        )
        creds.set_configured_data_dir(None)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")), {"theme": "dark"}
        )
        self.assertIsNone(creds.get_configured_data_dir())

    def test_clear_without_a_config_file(self):
        self._env()
        creds.set_configured_data_dir(None)
        self.assertIsNone(creds.get_configured_data_dir())

    def test_set_leaves_no_temp_files(self):
        self._env()
        creds.set_configured_data_dir("/x")
        self.assertEqual(
            [entry.name for entry in creds.config_path().parent.iterdir()],
            ["config.json"],
        )


class DataDirResolutionTests(EnvTestCase):
    """The effective data dir: OCGO_DATA_DIR, then config, then XDG default."""

    def test_xdg_data_home_default(self):
        self._env()
        self.assertEqual(
            creds.default_db_path(), self.tmp / "data" / "opencode" / "opencode.db"
        )
        self.assertEqual(
            creds.default_auth_json_path(),
            self.tmp / "data" / "opencode" / "auth.json",
        )

    def test_ocgo_data_dir_wins_over_config(self):
        self._env(OCGO_DATA_DIR=str(self.tmp / "env-opencode"))
        creds.set_configured_data_dir(str(self.tmp / "config-opencode"))
        self.assertEqual(
            creds.default_db_path(), self.tmp / "env-opencode" / "opencode.db"
        )
        self.assertEqual(
            creds.default_auth_json_path(),
            self.tmp / "env-opencode" / "auth.json",
        )

    def test_configured_dir_wins_over_xdg_data_home(self):
        self._env()
        creds.set_configured_data_dir(str(self.tmp / "config-opencode"))
        self.assertEqual(
            creds.default_db_path(), self.tmp / "config-opencode" / "opencode.db"
        )
        self.assertEqual(
            creds.default_auth_json_path(),
            self.tmp / "config-opencode" / "auth.json",
        )

    def test_configured_tilde_is_expanded(self):
        self._env()
        creds.set_configured_data_dir("~/opencode-data")
        self.assertEqual(
            creds.default_db_path(),
            self.tmp / "home" / "opencode-data" / "opencode.db",
        )

    def test_ocgo_db_overrides_the_data_dir(self):
        self._env(
            OCGO_DATA_DIR=str(self.tmp / "env-opencode"),
            OCGO_DB=str(self.tmp / "direct.db"),
        )
        status = creds.store_status()
        self.assertEqual(status["db_path"], str(self.tmp / "direct.db"))
        self.assertEqual(
            status["auth_json_path"], str(self.tmp / "env-opencode" / "auth.json")
        )
        self.assertEqual(status["data_dir"], str(self.tmp / "env-opencode"))


class StoreStatusTests(EnvTestCase):
    """``store_status`` names the stores the applet/CLI looked at."""

    _FIELDS = [
        "db_path",
        "db_exists",
        "auth_json_path",
        "auth_json_exists",
        "auth_json_login",
        "has_login",
        "data_dir",
        "configured_data_dir",
        "api_key_configured",
        "api_key_hint",
    ]

    def test_nothing_present(self):
        self._env()
        status = creds.store_status()
        self.assertEqual(list(status), self._FIELDS)
        self.assertEqual(
            status["db_path"], str(self.tmp / "data" / "opencode" / "opencode.db")
        )
        self.assertFalse(status["db_exists"])
        self.assertEqual(
            status["auth_json_path"],
            str(self.tmp / "data" / "opencode" / "auth.json"),
        )
        self.assertFalse(status["auth_json_exists"])
        self.assertFalse(status["auth_json_login"])
        self.assertFalse(status["has_login"])
        self.assertEqual(status["data_dir"], str(self.tmp / "data" / "opencode"))
        self.assertIsNone(status["configured_data_dir"])
        self.assertFalse(status["api_key_configured"])
        self.assertIsNone(status["api_key_hint"])

    def test_field_types(self):
        self._env()
        status = creds.store_status()
        self.assertEqual(list(status), self._FIELDS)
        self.assertIsInstance(status["db_path"], str)
        self.assertIsInstance(status["db_exists"], bool)
        self.assertIsInstance(status["auth_json_path"], str)
        self.assertIsInstance(status["auth_json_exists"], bool)
        self.assertIsInstance(status["auth_json_login"], bool)
        self.assertIsInstance(status["has_login"], bool)
        self.assertIsInstance(status["data_dir"], str)
        self.assertIsNone(status["configured_data_dir"])
        self.assertIsInstance(status["api_key_configured"], bool)
        self.assertIsNone(status["api_key_hint"])

    def test_database_only(self):
        db = self.tmp / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        _write_labelled_db(
            db,
            [("cred-1", "opencode", "Default", json.dumps({"access": "tok"}), 1, 100)],
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        status = creds.store_status()
        self.assertEqual(status["db_path"], str(db))
        self.assertTrue(status["db_exists"])
        self.assertFalse(status["auth_json_exists"])
        self.assertFalse(status["auth_json_login"])
        self.assertTrue(status["has_login"])
        self.assertEqual(status["data_dir"], str(self.tmp / "opencode"))

    def test_legacy_only(self):
        _write_auth_json(self.tmp, {"opencode": {"type": "api", "key": "legacy-key-1"}})
        self._env(XDG_DATA_HOME=str(self.tmp))
        status = creds.store_status()
        self.assertFalse(status["db_exists"])
        self.assertTrue(status["auth_json_exists"])
        self.assertTrue(status["auth_json_login"])
        self.assertTrue(status["has_login"])

    def test_both_stores(self):
        db = self.tmp / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        _write_db(db, [("opencode", json.dumps({"access": "db-token-1"}))])
        _write_auth_json(
            self.tmp, {"opencode": {"type": "oauth", "access": "legacy-access-1"}}
        )
        self._env(XDG_DATA_HOME=str(self.tmp))
        status = creds.store_status()
        self.assertTrue(status["db_exists"])
        self.assertTrue(status["auth_json_exists"])
        self.assertTrue(status["auth_json_login"])
        self.assertTrue(status["has_login"])

    def test_env_token_only_counts_as_a_login(self):
        self._env(OCGO_TOKEN="env-token-1")
        status = creds.store_status()
        self.assertFalse(status["db_exists"])
        self.assertFalse(status["auth_json_exists"])
        self.assertFalse(status["auth_json_login"])
        self.assertTrue(status["has_login"])
        self.assertFalse(status["api_key_configured"])

    def test_malformed_legacy_file_is_not_a_login(self):
        path = self.tmp / "opencode" / "auth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self._env(XDG_DATA_HOME=str(self.tmp))
        status = creds.store_status()
        self.assertTrue(status["auth_json_exists"])
        self.assertFalse(status["auth_json_login"])
        self.assertFalse(status["has_login"])

    def test_configured_data_dir_is_reported(self):
        self._env()
        custom = self.tmp / "custom-opencode"
        creds.set_configured_data_dir(str(custom))
        status = creds.store_status()
        self.assertEqual(status["data_dir"], str(custom))
        self.assertEqual(status["configured_data_dir"], str(custom))
        self.assertEqual(status["db_path"], str(custom / "opencode.db"))
        self.assertEqual(status["auth_json_path"], str(custom / "auth.json"))

    def test_env_data_dir_is_reported(self):
        self._env(OCGO_DATA_DIR=str(self.tmp / "env-opencode"))
        status = creds.store_status()
        self.assertEqual(status["data_dir"], str(self.tmp / "env-opencode"))
        self.assertIsNone(status["configured_data_dir"])

    def test_stored_api_key_is_reported_masked(self):
        self._env()
        creds.store_api_key(_KEY)
        status = creds.store_status()
        self.assertTrue(status["api_key_configured"])
        self.assertEqual(status["api_key_hint"], creds.mask_token(_KEY))
        self.assertTrue(status["has_login"])
        self.assertNotIn(_KEY, json.dumps(status))

    def test_malformed_config_still_reports(self):
        self._env()
        path = creds.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        status = creds.store_status()
        self.assertEqual(status["data_dir"], str(self.tmp / "data" / "opencode"))
        self.assertIsNone(status["configured_data_dir"])


class DefaultPathTests(unittest.TestCase):
    def test_xdg_data_home_wins(self):
        with mock.patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "/xdg", "XDG_CONFIG_HOME": "/xdg-config"},
            clear=True,
        ):
            self.assertEqual(
                creds.default_db_path(), Path("/xdg/opencode/opencode.db")
            )

    def test_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                creds.default_db_path(),
                Path("/home/tester/.local/share/opencode/opencode.db"),
            )


class AuthJsonPathTests(unittest.TestCase):
    def test_xdg_data_home_wins(self):
        with mock.patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "/xdg", "XDG_CONFIG_HOME": "/xdg-config"},
            clear=True,
        ):
            self.assertEqual(
                creds.default_auth_json_path(), Path("/xdg/opencode/auth.json")
            )

    def test_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                creds.default_auth_json_path(),
                Path("/home/tester/.local/share/opencode/auth.json"),
            )


class ConfigPathTests(unittest.TestCase):
    def test_xdg_config_home_wins(self):
        with mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": "/xdg-config"}, clear=True
        ):
            self.assertEqual(
                creds.config_path(), Path("/xdg-config/ocgo/config.json")
            )

    def test_home_fallback(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester"}, clear=True):
            self.assertEqual(
                creds.config_path(), Path("/home/tester/.config/ocgo/config.json")
            )


class MaskTokenTests(unittest.TestCase):
    def test_long_token_keeps_only_head_and_tail(self):
        masked = creds.mask_token("abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(masked, "abcdef…wxyz")

    def test_short_token_is_fully_hidden(self):
        self.assertEqual(creds.mask_token("short"), "…")
        self.assertEqual(creds.mask_token("twelve-chars"), "…")


class CredentialObjectTests(unittest.TestCase):
    def test_kind_defaults_to_oauth(self):
        credential = creds.Credential(token="tok-abcdefgh", source="test")
        self.assertEqual(credential.kind, "oauth")

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
