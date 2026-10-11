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
from test_accounts import _fake_secret_tool_source

from ocgo import __version__, accounts, api, cache, cli, creds
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


def billing_status_payload() -> dict:
    """The live billing/status capture (odd/tasks/credits-panel.md, 2026-10-10)."""
    return {
        "billingMode": "prepaid",
        "mode": "pay-as-you-go",
        "balanceMicroCents": "312600514",
        "creditLimitMicroCents": None,
        "availableMicroCents": "312600514",
        "canPurchaseCredits": True,
        "canEnableAutoRecharge": True,
    }


def auto_recharge_payload() -> dict:
    """The live billing/auto-recharge capture (2026-10-10)."""
    return {
        "enabled": False,
        "thresholdDollars": 5,
        "rechargeAmountDollars": 20,
        "pending": False,
        "failureReason": None,
    }


class CliTestCase(unittest.TestCase):
    def setUp(self):
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
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ),
            mock.patch.object(
                cli.api, "fetch_auto_recharge", return_value=auto_recharge_payload()
            ),
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
        self.assertEqual(data["credits"]["available_usd"], 3.126)
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


_ZEN_KEY = "oc_sk_test_abcdefghijklmnop1234"
_OTHER_KEY = "oc_sk_test_zyxwvutsrqponmlk9876"


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


