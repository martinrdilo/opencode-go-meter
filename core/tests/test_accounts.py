"""Tests for ocgo.accounts (temp XDG dirs and a fake secret-tool only)."""

import json
import os
import stat
import sys
import tempfile
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

    def test_default_is_a_valid_id(self):
        self.assertEqual(accounts.validate_account_id("default"), "default")

    def test_add_accepts_default_id(self):
        accounts.remove_account("default")  # writes the empty v2 registry
        account = accounts.add_account("default", "My login")
        self.assertEqual(account.id, "default")
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["default"])
        self.assertEqual(active, "default")

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
            "bad-version": {**base, "version": 4},
            "float-version": {**base, "version": 1.0},
            "bool-version": {**base, "version": True},
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
            "v2-active-wrong-type": {"version": 2, "active": 5, "accounts": []},
            "v2-unknown-kind": {
                "version": 2,
                "active": None,
                "accounts": [{"id": "work", "label": "W", "kind": "bogus"}],
            },
            "v2-db-with-hint": {
                "version": 2,
                "active": None,
                "accounts": [
                    {"id": "login", "label": "L", "kind": "opencode-db", "hint": "x"}
                ],
            },
            "v1-credential-id": {
                **base,
                "accounts": [
                    {
                        "id": "work",
                        "label": "W",
                        "kind": "api-key",
                        "hint": None,
                        "credential_id": "cred-1",
                    }
                ],
            },
            "v2-credential-id": {
                "version": 2,
                "active": None,
                "accounts": [
                    {
                        "id": "login",
                        "label": "L",
                        "kind": "opencode-db",
                        "hint": None,
                        "credential_id": "cred-1",
                    }
                ],
            },
            "v3-credential-id-on-api-key": {
                "version": 3,
                "active": None,
                "accounts": [
                    {
                        "id": "work",
                        "label": "W",
                        "kind": "api-key",
                        "hint": None,
                        "credential_id": "cred-1",
                    }
                ],
            },
            "v3-credential-id-empty": {
                "version": 3,
                "active": None,
                "accounts": [
                    {
                        "id": "login",
                        "label": "L",
                        "kind": "opencode-db",
                        "hint": None,
                        "credential_id": "",
                    }
                ],
            },
            "v3-credential-id-null": {
                "version": 3,
                "active": None,
                "accounts": [
                    {
                        "id": "login",
                        "label": "L",
                        "kind": "opencode-db",
                        "hint": None,
                        "credential_id": None,
                    }
                ],
            },
            "v3-credential-id-int": {
                "version": 3,
                "active": None,
                "accounts": [
                    {
                        "id": "login",
                        "label": "L",
                        "kind": "opencode-db",
                        "hint": None,
                        "credential_id": 7,
                    }
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

    def test_set_active_default_without_registry_materializes_registry(self):
        accounts.set_active("default")
        registry = accounts.load_registry()
        self.assertEqual(registry["version"], 3)
        self.assertEqual(registry["active"], "default")
        self.assertEqual(
            [entry["id"] for entry in registry["accounts"]], ["default"]
        )

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

    def test_remove_seeded_default_writes_empty_registry(self):
        accounts.remove_account("default")
        registry = accounts.load_registry()
        self.assertEqual(registry["version"], 3)
        self.assertIsNone(registry["active"])
        self.assertEqual(registry["accounts"], [])
        entries, active = accounts.list_accounts()
        self.assertEqual(entries, [])
        self.assertIsNone(active)

    def test_remove_missing_raises(self):
        with self.assertRaises(accounts.AccountError):
            accounts.remove_account("ghost")

    def test_remove_aborts_when_secret_delete_fails(self):
        accounts.add_account("work", "Work")
        accounts.keys_dir().write_text("obstructed", encoding="utf-8")
        before = accounts.registry_path().read_text(encoding="utf-8")
        with self.assertRaises(accounts.AccountError):
            accounts.remove_account("work")
        self.assertEqual(accounts.registry_path().read_text(encoding="utf-8"), before)
        entries, _active = accounts.list_accounts()
        self.assertEqual([account.id for account in entries], ["default", "work"])

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


class RegistryV2Tests(AccountsTestCase):
    def test_v1_registry_prepends_seeded_default(self):
        self.write_registry(
            {
                "version": 1,
                "active": "work",
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None}
                ],
            }
        )
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["default", "work"])
        self.assertEqual(entries[0].kind, "opencode-db")
        self.assertEqual(active, "work")

    def test_v1_mutation_writes_v3_with_seeded_default(self):
        self.write_registry(
            {
                "version": 1,
                "active": "work",
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None}
                ],
            }
        )
        accounts.add_account("personal", "Personal")
        registry = accounts.load_registry()
        self.assertEqual(registry["version"], 3)
        self.assertEqual(registry["active"], "work")
        self.assertEqual(
            [entry["id"] for entry in registry["accounts"]],
            ["default", "work", "personal"],
        )

    def test_v2_empty_list_and_null_active(self):
        self.write_registry({"version": 2, "active": None, "accounts": []})
        entries, active = accounts.list_accounts()
        self.assertEqual(entries, [])
        self.assertIsNone(active)
        self.assertIsNone(accounts.get_active_id())

    def test_v2_active_falls_back_to_first_account(self):
        self.write_registry(
            {
                "version": 2,
                "active": None,
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None},
                    {"id": "personal", "label": "P", "kind": "api-key", "hint": None},
                ],
            }
        )
        entries, active = accounts.list_accounts()
        self.assertEqual(len(entries), 2)
        self.assertEqual(active, "work")

    def test_v2_stored_default_id_is_not_duplicated(self):
        self.write_registry(
            {
                "version": 2,
                "active": "default",
                "accounts": [
                    {
                        "id": "default",
                        "label": "My login",
                        "kind": "opencode-db",
                        "hint": None,
                    }
                ],
            }
        )
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["default"])
        self.assertEqual(entries[0].label, "My login")
        self.assertEqual(active, "default")

    def test_add_after_empty_becomes_active(self):
        self.write_registry({"version": 2, "active": None, "accounts": []})
        accounts.add_account("work", "Work")
        registry = accounts.load_registry()
        self.assertEqual(registry["active"], "work")
        self.assertEqual([entry["id"] for entry in registry["accounts"]], ["work"])

    def test_add_materializes_effective_active(self):
        self.write_registry(
            {
                "version": 2,
                "active": None,
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None}
                ],
            }
        )
        accounts.add_account("personal", "Personal")
        registry = accounts.load_registry()
        self.assertEqual(registry["active"], "work")

    def test_remove_last_account_sets_active_null(self):
        self.write_registry(
            {
                "version": 2,
                "active": "work",
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None}
                ],
            }
        )
        accounts.remove_account("work")
        registry = accounts.load_registry()
        self.assertIsNone(registry["active"])
        self.assertEqual(registry["accounts"], [])

    def test_remove_active_falls_back_to_first_remaining(self):
        self.write_registry(
            {
                "version": 2,
                "active": "personal",
                "accounts": [
                    {
                        "id": "default",
                        "label": "D",
                        "kind": "opencode-db",
                        "hint": None,
                    },
                    {"id": "work", "label": "W", "kind": "api-key", "hint": None},
                    {"id": "personal", "label": "P", "kind": "api-key", "hint": None},
                ],
            }
        )
        accounts.remove_account("personal")
        registry = accounts.load_registry()
        self.assertEqual(registry["active"], "default")
        self.assertEqual(
            [entry["id"] for entry in registry["accounts"]], ["default", "work"]
        )

    def test_add_account_is_always_api_key(self):
        account = accounts.add_account("work", "Work")
        self.assertEqual(account.kind, "api-key")
        registry = accounts.load_registry()
        stored = next(entry for entry in registry["accounts"] if entry["id"] == "work")
        self.assertEqual(stored["kind"], "api-key")

    def test_remove_db_kind_does_not_touch_secrets(self):
        self.use_fake_tool()
        self.write_registry(
            {
                "version": 2,
                "active": "login",
                "accounts": [
                    {
                        "id": "login",
                        "label": "Login",
                        "kind": "opencode-db",
                        "hint": None,
                    }
                ],
            }
        )
        accounts.remove_account("login")
        registry = accounts.load_registry()
        self.assertEqual(registry["accounts"], [])
        self.assertIsNone(registry["active"])
        self.assertNotIn("clear", self.argv_log())

    def test_update_hint_rejects_db_kind(self):
        self.write_registry(
            {
                "version": 2,
                "active": "login",
                "accounts": [
                    {
                        "id": "login",
                        "label": "Login",
                        "kind": "opencode-db",
                        "hint": None,
                    }
                ],
            }
        )
        with self.assertRaises(accounts.AccountError):
            accounts.update_hint("login", "oc_sk_…x")


