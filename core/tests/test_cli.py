"""Tests for ocgo.cli: credential/API calls are patched; no network."""

import io
import json
import os
import sqlite3
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _support import quarantine_gc_warnings, temp_dir

from ocgo import __version__, api, cache, cli, creds
from ocgo import format as fmt

TOKEN = "test-token-abcdefghijklmnop"
_ZEN_KEY = "oc_sk_test_abcdefghijklmnop1234"


def run_cli(args):
    """Run the CLI in-process, capturing stdout/stderr and SystemExit codes."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(args)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def good_cache_data() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "schema": 1,
        "fetched_at": fmt.iso_utc(now),
        "last_error": None,
        "last_error_at": None,
        "product": "go",
        "renewal_ends_at": fmt.iso_utc(now + timedelta(days=9, hours=3, minutes=30)),
        "windows": {
            "rolling": {
                "percent": 2,
                "used_usd": 0.1821,
                "limit_usd": 12.0,
                "resets_at": fmt.iso_utc(
                    now + timedelta(hours=4, minutes=24, seconds=30)
                ),
            },
            "weekly": {
                "percent": 64,
                "used_usd": 19.0929,
                "limit_usd": 30.0,
                "resets_at": fmt.iso_utc(now + timedelta(days=3, minutes=30)),
            },
            "monthly": {
                "percent": 58,
                "used_usd": 34.713,
                "limit_usd": 60.0,
                "resets_at": None,
            },
        },
    }


def live_payload() -> dict:
    return {
        "product": "go",
        "useBalance": True,
        "access": {
            "endsAt": "2026-10-11T02:26:15.000Z",
            "meters": {
                "fiveHour": {
                    "resetsAt": "2026-10-02T03:46:18.527Z",
                    "limitMicroCents": "1200000000",
                    "usedMicroCents": "18211143",
                },
                "week": {
                    "resetsAt": "2026-10-05T00:00:00.000Z",
                    "limitMicroCents": "3000000000",
                    "usedMicroCents": "1909286550",
                },
                "month": {
                    "limitMicroCents": "6000000000",
                    "usedMicroCents": "3471303267",
                },
            },
        },
    }


def zen_payload() -> dict:
    return {
        "usage": {
            "rolling": {
                "status": "ok",
                "percent": 12,
                "resetsAt": "2026-10-02T03:46:18.527Z",
            },
            "weekly": {
                "status": "ok",
                "percent": 64,
                "resetsAt": "2026-10-05T00:00:00.000Z",
            },
            "monthly": {
                "status": "ok",
                "percent": 58,
                "resetsAt": "2026-10-11T02:26:15.000Z",
            },
        }
    }


def write_credential_db(path: Path, rows: list[tuple]) -> Path:
    """Write a labelled opencode credential DB and return its path.

    Each row is ``(id, label, value, active, time_updated)``; every row is
    stored under the ``opencode`` integration id.
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
    for row_id, label, value, active, updated in rows:
        connection.execute(
            "INSERT INTO credential "
            "(id, integration_id, label, value, active, time_updated) "
            "VALUES (?, 'opencode', ?, ?, ?, ?)",
            (row_id, label, value, active, updated),
        )
    connection.commit()
    connection.close()
    return path


