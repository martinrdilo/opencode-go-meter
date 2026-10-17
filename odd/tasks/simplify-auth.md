# Feature: simplify-auth — single-account auto-detection, simple API-key fallback, and removal of credits/multi-account machinery

**Status**: MERGED — PR #16 (`ad35596`) on 2026-10-17; branch `refactor/simplify-auth` kept on origin (repo precedent). CI green on push and pull_request.
**Repo**: `opencode-go-meter`
**Branch**: `refactor/simplify-auth` (from `main` @ `6098125`)
**Created**: 2026-10-17

## Objective

Simplify `opencode-go-meter` so that it works out of the box by auto-detecting the local OpenCode credential store (`opencode.db` / `auth.json`, optionally pointed at a custom OpenCode data directory), falls back to a single user-supplied API key when no usable local OpenCode session is present, and displays only the three OpenCode Go subscription usage windows (`5h`, `7d`, `30d`).

Remove the entire multi-account registry (`accounts.json`), the GUI "Sign in with OpenCode" terminal launcher, the database credential picker (`list_db_credentials`), the `secret-tool` keyring integration, the standalone Cinnamon GTK3 window (`cinnamon/accounts-window.js`), and the OAuth-only `credits` / `extra_usage` / `auto_recharge` billing fetches and UI rows.

## Problem

1. **Unnecessary account-management machinery**: `core/ocgo/creds.py` already auto-detects OpenCode's local credential store (`~/.local/share/opencode/opencode.db` and `auth.json`). Nearly all recurring Linux Mint / Cinnamon friction came from the layer built on top of it:
   - A multi-account registry (`~/.config/ocgo/accounts.json` v1–v3) with `opencode-db` pins and `api-key` entries (`core/ocgo/accounts.py`, 726 lines).
   - Launching `opencode auth login` from the desktop applet/extension where `opencode` is often absent from the graphical session `PATH`.
   - `secret-tool` / `libsecret` keyring prompts and fallbacks.
   - A 1,343-line standalone GTK3 window (`cinnamon/accounts-window.js`) duplicating `cinnamon/applet.js` helpers just to add/switch accounts.
2. **Asymmetric and unnecessary billing/credits surface**: `fetch_billing_status` and `fetch_auto_recharge` in `core/ocgo/api.py` only work with Console OAuth tokens (returning HTTP 403 for API keys), require two extra HTTP requests on every refresh, and add three extra UI rows (`Credits`, `Extra usage`, `Auto-recharge`) plus visibility settings in both frontends.
3. **Store API-key routing gap**: `core/ocgo/creds.py` already extracts either `access` (OAuth) or `key` (API key) from `opencode.db` / `auth.json`, but `cli.py` previously routed all `opencode-db` accounts to `fetch_status` (Console OAuth endpoint) instead of routing `"key"` credentials to `fetch_zen_status` (Zen API-key endpoint).

## Scope

In:
- `core/ocgo/`:
  - Remove `credits`, `extra_usage`, and `auto_recharge` from `api.py`, `format.py`, and `cli.py` while keeping cache `schema: 1` compatible with existing cached `status.json` files.
  - Tag `Credential` with `kind: str = "oauth" | "api"` so `ocgo refresh` calls `fetch_status` for `"oauth"` tokens and `fetch_zen_status` for `"api"` tokens (whether the API key came from `opencode.db`, `auth.json`, or the fallback API-key file).
  - Replace the multi-account registry (`core/ocgo/accounts.py`) and per-account caches with single-credential resolution in `core/ocgo/creds.py` and a single `$XDG_CACHE_HOME/ocgo/status.json` in `core/ocgo/cache.py`:
    1. `OCGO_TOKEN` environment variable.
    2. Local OpenCode store (`opencode.db`, then legacy `auth.json`) under the effective OpenCode data directory (`OCGO_DB` / `OCGO_DATA_DIR` env override, then configured `opencode_data_dir` in `$XDG_CONFIG_HOME/ocgo/config.json`, then default `$XDG_DATA_HOME/opencode` / `~/.local/share/opencode`).
    3. Fallback API key in `$XDG_CONFIG_HOME/ocgo/api.key` (`0600` permissions) when the local store has no usable (non-expired) credential.
  - Simplify `core/ocgo/cli.py` commands to:
    - `ocgo refresh`
    - `ocgo status [--json] [--no-color]`
    - `ocgo auth show [--json]`
    - `ocgo auth set-key [--stdin]` (validates via `fetch_zen_status` before writing `0600` `$XDG_CONFIG_HOME/ocgo/api.key`)
    - `ocgo auth clear-key`
    - `ocgo auth set-data-dir <path>` and `ocgo auth clear-data-dir` (persists/clears `opencode_data_dir` in `$XDG_CONFIG_HOME/ocgo/config.json`)