class AccountCliTestCase(CliTestCase):
    def setUp(self):
        super().setUp()
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()
        self.empty_bin = self.tmp / "empty-bin"
        self.empty_bin.mkdir()
        self.secrets = self.tmp / "secrets"
        self.secrets.mkdir()
        tool = self.bin_dir / "secret-tool"
        tool.write_text(_fake_secret_tool_source(), encoding="utf-8")
        tool.chmod(0o755)

    def _isolate(self, with_tool: bool = True, **extra):
        values = {
            "FAKE_SECRET_TOOL_DIR": str(self.secrets),
            "PATH": str(self.bin_dir if with_tool else self.empty_bin),
        }
        values.update(extra)
        self._env(**values)

    def _seed_account(self, account_id="work", label="Work", key=_ZEN_KEY):
        accounts.add_account(account_id, label)
        hint = accounts.store_secret(account_id, key)
        accounts.update_hint(account_id, hint)
        return hint

    def _seed_db_account(self, account_id="login", label="Login"):
        """Write a v2 registry with a single opencode-db account."""
        path = accounts.registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "active": account_id,
                    "accounts": [
                        {
                            "id": account_id,
                            "label": label,
                            "kind": "opencode-db",
                            "hint": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )


class FakeStdin(io.StringIO):
    def __init__(self, text: str, tty: bool = False):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


class ApiKeyReadingTests(AccountCliTestCase):
    def test_non_tty_reads_one_line(self):
        self._isolate()
        stdin = FakeStdin("  key-from-pipe  \nignored\n")
        with mock.patch.object(cli.sys, "stdin", stdin):
            self.assertEqual(cli._read_api_key(), "key-from-pipe")

    def test_tty_prompts_hidden(self):
        self._isolate()
        with (
            mock.patch.object(cli.sys, "stdin", FakeStdin("", tty=True)),
            mock.patch.object(cli.getpass, "getpass", return_value="typed-key") as prompt,
        ):
            self.assertEqual(cli._read_api_key(), "typed-key")
        prompt.assert_called_once_with("API key: ")


class AccountAddTests(AccountCliTestCase):
    def test_add_stores_key_and_registers(self):
        self._isolate()
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, out, err = run_cli(["account", "add", "work", "--label", "Work"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("work", out)
        entries, active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default", "work"])
        self.assertEqual(active, "default")
        self.assertEqual(entries[1].label, "Work")
        self.assertEqual(entries[1].hint, creds.mask_token(_ZEN_KEY))
        self.assertEqual(accounts.read_secret("work"), _ZEN_KEY)
        self.assertNotIn(_ZEN_KEY, out + err)

    def test_add_defaults_label_to_id(self):
        self._isolate()
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["account", "add", "work"])
        self.assertEqual(code, 0)
        entries, _active = accounts.list_accounts()
        self.assertEqual(entries[1].label, "work")

    def test_add_entitlement_stores_with_warning(self):
        self._isolate()
        error = api.ApiEntitlementError(
            "this account has no active OpenCode Go subscription"
        )
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, out, err = run_cli(["account", "add", "nosub"])
        self.assertEqual(code, 0)
        self.assertIn("Added account 'nosub'", out)
        self.assertIn("no active OpenCode Go subscription", err)
        self.assertEqual(accounts.read_secret("nosub"), _ZEN_KEY)

    def test_add_auth_error_stores_nothing(self):
        self._isolate()
        error = api.ApiAuthError("the API key was rejected (HTTP 401)")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, out, err = run_cli(["account", "add", "work"])
        self.assertEqual(code, 1)
        self.assertIn("API key was rejected", err)
        self.assertIsNone(accounts.load_registry())
        self.assertFalse(accounts.has_secret("work"))

    def test_add_network_error_stores_nothing(self):
        self._isolate()
        error = api.ApiError("network error contacting opencode.ai: boom")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, _out, err = run_cli(["account", "add", "work"])
        self.assertEqual(code, 1)
        self.assertIn("boom", err)
        self.assertIsNone(accounts.load_registry())
        self.assertFalse(accounts.has_secret("work"))

    def test_add_duplicate_is_rejected_without_prompt(self):
        self._isolate()
        self._seed_account("work")
        with (
            mock.patch.object(cli, "_read_api_key") as read,
            mock.patch.object(cli.api, "fetch_zen_status") as fetch,
        ):
            code, _out, err = run_cli(["account", "add", "work"])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        read.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(accounts.read_secret("work"), _ZEN_KEY)

    def test_add_default_id_after_removal(self):
        self._isolate()
        code, _out, _err = run_cli(["account", "remove", "default"])
        self.assertEqual(code, 0)
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["account", "add", "default"])
        self.assertEqual(code, 0)
        entries, active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default"])
        self.assertEqual(active, "default")
        self.assertEqual(accounts.read_secret("default"), _ZEN_KEY)

    def test_add_invalid_id_is_rejected(self):
        self._isolate()
        with mock.patch.object(cli, "_read_api_key") as read:
            code, _out, err = run_cli(["account", "add", "Bad"])
        self.assertEqual(code, 1)
        self.assertIn("invalid account id", err)
        read.assert_not_called()
        self.assertIsNone(accounts.load_registry())

    def test_add_empty_key_is_rejected(self):
        self._isolate()
        with (
            mock.patch.object(cli, "_read_api_key", return_value="   "),
            mock.patch.object(cli.api, "fetch_zen_status") as fetch,
        ):
            code, _out, err = run_cli(["account", "add", "work"])
        self.assertEqual(code, 1)
        self.assertIn("no API key provided", err)
        fetch.assert_not_called()
        self.assertIsNone(accounts.load_registry())

    def test_add_store_file_without_keyring(self):
        self._isolate(with_tool=False)
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["account", "add", "work", "--store", "file"])
        self.assertEqual(code, 0)
        self.assertEqual(accounts.read_secret("work"), _ZEN_KEY)
        self.assertTrue(accounts.secret_file_path("work").is_file())

    def test_add_auto_without_keyring_fails_without_registering(self):
        self._isolate(with_tool=False)
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_ZEN_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, err = run_cli(["account", "add", "work"])
        self.assertEqual(code, 1)
        self.assertIn("libsecret-tools", err)
        self.assertIsNone(accounts.load_registry())
        self.assertFalse(accounts.has_secret("work"))

    def test_add_file_replaces_an_orphan_keyring_entry(self):
        self._isolate()
        accounts.store_secret("work", _ZEN_KEY)  # orphan entry, no registry row
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_OTHER_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(["account", "add", "work", "--store", "file"])
        self.assertEqual(code, 0)
        self.assertEqual(accounts.read_secret("work"), _OTHER_KEY)
        self.assertFalse((self.secrets / "items" / "work").exists())
        self.assertTrue(accounts.secret_file_path("work").is_file())


