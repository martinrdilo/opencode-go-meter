"""Tests for ocgo.accounts (temp XDG dirs and a fake secret-tool only)."""

import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from _support import temp_dir
from ocgo import accounts, creds

_SECRET = "oc_sk_live_abcdefghijklmnop1234"

_FAKE_SECRET_TOOL_BODY = """#!/usr/bin/env python3
import os
import pathlib
import sys

base = pathlib.Path(os.environ["FAKE_SECRET_TOOL_DIR"])
items = base / "items"
items.mkdir(parents=True, exist_ok=True)

with (base / "argv.log").open("a", encoding="utf-8") as log:
    log.write("\\x00".join(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
command = args[0] if args else ""

if os.environ.get("FAKE_SECRET_TOOL_FAIL") == command:
    sys.exit(3)


def account_id():
    if "account" in args:
        return args[args.index("account") + 1]
    return ""


if command == "store":
    target = items / account_id()
    target.write_text(sys.stdin.read(), encoding="utf-8")
    os.chmod(target, 0o600)
elif command == "lookup":
    target = items / account_id()
    if not target.is_file():
        sys.exit(1)
    sys.stdout.write(target.read_text(encoding="utf-8"))
    sys.stdout.write("\\n")
elif command == "clear":
    try:
        (items / account_id()).unlink()
    except FileNotFoundError:
        pass
else:
    sys.exit(2)
sys.exit(0)
"""


def _fake_secret_tool_source() -> str:
    return _FAKE_SECRET_TOOL_BODY.replace(
        "#!/usr/bin/env python3", f"#!{sys.executable}"
    )


class AccountsTestCase(unittest.TestCase):
    """Isolated XDG dirs; secret-tool is absent unless a test opts in."""

    def setUp(self):
        self.tmp = Path(self.enterContext(temp_dir()))
        self.secrets = self.tmp / "secrets"
        self.secrets.mkdir()
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()
        self.empty_bin = self.tmp / "empty-bin"
        self.empty_bin.mkdir()
        tool = self.bin_dir / "secret-tool"
        tool.write_text(_fake_secret_tool_source(), encoding="utf-8")
        tool.chmod(0o755)
        base_env = {
            "HOME": str(self.tmp / "home"),
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "XDG_DATA_HOME": str(self.tmp / "data"),
            "FAKE_SECRET_TOOL_DIR": str(self.secrets),
            "PATH": str(self.empty_bin),
        }
        patcher = mock.patch.dict(os.environ, base_env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_fake_tool(self):
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.bin_dir)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_registry(self, data):
        path = accounts.registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def argv_log(self) -> str:
        log = self.secrets / "argv.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""


class PathTests(AccountsTestCase):
    def test_config_dir_uses_xdg_config_home(self):
        self.assertEqual(accounts.config_dir(), self.tmp / "config" / "ocgo")

    def test_config_dir_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home")}, clear=True):
            self.assertEqual(
                accounts.config_dir(), self.tmp / "home" / ".config" / "ocgo"
            )

    def test_registry_and_keys_paths(self):
        base = self.tmp / "config" / "ocgo"
        self.assertEqual(accounts.registry_path(), base / "accounts.json")
        self.assertEqual(accounts.keys_dir(), base / "keys")
        self.assertEqual(accounts.secret_file_path("work"), base / "keys" / "work.key")

    def test_env_var_for(self):
        self.assertEqual(accounts.env_var_for("work"), "OCGO_TOKEN_WORK")
        self.assertEqual(accounts.env_var_for("my.acct-1"), "OCGO_TOKEN_MY_ACCT_1")

    def test_secret_file_path_rejects_invalid_id(self):
        with self.assertRaises(accounts.AccountError):
            accounts.secret_file_path("../escape")