- `gnome/`:
  - Remove `CREDITS_ROWS`, `show-credits` GSettings key, `.ocgo-credit-value` style, and all multi-account submenu/switching/discovery code in `gnome/extension.js` and `gnome/prefs.js`.
  - Provide a clean Preferences page in `gnome/prefs.js` with display settings plus a Credentials group showing auto-detected store status, an optional custom OpenCode credentials directory row, and an optional fallback API key row (calling `ocgo auth set-key --stdin` / `ocgo auth clear-key` and `ocgo auth set-data-dir` / `ocgo auth clear-data-dir`).
- `cinnamon/`:
  - Delete `cinnamon/accounts-window.js` and update `cinnamon/scripts/check_applet.py`.
  - Remove `CREDITS_ROWS`, `show-credits`, login terminal launching, credential pickers, and multi-account dialogs/menus from `cinnamon/applet.js` and `cinnamon/settings-schema.json`.
  - Provide simple native settings in `cinnamon/settings-schema.json` + `cinnamon/applet.js` for the optional OpenCode credentials directory and fallback API key.
- `scripts/` & `docs/`:
  - Remove `libsecret-tools` / `secret-tool` and login-button `opencode` checks from `scripts/install-deps.sh`.
  - Align `AGENTS.md`, `README.md`, `docs/01-architecture.md` through `docs/05-technical-decisions.md` (recording D13 for the single-credential + API-key fallback + removal of credits architecture), and `skills/project-conventions/SKILL.md`.

Out:
- Changing the three usage windows (`rolling` 5h, `weekly` 7d, `monthly` 30d), percentage calculation, or traffic-light thresholds.
- Adding any third-party Python or JS dependencies.

## Constraints