class AccountSetKeyTests(AccountCliTestCase):
    def test_set_key_replaces_hint_and_secret(self):
        self._isolate()
        self._seed_account("work")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_OTHER_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, out, err = run_cli(["account", "set-key", "work"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("Updated key for account 'work'", out)
        entries, _active = accounts.list_accounts()
        self.assertEqual(entries[1].hint, creds.mask_token(_OTHER_KEY))
        self.assertEqual(accounts.read_secret("work"), _OTHER_KEY)
        self.assertNotIn(_OTHER_KEY, out + err)

    def test_set_key_auth_failure_keeps_the_old_key(self):
        self._isolate()
        self._seed_account("work")
        error = api.ApiAuthError("the API key was rejected (HTTP 401)")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_OTHER_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, _out, err = run_cli(["account", "set-key", "work"])
        self.assertEqual(code, 1)
        self.assertIn("API key was rejected", err)
        entries, _active = accounts.list_accounts()
        self.assertEqual(entries[1].hint, creds.mask_token(_ZEN_KEY))
        self.assertEqual(accounts.read_secret("work"), _ZEN_KEY)

    def test_set_key_entitlement_updates_with_warning(self):
        self._isolate()
        self._seed_account("work")
        error = api.ApiEntitlementError(
            "this account has no active OpenCode Go subscription"
        )
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_OTHER_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=error),
        ):
            code, _out, err = run_cli(["account", "set-key", "work"])
        self.assertEqual(code, 0)
        self.assertIn("no active OpenCode Go subscription", err)
        self.assertEqual(accounts.read_secret("work"), _OTHER_KEY)

    def test_set_key_file_rotates_keyring_backed_account_for_real(self):
        self._isolate()
        self._seed_account("work")
        with (
            mock.patch.object(cli, "_read_api_key", return_value=_OTHER_KEY),
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
        ):
            code, _out, _err = run_cli(
                ["account", "set-key", "work", "--store", "file"]
            )
        self.assertEqual(code, 0)
        self.assertFalse((self.secrets / "items" / "work").exists())
        self.assertEqual(accounts.read_secret("work"), _OTHER_KEY)
        with mock.patch.object(
            cli.api, "fetch_zen_status", return_value=zen_payload()
        ) as fetch:
            code, _out, _err = run_cli(["refresh", "--account", "work"])
        self.assertEqual(code, 0)
        fetch.assert_called_once_with(_OTHER_KEY)

    def test_set_key_refuses_db_accounts(self):
        self._isolate()
        self._seed_db_account()
        with mock.patch.object(cli, "_read_api_key") as read:
            code, _out, err = run_cli(["account", "set-key", "login"])
        self.assertEqual(code, 1)
        self.assertIn("uses the OpenCode login", err)
        read.assert_not_called()

    def test_set_key_unknown_account_fails(self):
        self._isolate()
        self._seed_account("work")
        with mock.patch.object(cli, "_read_api_key") as read:
            code, _out, err = run_cli(["account", "set-key", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)
        read.assert_not_called()


class AccountListTests(AccountCliTestCase):
    def test_without_registry_shows_default(self):
        self._isolate()
        code, out, err = run_cli(["account", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("* default", out)
        self.assertIn("opencode-db", out)

    def test_json_exact_shape_without_registry(self):
        self._isolate()
        code, out, _err = run_cli(["account", "list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {
                "schema": 2,
                "active": "default",
                "accounts": [
                    {
                        "id": "default",
                        "label": "Default",
                        "kind": "opencode-db",
                        "hint": None,
                        "active": True,
                    }
                ],
            },
        )

    def test_json_shape_with_accounts_and_active(self):
        self._isolate()
        self._seed_account("work", "Work")
        self._seed_account("personal", "Personal", key=_OTHER_KEY)
        accounts.set_active("personal")
        code, out, _err = run_cli(["account", "list", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(list(payload), ["schema", "active", "accounts"])
        self.assertEqual(payload["schema"], 2)
        self.assertEqual(payload["active"], "personal")
        self.assertEqual(
            [account["id"] for account in payload["accounts"]],
            ["default", "work", "personal"],
        )
        self.assertEqual(
            list(payload["accounts"][1]),
            ["id", "label", "kind", "hint", "active"],
        )
        self.assertEqual(payload["accounts"][0]["active"], False)
        self.assertEqual(payload["accounts"][1]["active"], False)
        self.assertEqual(payload["accounts"][2]["active"], True)
        self.assertEqual(payload["accounts"][1]["hint"], creds.mask_token(_ZEN_KEY))
        self.assertNotIn(_ZEN_KEY, out)

    def test_human_list_marks_the_active_account(self):
        self._isolate()
        self._seed_account("work", "Work")
        accounts.set_active("work")
        code, out, _err = run_cli(["account", "list"])
        self.assertEqual(code, 0)
        self.assertIn("* work", out)
        self.assertIn("oc_sk_", out)
        self.assertNotIn(_ZEN_KEY, out)


class AccountUseRemoveTests(AccountCliTestCase):
    def test_use_switches_the_active_account(self):
        self._isolate()
        self._seed_account("work")
        code, out, err = run_cli(["account", "use", "work"])
        self.assertEqual(code, 0)
        self.assertIn("Active account: work", out)
        self.assertEqual(accounts.get_active_id(), "work")
        self.assertEqual(err, "")

    def test_use_unknown_fails(self):
        self._isolate()
        self._seed_account("work")
        code, _out, err = run_cli(["account", "use", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_use_default_switches_back(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        code, _out, _err = run_cli(["account", "use", "default"])
        self.assertEqual(code, 0)
        self.assertEqual(accounts.get_active_id(), "default")

    def test_remove_cleans_secret_and_cache(self):
        self._isolate()
        self._seed_account("work")
        cache.save(good_cache_data(), cache.cache_path("work"))
        code, out, err = run_cli(["account", "remove", "work"])
        self.assertEqual(code, 0)
        self.assertIn("Removed account 'work'", out)
        self.assertEqual(err, "")
        entries, _active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default"])
        self.assertFalse(accounts.has_secret("work"))
        self.assertFalse(cache.cache_path("work").exists())
        self.assertFalse(cache.cache_path("work").parent.exists())

    def test_remove_active_resets_to_default(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        code, _out, _err = run_cli(["account", "remove", "work"])
        self.assertEqual(code, 0)
        self.assertEqual(accounts.get_active_id(), "default")

    def test_remove_default_works(self):
        self._isolate()
        code, out, err = run_cli(["account", "remove", "default"])
        self.assertEqual(code, 0)
        self.assertIn("Removed account 'default'", out)
        self.assertEqual(err, "")
        entries, active = accounts.list_accounts()
        self.assertEqual(entries, [])
        self.assertIsNone(active)
        registry = accounts.load_registry()
        self.assertEqual(registry["version"], 2)
        self.assertIsNone(registry["active"])
        self.assertEqual(registry["accounts"], [])

    def test_remove_unknown_fails(self):
        self._isolate()
        self._seed_account("work")
        code, _out, err = run_cli(["account", "remove", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_remove_failure_leaves_the_cache_untouched(self):
        self._isolate()
        cache.save(good_cache_data(), cache.cache_path("ghost"))
        code, _out, err = run_cli(["account", "remove", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)
        self.assertTrue(cache.cache_path("ghost").exists())

    def test_remove_succeeds_when_cache_cleanup_fails(self):
        self._isolate()
        self._seed_account("work")
        with mock.patch.object(
            cli.cache, "remove_account_cache", side_effect=OSError("boom")
        ):
            code, out, err = run_cli(["account", "remove", "work"])
        self.assertEqual(code, 0)
        self.assertIn("Removed account 'work'", out)
        self.assertIn("could not clean its cache", err)
        entries, _active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default"])

    def test_remove_default_deletes_the_legacy_cache(self):
        self._isolate()
        cache.save(good_cache_data())
        self.assertTrue(cache.cache_path().exists())
        code, _out, _err = run_cli(["account", "remove", "default"])
        self.assertEqual(code, 0)
        self.assertFalse(cache.cache_path().exists())

    def test_remove_default_warns_when_legacy_cache_unlink_fails(self):
        self._isolate()
        cache.save(good_cache_data())
        with mock.patch.object(Path, "unlink", side_effect=OSError("boom")):
            code, out, err = run_cli(["account", "remove", "default"])
        self.assertEqual(code, 0)
        self.assertIn("Removed account 'default'", out)
        self.assertIn("could not clean its cache", err)
        self.assertIn("boom", err)
        self.assertTrue(cache.cache_path().exists())

    def test_remove_named_account_keeps_the_legacy_cache(self):
        self._isolate()
        self._seed_account("work")
        cache.save(good_cache_data())
        code, _out, _err = run_cli(["account", "remove", "work"])
        self.assertEqual(code, 0)
        self.assertTrue(cache.cache_path().exists())

    def test_readd_default_after_removal_starts_clean(self):
        self._isolate()
        cache.save(good_cache_data())
        code, _out, _err = run_cli(["account", "remove", "default"])
        self.assertEqual(code, 0)
        accounts.add_account("default", "Again")
        code, _out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("no cache", err)


class RefreshAccountTests(AccountCliTestCase):
    def _credential(self):
        return creds.Credential(token="console-token-abcdefgh", source="test")

    def test_refresh_without_registry_is_byte_compatible(self):
        self._isolate()
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ),
            mock.patch.object(
                cli.api, "fetch_auto_recharge", return_value=auto_recharge_payload()
            ),
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertEqual(
            out,
            "Refreshed OpenCode Go: rolling 2% · weekly 64% · monthly 58% · $3.13\n",
        )
        self.assertEqual(err, "")
        self.assertIsNotNone(cache.load())
        self.assertFalse((self.tmp / "cache" / "ocgo" / "accounts").exists())

    def test_refresh_active_named_uses_zen_and_named_cache(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        with mock.patch.object(
            cli.api, "fetch_zen_status", return_value=zen_payload()
        ) as fetch:
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertIn("Refreshed OpenCode Go (work): rolling 12%", out)
        fetch.assert_called_once_with(_ZEN_KEY)
        data = cache.load(cache.cache_path("work"))
        self.assertEqual(data["windows"]["rolling"]["percent"], 12)
        self.assertIsNone(data["windows"]["rolling"]["used_usd"])
        self.assertIsNone(cache.load())
        self.assertNotIn(_ZEN_KEY, out + err)

    def test_refresh_account_default_with_registry_prefixes(self):
        self._isolate()
        self._seed_account("work")
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ),
            mock.patch.object(
                cli.api, "fetch_auto_recharge", return_value=auto_recharge_payload()
            ),
        ):
            code, out, _err = run_cli(["refresh", "--account", "default"])
        self.assertEqual(code, 0)
        self.assertIn("Refreshed OpenCode Go (default):", out)
        self.assertIsNotNone(cache.load())

    def test_refresh_named_without_secret_fails_and_writes_nothing(self):
        self._isolate()
        accounts.add_account("work", "Work")
        code, _out, err = run_cli(["refresh", "--account", "work"])
        self.assertEqual(code, 1)
        self.assertIn("no secret found", err)
        self.assertIn("account 'work':", err)
        self.assertIn("ocgo account set-key work", err)
        self.assertIsNone(cache.load(cache.cache_path("work")))

    def test_refresh_failure_on_named_db_account_is_labeled(self):
        self._isolate()
        self._seed_db_account()
        with mock.patch.object(
            cli.creds,
            "resolve_credential",
            side_effect=creds.CredentialError("No OpenCode credential found."),
        ):
            code, _out, err = run_cli(["refresh", "--account", "login"])
        self.assertEqual(code, 1)
        self.assertIn("account 'login':", err)
        self.assertIn("No OpenCode credential found.", err)

    def test_refresh_failure_without_registry_is_unlabeled(self):
        self._isolate()
        with mock.patch.object(
            cli.creds,
            "resolve_credential",
            side_effect=creds.CredentialError("No OpenCode credential found."),
        ):
            code, _out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "ocgo: No OpenCode credential found.\n")

    def test_refresh_named_resolution_failure_records_last_error(self):
        self._isolate()
        accounts.add_account("work", "Work")  # no stored secret
        good = good_cache_data()
        cache.save(good, cache.cache_path("work"))
        code, _out, err = run_cli(["refresh", "--account", "work"])
        self.assertEqual(code, 1)
        self.assertIn("no secret found", err)
        data = cache.load(cache.cache_path("work"))
        self.assertIsNotNone(data)
        self.assertEqual(data["windows"], good["windows"])
        self.assertIn("no secret found", data["last_error"])
        self.assertIsNotNone(fmt.parse_iso(data["last_error_at"]))

    def test_refresh_account_and_all_are_exclusive(self):
        self._isolate()
        self.assertEqual(run_cli(["refresh", "--account", "work", "--all"])[0], 2)

    def test_refresh_unknown_account_fails(self):
        self._isolate()
        self._seed_account("work")
        code, _out, err = run_cli(["refresh", "--account", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_refresh_failure_records_last_error_in_named_cache(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        good = good_cache_data()
        cache.save(good, cache.cache_path("work"))
        error = api.ApiError("network error contacting opencode.ai: boom")
        with mock.patch.object(cli.api, "fetch_zen_status", side_effect=error):
            code, _out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertIn("boom", err)
        data = cache.load(cache.cache_path("work"))
        self.assertEqual(data["windows"], good["windows"])
        self.assertEqual(data["last_error"], str(error))
        self.assertIsNotNone(fmt.parse_iso(data["last_error_at"]))

    def test_refresh_all_continues_after_failures(self):
        self._isolate()
        self._seed_account("work", key=_ZEN_KEY)
        self._seed_account("personal", "Personal", key=_OTHER_KEY)
        accounts.set_active("work")
        cache.save(good_cache_data(), cache.cache_path("work"))

        def zen(token):
            if token == _ZEN_KEY:
                raise api.ApiError("network error contacting opencode.ai: boom")
            return zen_payload()

        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ),
            mock.patch.object(
                cli.api, "fetch_auto_recharge", return_value=auto_recharge_payload()
            ),
            mock.patch.object(cli.api, "fetch_zen_status", side_effect=zen),
        ):
            code, out, err = run_cli(["refresh", "--all"])
        self.assertEqual(code, 1)
        self.assertIn("(default)", out)
        self.assertIn("(personal)", out)
        self.assertIn("account 'work'", err)
        self.assertIn("boom", err)
        self.assertIsNotNone(cache.load())
        personal = cache.load(cache.cache_path("personal"))
        self.assertIsNone(personal["last_error"])
        work = cache.load(cache.cache_path("work"))
        self.assertEqual(work["last_error"], "network error contacting opencode.ai: boom")


class CreditsRefreshTests(AccountCliTestCase):
    def _credential(self):
        return creds.Credential(token="console-token-abcdefgh", source="test")

    def test_db_refresh_caches_credits_and_summary_suffix(self):
        self._isolate()
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ) as billing,
            mock.patch.object(
                cli.api, "fetch_auto_recharge", return_value=auto_recharge_payload()
            ) as auto,
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("rolling 2% · weekly 64% · monthly 58% · $3.13", out)
        billing.assert_called_once_with("console-token-abcdefgh")
        auto.assert_called_once_with("console-token-abcdefgh")
        data = cache.load()
        self.assertEqual(
            data["credits"],
            {
                "available_usd": 3.126,
                "state": "low",
                "billing_mode": "prepaid",
                "auto_recharge": {
                    "enabled": False,
                    "threshold_usd": 5.0,
                    "amount_usd": 20.0,
                    "pending": False,
                    "failed": False,
                },
            },
        )
        self.assertIs(data["extra_usage"], True)
        self.assertIsNone(data["last_error"])

    def test_billing_failure_never_fails_the_refresh(self):
        self._isolate()
        error = api.ApiError(
            "billing request rejected (HTTP 403) — credits are available only "
            "for the OpenCode login account"
        )
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(cli.api, "fetch_billing_status", side_effect=error),
            mock.patch.object(cli.api, "fetch_auto_recharge") as auto,
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertNotIn("$", out)
        auto.assert_not_called()
        data = cache.load()
        self.assertEqual(data["credits"], {"error": str(error)})
        self.assertIsNone(data["last_error"])
        self.assertEqual(data["windows"]["weekly"]["percent"], 64)

    def test_auto_recharge_failure_keeps_the_balance(self):
        self._isolate()
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ),
            mock.patch.object(cli.api, "fetch_status", return_value=live_payload()),
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ),
            mock.patch.object(
                cli.api,
                "fetch_auto_recharge",
                side_effect=api.ApiError("network error contacting opencode.ai: boom"),
            ),
        ):
            code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("· $3.13", out)
        data = cache.load()
        self.assertEqual(data["credits"]["state"], "low")
        self.assertIsNone(data["credits"]["auto_recharge"])

    def test_api_key_refresh_does_not_touch_billing(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        with (
            mock.patch.object(cli.api, "fetch_zen_status", return_value=zen_payload()),
            mock.patch.object(cli.api, "fetch_billing_status") as billing,
            mock.patch.object(cli.api, "fetch_auto_recharge") as auto,
        ):
            code, _out, _err = run_cli(["refresh"])
        self.assertEqual(code, 0)
        billing.assert_not_called()
        auto.assert_not_called()
        data = cache.load(cache.cache_path("work"))
        self.assertIsNone(data["credits"])
        self.assertIsNone(data["extra_usage"])


class StatusAccountTests(AccountCliTestCase):
    def test_status_uses_the_active_named_cache(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        cache.save(good_cache_data(), cache.cache_path("work"))
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage    2%", out)
        self.assertEqual(err, "")
        self.assertIsNone(cache.load())

    def test_status_account_default_reads_the_legacy_cache(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        named = good_cache_data()
        named["windows"]["rolling"]["percent"] = 99
        cache.save(named, cache.cache_path("work"))
        cache.save(good_cache_data())
        code, out, _err = run_cli(["status", "--account", "default", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage    2%", out)
        self.assertNotIn("99%", out)

    def test_status_json_prints_the_named_cache_verbatim(self):
        self._isolate()
        self._seed_account("work")
        cache.save(good_cache_data(), cache.cache_path("work"))
        raw = cache.cache_path("work").read_text(encoding="utf-8")
        code, out, err = run_cli(["status", "--json", "--account", "work"])
        self.assertEqual(code, 0)
        self.assertEqual(out, raw)
        self.assertEqual(err, "")

    def test_status_named_missing_cache_is_friendly(self):
        self._isolate()
        self._seed_account("work")
        code, _out, err = run_cli(["status", "--account", "work"])
        self.assertEqual(code, 1)
        self.assertIn("no cached usage yet", err)
        self.assertIn("ocgo refresh", err)

    def test_status_unknown_account_fails(self):
        self._isolate()
        self._seed_account("work")
        code, _out, err = run_cli(["status", "--account", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_status_without_registry_still_reads_the_legacy_cache(self):
        self._isolate()
        cache.save(good_cache_data())
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Rolling usage    2%", out)
        self.assertEqual(err, "")


class CreditsStatusTests(CliTestCase):
    def _save_credits(self, credits):
        data = good_cache_data()
        data["credits"] = credits
        cache.save(data)

    def test_low_state_row(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits(
            {"available_usd": 3.126, "state": "low", "billing_mode": "prepaid"}
        )
        code, out, err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Credits        $3.13   Running low", out)
        self.assertEqual(err, "")

    def test_ok_state_row_has_no_suffix(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits(
            {"available_usd": 12.5, "state": "ok", "billing_mode": "prepaid"}
        )
        code, out, _err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        line = next(line for line in out.splitlines() if line.startswith("Credits"))
        self.assertEqual(line, "Credits        $12.50")

    def test_empty_state_row(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits(
            {"available_usd": 0.0, "state": "empty", "billing_mode": "prepaid"}
        )
        code, out, _err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Credits        $0.00   No credits left", out)

    def test_error_row(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits({"error": "billing request rejected (HTTP 403)"})
        code, out, _err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Credits        n/a   unavailable", out)
        self.assertNotIn("HTTP 403", out)

    def test_no_credits_key_means_no_row(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        cache.save(good_cache_data())
        code, out, _err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertNotIn("Credits", out)

    def test_null_credits_means_no_row(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits(None)
        code, out, _err = run_cli(["status", "--no-color"])
        self.assertEqual(code, 0)
        self.assertNotIn("Credits", out)

    def test_low_row_is_amber_on_a_tty(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits({"available_usd": 3.126, "state": "low"})
        out = TtyStream()
        with mock.patch.object(cli.sys, "stdout", out):
            code = cli.main(["status"])
        self.assertEqual(code, 0)
        self.assertIn(
            "\x1b[33mCredits        $3.13   Running low\x1b[0m", out.getvalue()
        )

    def test_empty_row_is_red_on_a_tty(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits({"available_usd": 0.0, "state": "empty"})
        out = TtyStream()
        with mock.patch.object(cli.sys, "stdout", out):
            code = cli.main(["status"])
        self.assertEqual(code, 0)
        self.assertIn(
            "\x1b[31mCredits        $0.00   No credits left\x1b[0m", out.getvalue()
        )

    def test_json_stays_verbatim_with_credits(self):
        self._env(XDG_CACHE_HOME=str(self.tmp))
        self._save_credits(
            {"available_usd": 3.126, "state": "low", "billing_mode": "prepaid"}
        )
        raw = cache.cache_path().read_text(encoding="utf-8")
        code, out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(out, raw)
        self.assertEqual(err, "")


class AuthShowAccountTests(AccountCliTestCase):
    def test_named_account_shows_source_and_masked_hint(self):
        self._isolate()
        hint = self._seed_account("work")
        code, out, err = run_cli(["auth", "show", "--account", "work"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  stored API key (account 'work')", out)
        self.assertIn(f"Token:   {hint}", out)
        self.assertNotIn("Expires:", out)
        self.assertNotIn(_ZEN_KEY, out + err)

    def test_active_named_account_is_the_default_target(self):
        self._isolate()
        self._seed_account("work")
        accounts.set_active("work")
        code, out, _err = run_cli(["auth", "show"])
        self.assertEqual(code, 0)
        self.assertIn("stored API key (account 'work')", out)

    def test_default_account_unchanged(self):
        self._isolate(OCGO_TOKEN="console-token-abcdefgh")
        code, out, err = run_cli(["auth", "show", "--account", "default"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  OCGO_TOKEN environment", out)
        self.assertIn("consol…efgh", out)
        self.assertNotIn("console-token-abcdefgh", out + err)

    def test_unknown_account_fails(self):
        self._isolate()
        self._seed_account("work")
        code, _out, err = run_cli(["auth", "show", "--account", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_account_without_hint_or_secret_fails_actionably(self):
        self._isolate()
        accounts.add_account("work", "Work")
        code, _out, err = run_cli(["auth", "show", "--account", "work"])
        self.assertEqual(code, 1)
        self.assertIn("ocgo account set-key work", err)


class EmptyAccountsTests(AccountCliTestCase):
    def _empty(self):
        self._isolate()
        accounts.remove_account("default")

    def test_refresh_errors(self):
        self._empty()
        code, out, err = run_cli(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no accounts configured — run 'ocgo account add <id>'", err)

    def test_refresh_all_errors(self):
        self._empty()
        code, _out, err = run_cli(["refresh", "--all"])
        self.assertEqual(code, 1)
        self.assertIn("no accounts configured", err)

    def test_status_errors(self):
        self._empty()
        code, out, err = run_cli(["status"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no accounts configured", err)

    def test_status_json_errors(self):
        self._empty()
        code, out, err = run_cli(["status", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no accounts configured", err)

    def test_auth_show_errors(self):
        self._empty()
        code, out, err = run_cli(["auth", "show"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no accounts configured", err)

    def test_list_human_empty(self):
        self._empty()
        code, out, err = run_cli(["account", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "no accounts configured\n")
        self.assertEqual(err, "")

    def test_list_json_empty_schema_2(self):
        self._empty()
        code, out, err = run_cli(["account", "list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            json.loads(out),
            {"schema": 2, "active": None, "accounts": []},
        )


class DbKindTests(AccountCliTestCase):
    def _credential(self):
        return creds.Credential(token="console-token-abcdefgh", source="test")

    def test_db_kind_named_refresh_uses_console_endpoint(self):
        self._isolate()
        self._seed_db_account()
        with (
            mock.patch.object(
                cli.creds, "resolve_credential", return_value=self._credential()
            ) as resolve,
            mock.patch.object(
                cli.api, "fetch_status", return_value=live_payload()
            ) as fetch,
            mock.patch.object(
                cli.api, "fetch_billing_status", return_value=billing_status_payload()
            ) as billing,
            mock.patch.object(
                cli.api, "fetch_auto_recharge", return_value=auto_recharge_payload()
            ) as auto,
            mock.patch.object(cli.api, "fetch_zen_status") as zen,
        ):
            code, out, _err = run_cli(["refresh", "--account", "login"])
        self.assertEqual(code, 0)
        resolve.assert_called_once_with()
        fetch.assert_called_once_with("console-token-abcdefgh")
        billing.assert_called_once_with("console-token-abcdefgh")
        auto.assert_called_once_with("console-token-abcdefgh")
        zen.assert_not_called()
        self.assertIn("Refreshed OpenCode Go (login):", out)
        self.assertIsNotNone(cache.load(cache.cache_path("login")))

    def test_db_kind_named_auth_show_uses_db_source(self):
        self._isolate()
        self._seed_db_account()
        with mock.patch.object(
            cli.creds, "resolve_credential", return_value=self._credential()
        ):
            code, out, err = run_cli(["auth", "show", "--account", "login"])
        self.assertEqual(code, 0)
        self.assertIn("Source:  test", out)
        self.assertIn("Token:   consol…efgh", out)
        self.assertEqual(err, "")

    def test_api_key_account_with_default_id_uses_zen(self):
        self._isolate()
        accounts.remove_account("default")
        accounts.add_account("default", "Work key")
        hint = accounts.store_secret("default", _ZEN_KEY)
        accounts.update_hint("default", hint)
        with mock.patch.object(
            cli.api, "fetch_zen_status", return_value=zen_payload()
        ) as zen:
            code, _out, _err = run_cli(["refresh", "--account", "default"])
        self.assertEqual(code, 0)
        zen.assert_called_once_with(_ZEN_KEY)


if __name__ == "__main__":
    unittest.main()