class CliTestCase(unittest.TestCase):
    def setUp(self):
        # A leaked HTTPError fixture from another test can otherwise warn into
        # this test's captured stderr; keep the quarantine ahead of
        # unittest's blanket "default" filter (see _support).
        quarantine_gc_warnings()
        self.tmp = Path(self.enterContext(temp_dir()))

    def _env(self, **values):
        """Isolate the process env: temp XDG dirs plus the given overrides."""
        base = {
            "HOME": str(self.tmp / "home"),
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "XDG_DATA_HOME": str(self.tmp / "data"),
            "OCGO_DB": str(self.tmp / "missing.db"),
        }
        base.update(values)
        patcher = mock.patch.dict(os.environ, base, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _api_key_path(self) -> Path:
        """The stored fallback API key path under the isolated config home."""
        return creds.config_path().parent / "api.key"


class ArgumentTests(CliTestCase):
    def test_version_flag(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), f"ocgo {__version__}")

    def test_help_flag(self):
        code, out, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: ocgo", out)

    def test_no_args_exits_2(self):
        self.assertEqual(run_cli([])[0], 2)

    def test_unknown_command_exits_2(self):
        self.assertEqual(run_cli(["frobnicate"])[0], 2)

    def test_auth_requires_subcommand(self):
        self.assertEqual(run_cli(["auth"])[0], 2)

    def test_account_subcommand_is_gone(self):
        code, out, err = run_cli(["account", "add", "x"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("invalid choice: 'account'", err)

    def test_refresh_rejects_account_flag(self):
        code, _out, err = run_cli(["refresh", "--account", "work"])
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)

    def test_refresh_rejects_all_flag(self):
        self.assertEqual(run_cli(["refresh", "--all"])[0], 2)

    def test_status_rejects_account_flag(self):
        self.assertEqual(run_cli(["status", "--account", "work"])[0], 2)


class AuthShowTests(CliTestCase):
    def test_env_token_shows_only_masked_hint(self):
        self._env(OCGO_TOKEN=TOKEN)
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  OCGO_TOKEN environment", out)
        self.assertIn("Token:   test-t…mnop", out)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn(TOKEN, err)

    def test_db_token_shows_source_and_expiry(self):
        expires_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3_600_000
        db = write_credential_db(
            self.tmp / "opencode.db",
            [("cred-1", "Default", json.dumps({"access": TOKEN, "expires": expires_ms}), 1, 1)],
        )
        self._env(OCGO_DB=str(db))
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  OpenCode local database", out)
        self.assertIn("test-t…mnop", out)
        self.assertIn("Expires: ", out)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn(TOKEN, err)

    def test_configured_api_key_is_shown_without_expiry(self):
        self._env()
        creds.store_api_key(_ZEN_KEY)
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("Source:  Configured API key", out)
        self.assertIn(f"Token:   {creds.mask_token(_ZEN_KEY)}", out)
        self.assertNotIn("Expires:", out)
        self.assertNotIn(_ZEN_KEY, out + err)

    def test_missing_credential_is_friendly(self):
        self._env()
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "Source:  none\n")
        self.assertIn("No OpenCode credential found.", err)

    def test_json_reports_credential_and_store(self):
        self._env(OCGO_TOKEN=TOKEN)
        code, out, err = run_cli(["auth", "show", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(list(payload), ["schema", "credential", "store"])
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(
            payload["credential"],
            {
                "source": "OCGO_TOKEN environment",
                "kind": "oauth",
                "token_hint": creds.mask_token(TOKEN),
                "expires_at": None,
            },
        )
        self.assertEqual(
            list(payload["store"]),
            [
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
            ],
        )
        self.assertNotIn(TOKEN, out)

    def test_json_reports_api_kind_and_masked_hint(self):
        self._env()
        creds.store_api_key(_ZEN_KEY)
        code, out, err = run_cli(["auth", "show", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(
            payload["credential"],
            {
                "source": "Configured API key",
                "kind": "api",
                "token_hint": creds.mask_token(_ZEN_KEY),
                "expires_at": None,
            },
        )
        self.assertTrue(payload["store"]["api_key_configured"])
        self.assertEqual(payload["store"]["api_key_hint"], creds.mask_token(_ZEN_KEY))
        self.assertNotIn(_ZEN_KEY, out)

    def test_json_reports_expiry_when_present(self):
        expires_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3_600_000
        db = write_credential_db(
            self.tmp / "opencode.db",
            [("cred-1", "Default", json.dumps({"access": TOKEN, "expires": expires_ms}), 1, 1)],
        )
        self._env(OCGO_DB=str(db))
        code, out, _err = run_cli(["auth", "show", "--json"])
        self.assertEqual(code, 0)
        expires_at = json.loads(out)["credential"]["expires_at"]
        self.assertIsNotNone(fmt.parse_iso(expires_at))

    def test_json_marks_none_on_failure(self):
        self._env()
        code, out, err = run_cli(["auth", "show", "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(list(payload), ["schema", "credential", "store"])
        self.assertIsNone(payload["credential"])
        self.assertIn("No OpenCode credential found.", err)


class StatusTests(CliTestCase):
    def test_missing_cache_is_friendly(self):
        self._env()
        code, out, err = run_cli(["status"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("ocgo refresh", err)

    def test_rows_mirror_the_console(self):
        self._env()
        cache.save(good_cache_data())
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage    2%   Resets in 4h 24m", out)
        self.assertIn("Weekly usage    64%   Resets in 3d 0h", out)
        self.assertIn("Monthly usage   58%   Resets in 9d 3h", out)
        self.assertNotIn("\x1b", out)
        self.assertEqual(err, "")

    def test_warning_line_when_last_error(self):
        self._env()
        data = good_cache_data()
        data["last_error"] = "network error contacting opencode.ai: boom"
        data["last_error_at"] = "2026-10-01T23:45:00Z"
        cache.save(data)
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage", out)
        self.assertIn("Warning: last refresh failed at 2026-10-01T23:45:00Z", err)
        self.assertIn("network error contacting opencode.ai: boom", err)
        self.assertIn(data["fetched_at"], err)

    def test_json_prints_cache_verbatim(self):
        self._env()
        cache.save(good_cache_data())
        raw = cache.cache_path().read_text(encoding="utf-8")
        code, out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(out, raw)
        self.assertEqual(err, "")

    def test_json_without_cache_exits_1(self):
        self._env()
        code, out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("ocgo refresh", err)

    def test_non_dict_windows_is_handled_gracefully(self):
        self._env()
        data = good_cache_data()
        data["windows"] = [1, 2]
        cache.save(data)
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage  n/a   Resets in n/a", out)
        self.assertIn("Weekly usage   n/a   Resets in n/a", out)
        self.assertIn("Monthly usage  n/a   Resets in", out)  # renewal countdown stays
        self.assertNotIn("Traceback", err)

    def test_non_dict_window_entry_is_handled_gracefully(self):
        self._env()
        data = good_cache_data()
        data["windows"]["weekly"] = [1]
        cache.save(data)
        code, out, _ = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Weekly usage   n/a   Resets in n/a", out)

    def test_tty_uses_per_window_colors(self):
        self._env()
        data = good_cache_data()
        data["windows"]["monthly"]["percent"] = 90
        cache.save(data)
        out = TtyStream()
        with mock.patch.object(cli.sys, "stdout", out):
            code = cli.main(["status"])
        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("\x1b[32m", rendered)  # rolling 2% green
        self.assertIn("\x1b[33m", rendered)  # weekly 64% amber
        self.assertIn("\x1b[31m", rendered)  # monthly 90% red
        self.assertIn("\x1b[0m", rendered)


class TtyStream(io.StringIO):
    def isatty(self):
        return True


class PipeStream(io.StringIO):
    def isatty(self):
        return False


class ColorTests(unittest.TestCase):
    def test_tty_enables_colors(self):
        self.assertTrue(cli.colors_enabled(False, stream=TtyStream()))

    def test_no_color_flag_wins(self):
        self.assertFalse(cli.colors_enabled(True, stream=TtyStream()))

    def test_no_color_env_wins(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
            self.assertFalse(cli.colors_enabled(False, stream=TtyStream()))

    def test_pipe_disables_colors(self):
        self.assertFalse(cli.colors_enabled(False, stream=PipeStream()))


class RefreshTests(CliTestCase):
    def _oauth_credential(self):
        return creds.Credential(
            token=TOKEN, source="OCGO_TOKEN environment", kind="oauth"
        )

    def _api_credential(self):
        return creds.Credential(token=_ZEN_KEY, source="Configured API key", kind="api")

    def test_refresh_oauth_writes_cache_and_summary(self):
        self._env(OCGO_TOKEN=TOKEN)
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._oauth_credential()
            ),
            mock.patch.object(
                cli.api, "fetch_status", return_value=live_payload()
            ) as fetch,
            mock.patch.object(cli.api, "fetch_zen_status") as zen,
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertEqual(
            out,
            "Refreshed OpenCode Go: rolling 2% · weekly 64% · monthly 58%\n",
        )
        self.assertEqual(err, "")
        fetch.assert_called_once_with(TOKEN)
        zen.assert_not_called()
        data = cache.load()
        self.assertEqual(data["windows"]["weekly"]["percent"], 64)
        self.assertEqual(data["windows"]["monthly"]["resets_at"], None)
        self.assertNotIn("credits", data)
        self.assertNotIn("extra_usage", data)
        self.assertIsNone(data["last_error"])
        self.assertIsNotNone(fmt.parse_iso(data["fetched_at"]))
        self.assertNotIn(TOKEN, out + err)

    def test_refresh_api_key_uses_zen_only(self):
        self._env()
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._api_credential()
            ),
            mock.patch.object(cli.api, "fetch_status") as fetch,
            mock.patch.object(
                cli.api, "fetch_zen_status", return_value=zen_payload()
            ) as zen,
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertIn(
            "Refreshed OpenCode Go: rolling 12% · weekly 64% · monthly 58%", out
        )
        self.assertEqual(err, "")
        zen.assert_called_once_with(_ZEN_KEY)
        fetch.assert_not_called()
        data = cache.load()
        self.assertEqual(data["windows"]["rolling"]["percent"], 12)
        self.assertIsNone(data["windows"]["rolling"]["used_usd"])
        self.assertNotIn(_ZEN_KEY, out + err)

    def test_refresh_resolves_the_local_store_end_to_end(self):
        db = write_credential_db(
            self.tmp / "opencode.db",
            [("cred-1", "Default", json.dumps({"access": TOKEN}), 1, 1)],
        )
        self._env(OCGO_DB=str(db))
        with mock.patch.object(
            cli.api, "fetch_status", return_value=live_payload()
        ) as fetch:
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        fetch.assert_called_once_with(TOKEN)
        self.assertEqual(
            out,
            "Refreshed OpenCode Go: rolling 2% · weekly 64% · monthly 58%\n",
        )
        self.assertIsNotNone(cache.load())

    def test_refresh_failure_keeps_last_good_data(self):
        self._env(OCGO_TOKEN=TOKEN)
        good = good_cache_data()
        cache.save(good)
        error = api.ApiError("network error contacting opencode.ai: boom")
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._oauth_credential()
            ),
            mock.patch.object(cli.api, "fetch_status", side_effect=error),
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("network error contacting opencode.ai: boom", err)
        data = cache.load()
        self.assertEqual(data["windows"], good["windows"])
        self.assertEqual(data["fetched_at"], good["fetched_at"])
        self.assertEqual(data["last_error"], str(error))
        self.assertIsNotNone(fmt.parse_iso(data["last_error_at"]))

    def test_refresh_without_credential_writes_nothing(self):
        self._env()  # OCGO_DB points at a missing file and no fallback key exists
        code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("No OpenCode credential found", err)
        self.assertIsNone(cache.load())

    def test_refresh_resolution_failure_records_last_error(self):
        self._env()
        good = good_cache_data()
        cache.save(good)
        error = creds.CredentialError(creds.NO_CREDENTIAL_MESSAGE)
        with mock.patch.object(cli.creds, "resolve_credential", side_effect=error):
            code, _out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertIn("No OpenCode credential found.", err)
        data = cache.load()
        self.assertEqual(data["windows"], good["windows"])
        self.assertEqual(data["last_error"], str(error))
        self.assertIsNotNone(fmt.parse_iso(data["last_error_at"]))

    def test_refresh_cache_write_failure_is_reported(self):
        self._env(OCGO_TOKEN=TOKEN)
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._oauth_credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(cli.cache, "save", side_effect=OSError("boom")),
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("could not write the cache", err)


class FakeStdin(io.StringIO):
    def __init__(self, text: str, tty: bool = False):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


class AuthSetKeyTests(CliTestCase):
    def test_stdin_key_is_validated_stored_and_refreshed(self):
        self._env()
        stdin = FakeStdin(_ZEN_KEY + "\n")
        with (
            mock.patch.object(cli.sys, "stdin", stdin),
            mock.patch.object(
                cli.api, "fetch_zen_status", return_value=zen_payload()
            ) as zen,
        ):
            code, out, err = run_cli(["auth", "set-key", "--stdin"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(zen.call_count, 2)  # validation + refresh
        zen.assert_called_with(_ZEN_KEY)
        self.assertEqual(out, f"Stored API key {creds.mask_token(_ZEN_KEY)}\n")
        path = self._api_key_path()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.read_text(encoding="utf-8").strip(), _ZEN_KEY)
        data = cache.load()
        self.assertEqual(data["windows"]["rolling"]["percent"], 12)
        self.assertIsNone(data["last_error"])
        self.assertNotIn(_ZEN_KEY, out + err)

    def test_piped_stdin_without_a_tty_is_read(self):
        self._env()
        stdin = FakeStdin(_ZEN_KEY + "\nignored\n", tty=False)
        with (
            mock.patch.object(cli.sys, "stdin", stdin),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["auth", "set-key"])
        self.assertEqual(code, 0)
        self.assertEqual(creds.read_api_key(), _ZEN_KEY)

    def test_tty_prompts_hidden(self):
        self._env()
        with (
            mock.patch.object(cli.sys, "stdin", FakeStdin("", tty=True)),
            mock.patch.object(
                cli.getpass, "getpass", return_value=_ZEN_KEY
            ) as prompt,
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["auth", "set-key"])
        self.assertEqual(code, 0)
        prompt.assert_called_once_with("API key: ")
        self.assertEqual(creds.read_api_key(), _ZEN_KEY)

    def test_blank_key_fails_before_validating(self):
        self._env()
        with (
            mock.patch.object(cli, "_read_api_key", return_value="   "),
            mock.patch.object(cli.api, "fetch_zen_status") as zen,
        ):
            code, _out, err = run_cli(["auth", "set-key", "--stdin"])
        self.assertEqual(code, 1)
        self.assertIn("no API key provided", err)
        zen.assert_not_called()
        self.assertFalse(self._api_key_path().exists())

    def test_rejected_key_is_not_stored(self):
        self._env()
        error = api.ApiAuthError("the API key was rejected (HTTP 401)")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, out, err = run_cli(["auth", "set-key", "--stdin"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("API key was rejected", err)
        self.assertFalse(self._api_key_path().exists())
        self.assertIsNone(cache.load())

    def test_network_error_is_not_stored(self):
        self._env()
        error = api.ApiError("network error contacting opencode.ai: boom")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, _out, err = run_cli(["auth", "set-key", "--stdin"])
        self.assertEqual(code, 1)
        self.assertIn("boom", err)
        self.assertFalse(self._api_key_path().exists())

    def test_entitlement_warns_but_stores(self):
        self._env()
        error = api.ApiEntitlementError(
            "this account has no active OpenCode Go subscription"
        )
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, out, err = run_cli(["auth", "set-key", "--stdin"])
        self.assertEqual(code, 0)
        self.assertIn("Stored API key", out)
        self.assertIn("no active OpenCode Go subscription", err)
        self.assertEqual(creds.read_api_key(), _ZEN_KEY)

    def test_stored_key_is_then_used_by_refresh(self):
        self._env()
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["auth", "set-key", "--stdin"])
        self.assertEqual(code, 0)
        with (
            mock.patch.object(
                cli.api, "fetch_zen_status", return_value=zen_payload()
            ) as zen,
            mock.patch.object(cli.api, "fetch_status") as fetch,
        ):
            code, _out, _err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        zen.assert_called_once_with(_ZEN_KEY)
        fetch.assert_not_called()


class AuthClearKeyTests(CliTestCase):
    def test_clear_removes_the_stored_key(self):
        self._env()
        creds.store_api_key(_ZEN_KEY)
        code, out, err = run_cli(["auth", "clear-key"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "Cleared the stored API key\n")
        self.assertEqual(err, "")
        self.assertFalse(self._api_key_path().exists())
        self.assertIsNone(creds.read_api_key())

    def test_clear_without_a_key_is_a_note(self):
        self._env()
        code, out, err = run_cli(["auth", "clear-key"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "No stored API key to clear\n")
        self.assertEqual(err, "")


class AuthDataDirTests(CliTestCase):
    def test_set_data_dir_persists_the_choice(self):
        self._env()
        custom = self.tmp / "custom-opencode"
        custom.mkdir()
        code, out, err = run_cli(["auth", "set-data-dir", str(custom)])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, f"OpenCode data directory set to {custom}\n")
        self.assertEqual(creds.get_configured_data_dir(), str(custom))
        self.assertEqual(creds.store_status()["data_dir"], str(custom))

    def test_set_data_dir_expands_user(self):
        self._env()
        home = Path(os.environ["HOME"])
        target = home / "opencode-data"
        target.mkdir(parents=True)
        code, out, _err = run_cli(["auth", "set-data-dir", "~/opencode-data"])
        self.assertEqual(code, 0)
        self.assertEqual(creds.get_configured_data_dir(), str(target))
        self.assertIn(str(target), out)

    def test_set_data_dir_requires_an_existing_directory(self):
        self._env()
        missing = self.tmp / "nope"
        code, out, err = run_cli(["auth", "set-data-dir", str(missing)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(f"not a directory: {missing}", err)
        self.assertFalse(creds.config_path().exists())

    def test_set_data_dir_rejects_a_file(self):
        self._env()
        target = self.tmp / "a-file"
        target.write_text("x", encoding="utf-8")
        code, _out, err = run_cli(["auth", "set-data-dir", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("not a directory", err)

    def test_clear_data_dir_resets(self):
        self._env()
        creds.set_configured_data_dir(str(self.tmp))
        code, out, err = run_cli(["auth", "clear-data-dir"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "OpenCode data directory reset to the default\n")
        self.assertEqual(err, "")
        self.assertIsNone(creds.get_configured_data_dir())

    def test_configured_dir_drives_resolution(self):
        self._env(OCGO_DB="")
        custom = self.tmp / "custom-opencode"
        custom.mkdir()
        (custom / "auth.json").write_text(
            json.dumps({"opencode": {"type": "oauth", "access": TOKEN}}),
            encoding="utf-8",
        )
        code, _out, _err = run_cli(["auth", "set-data-dir", str(custom)])
        self.assertEqual(code, 0)
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("Source:  OpenCode auth.json file", out)
        self.assertIn("test-t…mnop", out)
        self.assertNotIn(TOKEN, out)


if __name__ == "__main__":
    unittest.main()