class IdValidationTests(AccountsTestCase):
    def test_valid_ids(self):
        for account_id in [
            "a",
            "work",
            "team.one",
            "team_one",
            "team-one",
            "0work",
            "a" * 64,
        ]:
            with self.subTest(account_id=account_id):
                self.assertEqual(accounts.validate_account_id(account_id), account_id)

    def test_invalid_ids(self):
        for account_id in [
            "",
            "Work",
            "-work",
            ".work",
            "_work",
            "a" * 65,
            "two words",
            "wörk",
            "work/../escape",
            None,
        ]:
            with self.subTest(account_id=account_id):
                with self.assertRaises(accounts.AccountError):
                    accounts.validate_account_id(account_id)

    def test_default_is_reserved(self):
        with self.assertRaises(accounts.AccountError):
            accounts.validate_account_id("default")

    def test_add_rejects_default(self):
        with self.assertRaises(accounts.AccountError):
            accounts.add_account("default", "Nope")
        self.assertIsNone(accounts.load_registry())

    def test_add_rejects_invalid_id(self):
        with self.assertRaises(accounts.AccountError):
            accounts.add_account("Bad", "Bad")
        self.assertIsNone(accounts.load_registry())

    def test_add_rejects_duplicate(self):
        accounts.add_account("work", "Work")
        with self.assertRaises(accounts.AccountError):
            accounts.add_account("work", "Other")

    def test_add_rejects_empty_label(self):
        with self.assertRaises(accounts.AccountError):
            accounts.add_account("work", "   ")
        self.assertIsNone(accounts.load_registry())