class AddAccountKindTests(AccountsTestCase):
    """The restored ``kind`` parameter and the one-``opencode-db`` invariant."""

    def test_add_db_kind_on_empty_v2_registry(self):
        self.write_registry({"version": 2, "active": None, "accounts": []})
        account = accounts.add_account(
            "login", "Login", kind=accounts.KIND_OPENCODE_DB
        )
        self.assertEqual(
            account, accounts.Account("login", "Login", "opencode-db", None)
        )
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["login"])
        self.assertEqual(active, "login")
        registry = accounts.load_registry()
        self.assertEqual(registry["accounts"][0]["kind"], "opencode-db")
        self.assertIsNone(registry["accounts"][0]["hint"])

    def test_add_db_kind_keeps_the_existing_active(self):
        self.write_registry(
            {
                "version": 2,
                "active": "work",
                "accounts": [
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None}
                ],
            }
        )
        accounts.add_account("login", "Login", kind=accounts.KIND_OPENCODE_DB)
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["work", "login"])
        self.assertEqual(active, "work")

    def test_add_db_kind_refused_when_one_exists(self):
        self.write_registry(
            {
                "version": 2,
                "active": "default",
                "accounts": [
                    {
                        "id": "default",
                        "label": "D",
                        "kind": "opencode-db",
                        "hint": None,
                    }
                ],
            }
        )
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account("login", "Login", kind=accounts.KIND_OPENCODE_DB)
        self.assertEqual(
            str(caught.exception),
            "an OpenCode login account already exists: 'default'",
        )
        registry = accounts.load_registry()
        self.assertEqual([entry["id"] for entry in registry["accounts"]], ["default"])

    def test_add_db_kind_refused_without_registry(self):
        # An absent registry materializes the seeded default opencode-db entry.
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account("login", "Login", kind=accounts.KIND_OPENCODE_DB)
        self.assertEqual(
            str(caught.exception),
            "an OpenCode login account already exists: 'default'",
        )
        self.assertIsNone(accounts.load_registry())

    def test_add_db_kind_after_removing_default(self):
        accounts.remove_account("default")  # writes the empty v2 registry
        account = accounts.add_account(
            "login", "Login", kind=accounts.KIND_OPENCODE_DB
        )
        self.assertEqual(account.kind, "opencode-db")
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["login"])
        self.assertEqual(active, "login")

    def test_add_db_kind_rejects_hint(self):
        self.write_registry({"version": 2, "active": None, "accounts": []})
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account(
                "login", "Login", kind=accounts.KIND_OPENCODE_DB, hint="oc_sk_…abcd"
            )
        self.assertIn("cannot have a hint", str(caught.exception))
        self.assertEqual(
            accounts.load_registry(), {"version": 2, "active": None, "accounts": []}
        )

    def test_add_rejects_unknown_kind(self):
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account("login", "Login", kind="bogus")
        self.assertIn("unsupported account kind", str(caught.exception))
        self.assertIsNone(accounts.load_registry())

    def test_explicit_api_key_kind_still_accepted(self):
        account = accounts.add_account(
            "work", "Work", kind=accounts.KIND_API_KEY, hint="oc_sk_…abcd"
        )
        self.assertEqual(account.kind, "api-key")
        self.assertEqual(account.hint, "oc_sk_…abcd")


