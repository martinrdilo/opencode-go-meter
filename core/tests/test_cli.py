"""Tests for ocgo.cli: credential/API calls are patched; no network."""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _support import temp_dir
from ocgo import __version__, api, cache, cli, creds
from ocgo import format as fmt

TOKEN = "test-token-abcdefghijklmnop"


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


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))

    def _env(self, **values):
        patcher = mock.patch.dict(os.environ, values, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)


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


class AuthShowTests(CliTestCase):
    def test_env_token_shows_only_masked_hint(self):
        self._env(OCGO_TOKEN=TOKEN, OCGO_DB=str(self.tmp / "missing.db"))
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  OCGO_TOKEN environment", out)
        self.assertIn("Token:   test-t…mnop", out)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn(TOKEN, err)

    def test_db_token_shows_source_and_expiry(self):
        import sqlite3

        expires_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3_600_000
        db = self.tmp / "opencode.db"
        connection = sqlite3.connect(db)
        connection.execute(
            "CREATE TABLE credential ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "integration_id TEXT NOT NULL, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO credential (integration_id, value) VALUES (?, ?)",
            ("opencode", json.dumps({"access": TOKEN, "expires": expires_ms})),
        )
        connection.commit()
        connection.close()
        self._env(OCGO_DB=str(db))
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  OpenCode local database", out)
        self.assertIn("test-t…mnop", out)
        self.assertIn("Expires: ", out)
        self.assertNotIn(TOKEN, out)
        self.assertNotIn(TOKEN, err)

    def test_missing_credential_is_friendly(self):
        self._env(OCGO_DB=str(self.tmp / "missing.db"))
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("No OpenCode credential found.", err)


class StatusTests(CliTestCase):
    def test_missing_cache_is_friendly(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        code, out, err = run_cli(["status"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("ocgo refresh", err)

    def test_rows_mirror_the_console(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        cache.save(good_cache_data())
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage    2%   Resets in 4h 24m", out)
        self.assertIn("Weekly usage    64%   Resets in 3d 0h", out)
        self.assertIn("Monthly usage   58%   Resets in 9d 3h", out)
        self.assertNotIn("\x1b", out)
        self.assertEqual(err, "")

    def test_warning_line_when_last_error(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
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
        self._env(XDG_CACHE_HOME=str(self.tmp))
        cache.save(good_cache_data())
        raw = cache.cache_path().read_text(encoding="utf-8")
        code, out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(out, raw)
        self.assertEqual(err, "")

    def test_json_without_cache_exits_1(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        code, out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("ocgo refresh", err)

    def test_non_dict_windows_is_handled_gracefully(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
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
        self._env(XDG_CACHE_HOME=str(self.tmp))
        data = good_cache_data()
        data["windows"]["weekly"] = [1]
        cache.save(data)
        code, out, _ = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Weekly usage   n/a   Resets in n/a", out)

    def test_tty_uses_per_window_colors(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
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
    def _fake_credential(self):
        return creds.Credential(token=TOKEN, source="OCGO_TOKEN environment")

    def test_refresh_writes_cache_and_summary(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._fake_credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertIn(
            "Refreshed OpenCode Go: rolling 2% · weekly 64% · monthly 58%", out
        )
        self.assertEqual(err, "")
        data = cache.load()
        self.assertEqual(data["windows"]["weekly"]["percent"], 64)
        self.assertEqual(data["windows"]["monthly"]["resets_at"], None)
        self.assertIsNone(data["last_error"])
        self.assertIsNotNone(fmt.parse_iso(data["fetched_at"]))
        self.assertNotIn(TOKEN, out + err)

    def test_refresh_failure_keeps_last_good_data(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        good = good_cache_data()
        cache.save(good)
        error = api.ApiError("network error contacting opencode.ai: boom")
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._fake_credential()
            ),
            mock.patch.object(cli.api, "fetch_status", side_effect=error),
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertIn("network error contacting opencode.ai: boom", err)
        data = cache.load()
        self.assertEqual(data["windows"], good["windows"])
        self.assertEqual(data["fetched_at"], good["fetched_at"])
        self.assertEqual(data["last_error"], str(error))
        self.assertIsNotNone(fmt.parse_iso(data["last_error_at"]))

    def test_refresh_without_credential_writes_nothing(self):
        self._env(XDG_CACHE_HOME=str(self.tmp), OCGO_DB=str(self.tmp / "missing.db"))
        code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertIn("No OpenCode credential found", err)
        self.assertIsNone(cache.load())


if __name__ == "__main__":
    unittest.main()