- Core remains Python 3 standard library only (`core/tests/` uses `unittest` only).
- Secrets never appear in argv, logs, cache JSON, or frontend settings files:
  - The fallback API key is passed to `ocgo auth set-key --stdin` over stdin and stored only in `$XDG_CONFIG_HOME/ocgo/api.key` with `0600` permissions (never stored in GSettings or Cinnamon's `settings-schema.json`).
- Frontends stay thin: read `$XDG_CACHE_HOME/ocgo/status.json`, run `ocgo`, and render.
- Default test-first policy (TDD): for every core behavior task, run and observe RED in `unittest` before implementing GREEN, then refactor while keeping tests green.
- All three repository checks must pass at the end of every task:
  - `make test`
  - `make check-gnome`
  - `make check-cinnamon`

## Tasks

- [x] **T1 — core (billing/credits removal): remove `credits`, `extra_usage`, and `auto_recharge` from `api.py`, `format.py`, `cli.py`, and their unit tests.**
  - Route: delegated writer (writer trigger: 6 non-trivial files). Done 2026-10-17, commit `dc9015b` (914 authored lines vs the ~400 heuristic — deletion work unit, not sliced): RED `Ran 422 tests — FAILED (failures=3)` (new `assertNotIn` tests against the removed keys), GREEN `Ran 422 tests — OK`; parent spot check re-ran `make test` (`Ran 422 tests — OK`); `make check-gnome` + `make check-cinnamon` green; `grep -rn "credits\|extra_usage\|auto_recharge\|fetch_billing\|BILLING" core/ocgo/` empty.
  - Files (`Allowed edit surfaces`):
    - `core/ocgo/format.py`
    - `core/ocgo/api.py`
    - `core/ocgo/cli.py`
    - `core/tests/test_format.py`
    - `core/tests/test_api.py`
    - `core/tests/test_cli.py`
  - Details:
    - Remove `CREDITS_LOW_MICROCENTS` and `credits_state` from `core/ocgo/format.py`.
    - Remove `BILLING_STATUS_URL`, `BILLING_AUTO_RECHARGE_URL`, `BILLING_REJECTED`, `_fetch_console_json`, `fetch_billing_status`, `fetch_auto_recharge`, `credits_from_billing`, `_auto_recharge_block`, and `_dollars_or_none` from `core/ocgo/api.py`.
    - Remove `"extra_usage"` and `"credits"` keys from `to_cache_schema` and `to_cache_schema_zen` in `core/ocgo/api.py` (keep `schema: 1`).
    - Remove billing fetches in `_refresh_one`, credits printing in `cmd_status`, credits summary in `_summary`, and `_credits_row` in `core/ocgo/cli.py`.
    - Update `core/tests/test_format.py`, `core/tests/test_api.py`, and `core/tests/test_cli.py` first (RED: assert `"credits"` and `"extra_usage"` are absent from `to_cache_schema*` and `ocgo refresh`/`status` make only 1 HTTP call and print only the 3 usage windows), then implement GREEN.
  - Verification: `make test`, `make check-gnome`, `make check-cinnamon`.

- [x] **T2 — core (single-credential auto-detection + fallback API key + custom data dir): remove multi-account registry (`accounts.py`) and per-account cache; add `Credential.kind`, `api.key` fallback, and `config.json` data-dir support.**
  - Route: delegated writer (writer trigger: 8 non-trivial files). Done 2026-10-17, commit `6a8af1a` (1,191+/5,238-): RED `Ran 235 tests — FAILED (failures=37, errors=61)`, GREEN `Ran 235 tests — OK`; parent spot check re-ran `make test` (`Ran 235 tests — OK`) and live-smoked `ocgo refresh` against the real store (`kind: api` → zen → `rolling 44% · weekly 46% · monthly 27%`). `accounts.py` + `test_accounts.py` deleted; suite 422 → 235 tests.
  - Files (`Allowed edit surfaces`):
    - `core/ocgo/creds.py`
    - `core/ocgo/accounts.py` (delete)
    - `core/ocgo/cache.py`
    - `core/ocgo/cli.py`
    - `core/tests/test_creds.py`
    - `core/tests/test_accounts.py` (delete)
    - `core/tests/test_cache.py`
    - `core/tests/test_cli.py`
  - Details:
    - In `core/ocgo/creds.py`:
      - Add `kind: str = "oauth"` (`"oauth"` or `"api"`) to `Credential`. `_credential_fields` returns `(token, expires_ms, kind)` where `"access"` -> `"oauth"` and `"key"` -> `"api"`.
      - Support `$XDG_CONFIG_HOME/ocgo/config.json` (`opencode_data_dir`) and `OCGO_DATA_DIR` env var in `default_db_path()` and `default_auth_json_path()` (`OCGO_DB` still overrides `db_path` directly). Add `set_configured_data_dir(path: str | None)` and `get_configured_data_dir() -> str | None`.
      - Support single fallback API key file at `$XDG_CONFIG_HOME/ocgo/api.key` (`0600` permissions via atomic temp-file write): `store_api_key(token: str) -> str` (returns masked hint), `read_api_key() -> str | None`, `clear_api_key() -> bool`, `has_api_key() -> bool`.
      - Resolution order in `resolve_credential(*, now_ms: int | None = None) -> Credential`:
        1. `OCGO_TOKEN` env var (`source="OCGO_TOKEN environment"`, `kind="oauth"`).
        2. Local OpenCode store (`opencode.db`, then legacy `auth.json`).
        3. Fallback API key file (`$XDG_CONFIG_HOME/ocgo/api.key`, `source="Configured API key"`, `kind="api"`). If the store raised `CredentialError` (missing or expired) and a fallback API key exists, return the fallback API key; otherwise raise the store's `CredentialError`.
      - Remove `credential_id` pinning, `DbCredential`, `list_db_credentials`, and `_metadata_strings`.
      - Extend `store_status()` with `"data_dir"` (effective directory string), `"configured_data_dir"` (`str | None`), `"api_key_configured"` (`bool`), and `"api_key_hint"` (`str | None`) while preserving the existing six keys (`db_path`, `db_exists`, `auth_json_path`, `auth_json_exists`, `auth_json_login`, `has_login`).
    - Delete `core/ocgo/accounts.py` and `core/tests/test_accounts.py`.
    - Simplify `core/ocgo/cache.py`: `cache_path()` takes no `account_id` and always returns `$XDG_CACHE_HOME/ocgo/status.json`; remove `remove_account_cache` and per-account path tests.
    - Simplify `core/ocgo/cli.py`:
      - Remove `ocgo account ...` subcommands and `--account` / `--all` flags.
      - `ocgo refresh`: resolves single `Credential`, calls `api.fetch_zen_status` + `api.to_cache_schema_zen` when `cred.kind == "api"` and `api.fetch_status` + `api.to_cache_schema` when `cred.kind == "oauth"`, saves to `cache.cache_path()`.
      - `ocgo status [--json] [--no-color]`: reads single `cache.cache_path()`.
      - `ocgo auth show [--json]`: reports resolved credential (`source`, `kind`, `token_hint`, `expires_at`) and `store_status()` JSON/text.
      - `ocgo auth set-key [--stdin]`: reads API key from stdin (when `--stdin` or non-TTY) or `getpass`, validates via `api.fetch_zen_status(key)`, stores via `creds.store_api_key(key)`, and writes initial cached status to `cache.cache_path()`.
      - `ocgo auth clear-key`: removes stored API key via `creds.clear_api_key()`.
      - `ocgo auth set-data-dir <path>` and `ocgo auth clear-data-dir`: sets or clears `opencode_data_dir` in `config.json`.
  - Verification: `make test`, `make check-gnome`, `make check-cinnamon`.

- [x] **T3 — gnome: simplify `extension.js`, `prefs.js`, `gschema.xml`, and `stylesheet.css` to single-credential auto-detection + optional data-dir and API-key preferences.**
  - Route: delegated writer (writer trigger: 4 non-trivial files). Done 2026-10-17, commit `a398ece` (197+/1,104-): `show-credits` key + `.ocgo-credit-value` + multi-account submenu/discovery removed; new Credentials preferences group (status row via `ocgo auth show --json`, data-dir EntryRow with Apply/Reset, API-key PasswordEntryRow with Save/Clear over stdin, best-effort `ocgo refresh` after each success). `make check-gnome` + `make test` + `make check-cinnamon` green; banned-token grep empty. Ran in parallel with T4 (disjoint surfaces).
  - Files (`Allowed edit surfaces`):
    - `gnome/extension.js`
    - `gnome/prefs.js`
    - `gnome/schemas/org.gnome.shell.extensions.opencode-go-meter.gschema.xml`
    - `gnome/stylesheet.css`
  - Details:
    - `gnome/schemas/org.gnome.shell.extensions.opencode-go-meter.gschema.xml`: remove `show-credits` key.
    - `gnome/stylesheet.css`: remove `.ocgo-credit-value`.
    - `gnome/extension.js`: remove `CREDITS_ROWS`, `creditsOf`, `extraUsageOf`, `dollarsText`, `creditsAmountText`, `creditsSuffix`, `autoRechargeValue`, `creditValueStyle`, `_showCreditsSetting`, `_renderCredits`, `ACCOUNTS_DIR`, `ACCOUNTS_SCHEMA`, `parseAccountList`, `_loadAccounts`, `_startAccountLoad`, `_finishAccountLoad`, `_renderAccountMenu`, `_switchAccount`, `_activeAccountLabel`, and per-account cache monitoring. Monitor only `$XDG_CACHE_HOME/ocgo/status.json`.
    - `gnome/prefs.js`: remove `show-credits` toggle and all multi-account / credential-picker / activate-in-opencode groups (~620 lines). Replace with a clean **Credentials** group that runs `ocgo auth show --json` to display:
      - Auto-detected status (active source & store path).
      - OpenCode data directory entry (`Adw.EntryRow` + Apply/Reset buttons invoking `ocgo auth set-data-dir <path>` / `ocgo auth clear-data-dir`).
      - Fallback API key entry (`Adw.PasswordEntryRow` + Save/Clear buttons invoking `ocgo auth set-key --stdin` / `ocgo auth clear-key`).
  - Verification: `make check-gnome`, `make test`, `make check-cinnamon`.

- [x] **T4 — cinnamon: delete `accounts-window.js`, simplify `applet.js`, `settings-schema.json`, and `check_applet.py`.**
  - Route: delegated writer (writer trigger: 4 non-trivial files). Done 2026-10-17, commit `6b7d90d` (214+/3,186-): `accounts-window.js` deleted (1,343 lines); `applet.js` 2,335 → 727 lines (credits, accounts menu, login terminal, credential picker gone; single `status.json` cache + unconditional startup refresh); new `credentials` settings section (data-dir entry + apply/clear buttons, set/clear API key with a masked single-field modal piped to stdin); `check_applet.py` dropped the window/module checks. `make check-cinnamon` + `make test` + `make check-gnome` green; banned-token grep empty. Ran in parallel with T3 (disjoint surfaces).
  - Files (`Allowed edit surfaces`):
    - `cinnamon/accounts-window.js` (delete)
    - `cinnamon/applet.js`
    - `cinnamon/settings-schema.json`
    - `cinnamon/scripts/check_applet.py`
  - Details:
    - Delete `cinnamon/accounts-window.js` and remove `WINDOW_JS` checks (and unused UI module allowances if no longer imported) from `cinnamon/scripts/check_applet.py`.
    - `cinnamon/settings-schema.json`: remove `show-credits` and the multi-account controls (`active-account`, `accounts-apply-button`, `accounts-remove-button`, `accounts-activate-button`). Add a **Credentials** section with:
      - `opencode-data-dir` (`filechooser` or `entry`, default `""`, description explaining default `~/.local/share/opencode` auto-detection).
      - `set-api-key-button` (`button` opening a minimal single-field modal prompt in `applet.js` that pipes the key to `ocgo auth set-key --stdin`, or clears it with `ocgo auth clear-key`).
      - `clear-api-key-button` (`button` invoking `ocgo auth clear-key`).
    - `cinnamon/applet.js`: remove `CREDITS_ROWS`, `_renderCredits`, `creditValueMarkup`, `dollarsText`, `creditsAmountText`, `creditsSuffix`, `autoRechargeValue`, `parseAccountList`, `parseDiscoverJson`, login terminal spawner, credential picker, and multi-account menu/state (~1,400 lines). Monitor only `$XDG_CACHE_HOME/ocgo/status.json`. Wire `opencode-data-dir` change handler to `ocgo auth set-data-dir` / `ocgo auth clear-data-dir` + `_triggerRefresh()`, and wire the API-key buttons to `ocgo auth set-key --stdin` / `ocgo auth clear-key` + `_triggerRefresh()`.
  - Verification: `make check-cinnamon`, `make check-gnome`, `make test`.

- [x] **T5 — scripts & docs: align `install-deps.sh`, `AGENTS.md`, `README.md`, `docs/01`–`05`, and `skills/project-conventions/SKILL.md`.**
  - Route: delegated writer (writer trigger: 9 files). Done 2026-10-17, commit `df21961` (219+/277-): D13 recorded (supersedes D3/D4-per-account/D7); architecture, CLI, frontends, testing, README, AGENTS and the skill rewritten to the single-credential model; `install-deps.sh` trimmed (no `secret-tool`/login `opencode` checks); README screenshot references removed (stale UI — see SOP-1). `make test` + both checks + `make pack` green.
  - Files (`Allowed edit surfaces`):
    - `scripts/install-deps.sh`
    - `AGENTS.md`
    - `README.md`
    - `docs/01-architecture.md`
    - `docs/02-cli-reference.md`
    - `docs/03-frontends.md`
    - `docs/04-testing.md`
    - `docs/05-technical-decisions.md`
    - `skills/project-conventions/SKILL.md`
  - Details:
    - `scripts/install-deps.sh`: remove `secret-tool` (`libsecret-tools`) and login-button `opencode` CLI dependency checks.
    - Update `AGENTS.md`, `README.md`, `docs/01-architecture.md`, `docs/02-cli-reference.md`, `docs/03-frontends.md`, `docs/04-testing.md`, and `skills/project-conventions/SKILL.md` to reflect single-credential auto-detection, optional custom OpenCode data directory, optional fallback API key (`0600` file), and the 3 usage windows without credits or multi-account registries.
    - Record decision **D13** in `docs/05-technical-decisions.md` documenting why multi-account management, GUI login spawning, `libsecret`, and billing/credits were removed in favor of store auto-detection + single API-key fallback (superseding D3, D4's credits/per-account cache parts, and D7).
  - Verification: `make test`, `make check-gnome`, `make check-cinnamon`, `make pack`.

## Delivery forecast & strategy

- **Forecast authored changed lines (`additions + deletions`)**: ~10,100 lines total (~620 additions, ~9,480 deletions across deleted subsystems `core/ocgo/accounts.py`, `core/tests/test_accounts.py`, `cinnamon/accounts-window.js`, and removed multi-account/credits code):
  - `T1` (core credits removal): ~620 lines (~20+, ~600-)
  - `T2` (core single-credential + API-key fallback): ~5,100 lines (~250+, ~4,850-)
  - `T3` (GNOME simplification): ~1,050 lines (~120+, ~930-)
  - `T4` (Cinnamon simplification): ~2,950 lines (~100+, ~2,850-)
  - `T5` (scripts & docs alignment): ~380 lines (~130+, ~250-)
- **Delivery strategy**: `ask-on-risk` (pending user confirmation between `single-pr` with `size:exception` on `refactor/simplify-auth` vs `stacked-to-main` across slices `T1`–`T5` where `T1`–`T4` carry `size:exception` because deletions exceed 400 lines).

## Acceptance criteria

- Zero-config auto-detection works whenever `~/.local/share/opencode/opencode.db` or `auth.json` (or the configured `opencode_data_dir`) has a valid OpenCode login (`opencode-go`, `opencode`, or `opencode*`), routing `"oauth"` tokens to Console status and `"api"` tokens to Zen usage.
- When no local OpenCode login is present (or it is expired), configuring a fallback API key via `ocgo auth set-key --stdin` (or the GNOME/Cinnamon preferences UI) stores it in `0600` `$XDG_CONFIG_HOME/ocgo/api.key` and refreshes usage from the Zen endpoint.
- No `credits`, `extra_usage`, or `auto_recharge` requests, cache fields, CLI rows, or GUI rows remain.
- No multi-account registry (`accounts.json`), `secret-tool` calls, GUI terminal login launcher, or `cinnamon/accounts-window.js` remain.
- `make test`, `make check-gnome`, `make check-cinnamon`, and `make pack` all pass with zero warnings/errors.

## Checks

- `make test`
- `make check-gnome`
- `make check-cinnamon`
- `make pack`

## Progress

- 2026-10-17 — Feature planned on `refactor/simplify-auth` (from `main` @ `6098125`). Ready for implementation of `T1`–`T5`.
- 2026-10-17 — `T1` done (commit `dc9015b`): credits/billing surface removed from the core; suite 478 → 422 tests, all green.
- 2026-10-17 — `T2` done (commit `6a8af1a`): multi-account registry deleted; single-credential detection + `Credential.kind` routing + `api.key` fallback + configurable data dir; suite 422 → 235 tests, all green; live refresh OK (`kind: api` → zen).
- 2026-10-17 — `T3` + `T4` done in parallel (commits `a398ece`, `6b7d90d`): GNOME and Cinnamon reduced to the single-cache/3-windows surface with Credentials preferences; `accounts-window.js` deleted; all three checks green.
- 2026-10-17 — `T5` done (commit `df21961`): references aligned to the single-credential model; D13 recorded; `make pack` green. All tasks complete.
- 2026-10-17 — DELIVERED: pushed `refactor/simplify-auth`, opened PR #16 (repo template + `enhancement` label), CI green on push and pull_request, merged with a merge commit (`ad35596`) on user instruction; branch kept on origin.

## Follow-ups (out of T1–T5 scope)

- **SOP-1**: regenerate `docs/screenshots/gnome-popup.png` and `gnome-preferences.png` for the new UI (the stale image references were removed from `README.md`).
- Delivery: MERGED — PR #16 (`ad35596`) landed on `main` on 2026-10-17.

## Next step

Feature closed. Optional follow-ups: SOP-1 (README screenshots) and a field-machine re-check of the new auto-detection flow on Mint/Cinnamon.