class RegistryTests(AccountsTestCase):
    def test_missing_registry_returns_none(self):
        self.assertIsNone(accounts.load_registry())

    def test_only_default_without_registry(self):
        entries, active = accounts.list_accounts()
        self.assertEqual(active, "default")
        self.assertEqual([account.id for account in entries], ["default"])
        self.assertEqual(entries[0].kind, "opencode-db")
        self.assertIsNone(entries[0].hint)
        self.assertEqual(accounts.get_active_id(), "default")

    def test_add_account_round_trip(self):
        account = accounts.add_account("work", "Work")
        self.assertEqual(account, accounts.Account("work", "Work", "api-key", None))
        entries, active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default", "work"])
        self.assertEqual(active, "default")

    def test_add_account_keeps_hint(self):
        account = accounts.add_account("work", "  Work  ", hint="oc_sk_…abcd")
        self.assertEqual(account.label, "Work")
        self.assertEqual(account.hint, "oc_sk_…abcd")
        entries, _active = accounts.list_accounts()
        self.assertEqual(entries[1].hint, "oc_sk_…abcd")

    def test_add_preserves_order_and_active(self):
        accounts.add_account("one", "One")
        accounts.set_active("one")
        accounts.add_account("two", "Two")
        entries, active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default", "one", "two"])
        self.assertEqual(active, "one")

    def test_registry_file_and_dir_are_private(self):
        accounts.add_account("work", "Work")
        path = accounts.registry_path()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(accounts.config_dir().stat().st_mode), 0o700)

    def test_active_falls_back_to_default(self):
        self.write_registry(
            {
                "version": 1,
                "active": "ghost",
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None}
                ],
            }
        )
        entries, active = accounts.list_accounts()
        self.assertEqual(active, "default")
        self.assertEqual([account.id for account in entries], ["default", "work"])

    def test_corrupt_json_raises(self):
        path = accounts.registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(accounts.AccountError):
            accounts.load_registry()

    def test_malformed_registries_raise(self):
        base = {"version": 1, "active": "default", "accounts": []}
        cases = {
            "not-object": [1, 2],
            "bad-version": {**base, "version": 2},
            "missing-active": {"version": 1, "accounts": []},
            "bad-active": {**base, "active": "GHOST"},
            "accounts-not-list": {**base, "accounts": {}},
            "reserved-default": {
                **base,
                "accounts": [
                    {"id": "default", "label": "D", "kind": "api-key", "hint": None}
                ],
            },
            "duplicate": {
                **base,
                "accounts": [
                    {"id": "work", "label": "W", "kind": "api-key", "hint": None},
                    {"id": "work", "label": "W2", "kind": "api-key", "hint": None},
                ],
            },
            "bad-kind": {
                **base,
                "accounts": [
                    {"id": "work", "label": "W", "kind": "opencode-db", "hint": None}
                ],
            },
            "bad-label": {
                **base,
                "accounts": [
                    {"id": "work", "label": "", "kind": "api-key", "hint": None}
                ],
            },
            "bad-hint": {
                **base,
                "accounts": [
                    {"id": "work", "label": "W", "kind": "api-key", "hint": 7}
                ],
            },
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self.write_registry(data)
                with self.assertRaises(accounts.AccountError):
                    accounts.load_registry()

    def test_set_active_named(self):
        accounts.add_account("work", "Work")
        accounts.set_active("work")
        self.assertEqual(accounts.get_active_id(), "work")
        self.assertIn(
            '"active": "work"',
            accounts.registry_path().read_text(encoding="utf-8"),
        )

    def test_set_active_missing_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.set_active("ghost")
        self.assertIsNone(accounts.load_registry())

    def test_set_active_default_without_registry_is_noop(self):
        accounts.set_active("default")
        self.assertIsNone(accounts.load_registry())

    def test_set_active_default_switches_back(self):
        accounts.add_account("work", "Work")
        accounts.set_active("work")
        accounts.set_active("default")
        self.assertEqual(accounts.get_active_id(), "default")

    def test_remove_account_cleans_registry_and_file_secret(self):
        accounts.add_account("work", "Work")
        accounts.store_secret("work", _SECRET, backend="file")
        accounts.remove_account("work")
        entries, active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default"])
        self.assertEqual(active, "default")
        self.assertFalse(accounts.secret_file_path("work").exists())

    def test_remove_active_resets_to_default(self):
        accounts.add_account("work", "Work")
        accounts.set_active("work")
        accounts.remove_account("work")
        self.assertEqual(accounts.get_active_id(), "default")

    def test_remove_default_refused(self):
        with self.assertRaises(accounts.AccountError):
            accounts.remove_account("default")

    def test_remove_missing_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.remove_account("ghost")

    def test_update_hint(self):
        accounts.add_account("work", "Work")
        updated = accounts.update_hint("work", "oc_sk_…abcd")
        self.assertEqual(updated.hint, "oc_sk_…abcd")
        entries, _active = accounts.list_accounts()
        self.assertEqual(entries[1].hint, "oc_sk_…abcd")

    def test_update_hint_missing_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.update_hint("ghost", "x")

    def test_update_hint_rejects_default(self):
        with self.assertRaises(accounts.AccountError):
            accounts.update_hint("default", "x")


class KeyringSecretTests(AccountsTestCase):
    def test_secret_tool_detection(self):
        self.assertFalse(accounts.secret_available())
        self.use_fake_tool()
        self.assertTrue(accounts.secret_available())

    def test_store_read_delete_round_trip(self):
        self.use_fake_tool()
        hint = accounts.store_secret("work", _SECRET)
        self.assertEqual(hint, creds.mask_token(_SECRET))
        self.assertEqual(accounts.read_secret("work"), _SECRET)
        self.assertTrue(accounts.has_secret("work"))
        accounts.delete_secret("work")
        self.assertFalse(accounts.has_secret("work"))
        with self.assertRaises(accounts.AccountError):
            accounts.read_secret("work")

    def test_explicit_keyring_backend(self):
        self.use_fake_tool()
        accounts.store_secret("work", _SECRET, backend="keyring")
        self.assertEqual(accounts.read_secret("work"), _SECRET)

    def test_argv_never_contains_the_secret(self):
        self.use_fake_tool()
        accounts.add_account("work", "Work")
        hint = accounts.store_secret("work", _SECRET)
        accounts.update_hint("work", hint)
        self.assertEqual(accounts.read_secret("work"), _SECRET)
        accounts.delete_secret("work")
        log = self.argv_log()
        self.assertIn(
            "store\x00--label\x00ocgo work\x00service\x00ocgo\x00account\x00work\n",
            log,
        )
        self.assertIn("lookup\x00service\x00ocgo\x00account\x00work\n", log)
        self.assertIn("clear\x00service\x00ocgo\x00account\x00work\n", log)
        self.assertNotIn(_SECRET, log)
        registry_text = accounts.registry_path().read_text(encoding="utf-8")
        self.assertNotIn(_SECRET, registry_text)
        self.assertEqual(json.loads(registry_text)["accounts"][0]["hint"], hint)

    def test_store_failure_does_not_leak_secret(self):
        self.use_fake_tool()
        with mock.patch.dict(os.environ, {"FAKE_SECRET_TOOL_FAIL": "store"}):
            with self.assertRaises(accounts.AccountError) as caught:
                accounts.store_secret("work", _SECRET)
        self.assertNotIn(_SECRET, str(caught.exception))

    def test_env_var_wins_over_keyring(self):
        self.use_fake_tool()
        accounts.store_secret("work", _SECRET)
        with mock.patch.dict(os.environ, {"OCGO_TOKEN_WORK": "env-secret-value"}):
            self.assertEqual(accounts.read_secret("work"), "env-secret-value")

    def test_empty_env_var_is_ignored(self):
        self.use_fake_tool()
        accounts.store_secret("work", _SECRET)
        with mock.patch.dict(os.environ, {"OCGO_TOKEN_WORK": "   "}):
            self.assertEqual(accounts.read_secret("work"), _SECRET)

    def test_has_secret_with_env(self):
        with mock.patch.dict(os.environ, {"OCGO_TOKEN_WORK": "env-secret"}):
            self.assertTrue(accounts.has_secret("work"))
        self.assertFalse(accounts.has_secret("work"))

    def test_delete_secret_ignores_absence(self):
        accounts.delete_secret("work")
        self.use_fake_tool()
        accounts.delete_secret("work")

    def test_read_secret_none_is_actionable(self):
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.read_secret("work")
        self.assertIn("ocgo account set-key work", str(caught.exception))


class FileSecretTests(AccountsTestCase):
    def test_file_backend_round_trip_and_permissions(self):
        hint = accounts.store_secret("work", _SECRET, backend="file")
        self.assertEqual(hint, creds.mask_token(_SECRET))
        path = accounts.secret_file_path("work")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(accounts.keys_dir().stat().st_mode), 0o700)
        self.assertEqual(accounts.read_secret("work"), _SECRET)
        self.assertTrue(accounts.has_secret("work"))
        accounts.delete_secret("work")
        self.assertFalse(path.exists())

    def test_file_store_leaves_no_temp_files(self):
        accounts.store_secret("work", _SECRET, backend="file")
        names = [entry.name for entry in accounts.keys_dir().iterdir()]
        self.assertEqual(names, ["work.key"])

    def test_file_backend_works_without_keyring(self):
        self.assertFalse(accounts.secret_available())
        accounts.store_secret("work", _SECRET, backend="file")
        self.assertEqual(accounts.read_secret("work"), _SECRET)

    def test_keyring_wins_over_file(self):
        self.use_fake_tool()
        accounts.store_secret("work", "file-secret-value", backend="file")
        accounts.store_secret("work", "keyring-secret-value", backend="keyring")
        self.assertEqual(accounts.read_secret("work"), "keyring-secret-value")

    def test_auto_without_keyring_raises(self):
        self.assertFalse(accounts.secret_available())
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.store_secret("work", _SECRET)
        message = str(caught.exception)
        self.assertIn("libsecret-tools", message)
        self.assertIn("file", message)
        self.assertNotIn(_SECRET, message)

    def test_keyring_backend_without_tool_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.store_secret("work", _SECRET, backend="keyring")

    def test_unknown_backend_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.store_secret("work", _SECRET, backend="dconf")

    def test_empty_secret_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.store_secret("work", "   ", backend="file")
        self.assertFalse(accounts.secret_file_path("work").exists())

    def test_auto_uses_keyring_when_available(self):
        self.use_fake_tool()
        accounts.store_secret("work", _SECRET)
        self.assertFalse(accounts.secret_file_path("work").exists())
        self.assertTrue(accounts.has_secret("work"))


if __name__ == "__main__":
    unittest.main()