class RegistryV3Tests(AccountsTestCase):
    """Registry v3: the auto login stays singular, pins bind database rows."""

    def test_v2_registry_loads_the_login_as_auto(self):
        self.write_registry(
            {
                "version": 2,
                "active": "login",
                "accounts": [
                    {
                        "id": "login",
                        "label": "Login",
                        "kind": "opencode-db",
                        "hint": None,
                    },
                    {"id": "work", "label": "Work", "kind": "api-key", "hint": None},
                ],
            }
        )
        entries, active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["login", "work"])
        self.assertIsNone(entries[0].credential_id)
        self.assertIsNone(entries[1].credential_id)
        self.assertEqual(active, "login")

    def test_v2_read_does_not_rewrite_the_file(self):
        self.write_registry({"version": 2, "active": None, "accounts": []})
        accounts.list_accounts()
        self.assertEqual(accounts.load_registry()["version"], 2)

    def test_v2_mutation_writes_v3(self):
        self.write_registry(
            {
                "version": 2,
                "active": "login",
                "accounts": [
                    {
                        "id": "login",
                        "label": "Login",
                        "kind": "opencode-db",
                        "hint": None,
                    }
                ],
            }
        )
        accounts.add_account("work", "Work")
        registry = accounts.load_registry()
        self.assertEqual(registry["version"], 3)
        self.assertEqual(registry["active"], "login")
        self.assertEqual(
            [entry["id"] for entry in registry["accounts"]], ["login", "work"]
        )

    def test_absent_registry_mutation_writes_v3(self):
        accounts.add_account("work", "Work")
        self.assertEqual(accounts.load_registry()["version"], 3)

    def test_seeded_default_is_auto(self):
        entries, _active = accounts.list_accounts()
        self.assertEqual(entries[0].id, "default")
        self.assertIsNone(entries[0].credential_id)

    def test_v3_pinned_entry_round_trip(self):
        self.write_registry(
            {
                "version": 3,
                "active": "login",
                "accounts": [
                    {
                        "id": "login",
                        "label": "Login",
                        "kind": "opencode-db",
                        "hint": None,
                        "credential_id": "cred-1",
                    }
                ],
            }
        )
        entries, active = accounts.list_accounts()
        self.assertEqual(entries[0].credential_id, "cred-1")
        self.assertEqual(active, "login")

    def test_add_pinned_login_round_trip(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        account = accounts.add_account(
            "personal",
            "Personal",
            kind=accounts.KIND_OPENCODE_DB,
            credential_id="cred-2",
        )
        self.assertEqual(account.credential_id, "cred-2")
        entries, active = accounts.list_accounts()
        self.assertEqual(entries[0].credential_id, "cred-2")
        self.assertEqual(active, "personal")
        registry = accounts.load_registry()
        self.assertEqual(registry["accounts"][0]["credential_id"], "cred-2")

    def test_add_pinned_while_the_auto_login_exists(self):
        account = accounts.add_account(
            "personal",
            "Personal",
            kind=accounts.KIND_OPENCODE_DB,
            credential_id="cred-2",
        )
        self.assertEqual(account.credential_id, "cred-2")
        entries, _active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["default", "personal"])
        self.assertIsNone(entries[0].credential_id)
        self.assertEqual(entries[1].credential_id, "cred-2")
        stored = accounts.load_registry()["accounts"]
        self.assertNotIn("credential_id", stored[0])

    def test_add_auto_while_a_pinned_login_exists(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        accounts.add_account(
            "pin", "Pin", kind=accounts.KIND_OPENCODE_DB, credential_id="cred-1"
        )
        account = accounts.add_account("auto", "Auto", kind=accounts.KIND_OPENCODE_DB)
        self.assertIsNone(account.credential_id)
        entries, _active = accounts.list_accounts()
        self.assertEqual([entry.id for entry in entries], ["pin", "auto"])

    def test_add_second_auto_login_refused(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        accounts.add_account("first", "First", kind=accounts.KIND_OPENCODE_DB)
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account("second", "Second", kind=accounts.KIND_OPENCODE_DB)
        self.assertEqual(
            str(caught.exception),
            "an OpenCode login account already exists: 'first'",
        )
        self.assertEqual(
            [entry["id"] for entry in accounts.load_registry()["accounts"]], ["first"]
        )

    def test_add_duplicate_pin_refused(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        accounts.add_account(
            "first", "First", kind=accounts.KIND_OPENCODE_DB, credential_id="cred-1"
        )
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account(
                "second",
                "Second",
                kind=accounts.KIND_OPENCODE_DB,
                credential_id="cred-1",
            )
        message = str(caught.exception)
        self.assertIn("already pinned", message)
        self.assertIn("cred-1", message)
        self.assertIn("'first'", message)
        self.assertEqual(
            [entry["id"] for entry in accounts.load_registry()["accounts"]], ["first"]
        )

    def test_add_several_pins(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        accounts.add_account(
            "one", "One", kind=accounts.KIND_OPENCODE_DB, credential_id="cred-1"
        )
        accounts.add_account(
            "two", "Two", kind=accounts.KIND_OPENCODE_DB, credential_id="cred-2"
        )
        entries, active = accounts.list_accounts()
        self.assertEqual(
            [entry.credential_id for entry in entries], ["cred-1", "cred-2"]
        )
        self.assertEqual(active, "one")

    def test_auto_entry_stores_no_credential_id_key(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        accounts.add_account("auto", "Auto", kind=accounts.KIND_OPENCODE_DB)
        self.assertNotIn("credential_id", accounts.load_registry()["accounts"][0])

    def test_add_pin_rejected_for_api_key(self):
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.add_account("work", "Work", credential_id="cred-1")
        self.assertIn("api-key", str(caught.exception))
        self.assertIsNone(accounts.load_registry())

    def test_add_pin_must_be_a_non_empty_string(self):
        for credential_id in ("", "   ", 7, ["cred-1"]):
            with self.subTest(credential_id=credential_id):
                with self.assertRaises(accounts.AccountError):
                    accounts.add_account(
                        "pin",
                        "Pin",
                        kind=accounts.KIND_OPENCODE_DB,
                        credential_id=credential_id,
                    )
        self.assertIsNone(accounts.load_registry())

    def test_remove_pinned_login(self):
        self.write_registry({"version": 3, "active": None, "accounts": []})
        accounts.add_account(
            "pin", "Pin", kind=accounts.KIND_OPENCODE_DB, credential_id="cred-1"
        )
        accounts.remove_account("pin")
        registry = accounts.load_registry()
        self.assertEqual(registry["version"], 3)
        self.assertEqual(registry["accounts"], [])
        self.assertIsNone(registry["active"])


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
        stored = json.loads(registry_text)["accounts"]
        self.assertEqual(stored[0]["id"], "default")
        self.assertEqual(stored[1]["hint"], hint)

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

    @unittest.skipIf(os.geteuid() == 0, "file permissions are not enforced for root")
    def test_unreadable_secret_file_raises_clear_error(self):
        accounts.store_secret("work", _SECRET, backend="file")
        path = accounts.secret_file_path("work")
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o600)
        with self.assertRaises(accounts.AccountError) as caught:
            accounts.read_secret("work")
        message = str(caught.exception)
        self.assertIn("work", message)
        self.assertIn("cannot read", message)
        self.assertNotIn(_SECRET, message)
        with self.assertRaises(accounts.AccountError):
            accounts.has_secret("work")

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


class SecretMoveTests(AccountsTestCase):
    def test_file_store_clears_the_keyring_shadow(self):
        self.use_fake_tool()
        accounts.store_secret("work", "keyring-secret-value")
        accounts.store_secret("work", "file-secret-value", backend="file")
        self.assertEqual(accounts.read_secret("work"), "file-secret-value")
        self.assertFalse((self.secrets / "items" / "work").exists())
        self.assertTrue(accounts.secret_file_path("work").is_file())

    def test_file_store_aborts_when_keyring_clear_verifiably_fails(self):
        self.use_fake_tool()
        accounts.store_secret("work", "old-keyring-value")
        with mock.patch.dict(os.environ, {"FAKE_SECRET_TOOL_FAIL": "clear"}):
            with self.assertRaises(accounts.AccountError) as caught:
                accounts.store_secret("work", "new-file-value", backend="file")
        message = str(caught.exception)
        self.assertIn("work", message)
        self.assertIn("keyring", message)
        self.assertNotIn("new-file-value", message)
        self.assertNotIn("old-keyring-value", message)
        self.assertFalse(accounts.secret_file_path("work").exists())
        self.assertTrue((self.secrets / "items" / "work").exists())
        self.assertEqual(accounts.read_secret("work"), "old-keyring-value")

    def test_keyring_store_removes_the_file_shadow(self):
        self.use_fake_tool()
        accounts.store_secret("work", "file-secret-value", backend="file")
        accounts.store_secret("work", "keyring-secret-value", backend="keyring")
        self.assertEqual(accounts.read_secret("work"), "keyring-secret-value")
        self.assertFalse(accounts.secret_file_path("work").exists())

    def test_failed_keyring_write_leaves_no_shadow(self):
        self.use_fake_tool()
        accounts.store_secret("work", "file-secret-value", backend="file")
        with mock.patch.dict(os.environ, {"FAKE_SECRET_TOOL_FAIL": "store"}):
            with self.assertRaises(accounts.AccountError):
                accounts.store_secret("work", "new-secret-value", backend="keyring")
        self.assertFalse(accounts.secret_file_path("work").exists())
        self.assertFalse(accounts.has_secret("work"))


class AtomicWriteTests(AccountsTestCase):
    def test_fchmod_failure_closes_fd_and_cleans_up(self):
        target = self.tmp / "output.json"
        probe_fd, probe_path = tempfile.mkstemp(dir=self.tmp, prefix=".probe-")
        with mock.patch("ocgo.accounts.os.fchmod", side_effect=OSError("denied")):
            with mock.patch(
                "ocgo.accounts.tempfile.mkstemp",
                return_value=(probe_fd, probe_path),
            ):
                with self.assertRaises(OSError):
                    accounts._atomic_write_text(target, "{}\n")
        try:
            os.fstat(probe_fd)
        except OSError:
            pass
        else:
            os.close(probe_fd)
            self.fail("temporary file descriptor was leaked")
        self.assertFalse(Path(probe_path).exists())
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
