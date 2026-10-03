# Feature: multi-account — add, switch, and replace OpenCode Go accounts (one panel)

**Status**: Complete and user-verified (2026-10-03) — T1–T10 done; live test OK in the user's session (v7 shows the active api-key account).
**Repo**: `/home/martin/workspace/opencode-go-meter`
**Branch**: `feat/multi-account` (branched from `feat/gnome-indicator`)
**Created**: 2026-10-02
**Related**: `odd/tasks/opencode-go-meter.md` (base feature, complete)

## Objective

Register additional OpenCode Go accounts, switch the active account, and replace (rotate) an account's API key — without duplicating the top-bar panel. The indicator always shows exactly one account.

## Problem / Why

- Credential resolution today is single-account: `OCGO_TOKEN` env or the local OpenCode DB (one OAuth login).
- The user holds several `oc_sk_…` Go API keys (some on accounts without an active subscription) and wants to add/switch/replace accounts.

## Verified API facts (live + source, 2026-10-02)

- OAuth (default) → `GET https://opencode.ai/console/api/go/status`; rejects `oc_sk_…` keys (403).
- API-key → `GET https://opencode.ai/zen/go/v1/usage` (`Authorization: Bearer oc_sk_…`):
  - `401` AuthError "Unauthorized" — unknown key;
  - `403` EntitlementError "OpenCode Go subscription required." — valid key, no subscription;
  - `200` `{"usage":{"rolling":{"status":"ok","percent":12,"resetsAt":…},"weekly":{…},"monthly":{…}}}` — `percent` is consumed; `monthly.resetsAt` equals the OAuth `access.endsAt` (renewal).
- Route source: `anomalyco/opencode` `packages/console/app/src/routes/zen/go/v1/usage.ts` (matches live responses).
- Any non-deleted workspace key of the subscribed user works (console → workspace → API Keys).

## Scope

In:

- Core: accounts registry, secrets via `secret-tool`, per-account cache, zen adapter, CLI `account add|list|use|remove|set-key`, `refresh/status --account|--all`, `auth show --account`.
- GNOME: popup switch submenu; prefs active-account combo + add/replace-key form; account-aware cache path/monitor; account label in the header.
- Tests, README.

Out (not now):

- Cinnamon frontend, notifications, provisioning accounts on opencode.ai, keyring for the OAuth token itself, timer-refreshing every account in the extension (active only; `--all` is CLI).

## Constraints / Decisions

- Python stdlib only at runtime; keyring via the `secret-tool` CLI (present on this machine; GNOME/libsecret, also on Cinnamon). `python3-gi` is NOT available here → no `gi.Secret`. Fallbacks: `OCGO_TOKEN_<ID>` env, opt-in 0600 file store (`--store file`).
- Secrets never in dconf/GSettings, argv, logs, or the usage cache. `auth show` stays masked.
- The registry is the single source of truth for the account list and the active account (no dconf key for it). Since 2026-10-03 (registry v2) it is fully user-owned: any account is removable, the list may be empty, and `active` may be null.
- Cache: `default` → legacy `~/.cache/ocgo/status.json` (zero migration); named accounts → `~/.cache/ocgo/accounts/<id>/status.json`.
- zen cache mapping: `windows.<rolling|weekly|monthly>` ← `percent` + `resetsAt`; `used_usd`/`limit_usd` = `null`; `renewal_ends_at` ← `monthly.resetsAt`; schema stays v1 (nullable USD documented).
- Add/set-key tri-state: `401` → rejected; `403 EntitlementError` → stored with "no subscription" state; `200` → active.
- TDD: OFF (no project/session config; repo convention). Runner: `make test`.
- RDD: off (global) → ordinary repository policy; work-unit commits.
- Delivery: no remote/PR gate in this repo; work-unit commits on `feat/multi-account`. The ~400-line heuristic is advisory here (no reviewer run); keep commits reviewable.
- Artifacts in English.

- Change 2026-10-03: registry v2 — explicit account list (may be empty), nullable `active`; the seeded `opencode-db` default is materialized only for absent/v1 registries; `account list --json` schema 2.

## Change request (2026-10-03) — full account-list ownership

User request: the seeded `default` account must be removable; an empty account list must render as an empty state (dash, no invented account); any configured account must be selectable as the shown ("default") one; and the local OpenCode login must be re-addable under any id.

Model (registry v2):

- The registry is authoritative once it exists: `accounts` may be empty; `active` may be `null` (nothing shown).
- Absent registry or v1 registry (old format): the seeded `opencode-db` account (`id: default`, label "Default") is materialized in memory; the next mutation writes v2 materializing the current effective list (minus removals).
- Every account, of any kind, is removable. Removing the active account falls back to the first remaining account, or `null` when none remain.
- Adding the first account makes it active.
- `ocgo account add <id> --from-db` registers the local OpenCode login as an explicit account (no API key; validated against the local DB).
- `ocgo account list --json` schema 2: `{"schema":2,"active":<id|null>,"accounts":[...]}`; empty list and null active are valid.
- CLI with no accounts: `refresh`/`status`/`auth show` fail with `no accounts configured — run 'ocgo account add <id>'`.
- GNOME: panel shows the existing dash (`Go —`) when there is no active account; the popup Account submenu is always available (empty state: "No accounts configured" + Manage accounts…); prefs remove works for every account, and the add form gains an "OpenCode login (no API key)" option.

## Change request 2 (2026-10-03) — api-key-only adds (scope A, user-chosen)

User decision: remove the no-api-key add path. Every new account is added with its api-key; deletion stays permanent (re-adding an account means loading its key again). Scope A: the seeded `default` (OpenCode login, kind `opencode-db`) remains as-is — seeded on fresh installs, removable, and not recoverable once removed (that account is re-added with its console api-key).

- Remove the prefs "OpenCode login (no API key)" switch and the `ocgo account add --from-db` flag.
- Keep `opencode-db` kind support for the seeded default (refresh/status/auth branching); shrink any code that becomes dead.
- Update tests, README; metadata version v7.

## Tasks

- [x] **T1 — Core: accounts module + tests** *(route: delegated writer — new module + tests, 2+ non-trivial files)* — done: commits `f17d69f` + hardening `edb87ea`; suite 140 green; independent verification PASS-WITH-FINDINGS (all minor, fixed).
  `core/ocgo/accounts.py`, `core/tests/test_accounts.py`.
  Registry at `~/.config/ocgo/accounts.json` (`$XDG_CONFIG_HOME` fallback): id/label/kind/hint/active; atomic writes, 0600; id validation (`[a-z0-9][a-z0-9._-]*`, reserved `default`); secret-tool store/lookup/delete via subprocess; masked hint; opt-in 0600 file store; `OCGO_TOKEN_<ID>` override; unit tests with a fake `secret-tool` on PATH and temp XDG dirs.
- [x] **T2 — Core: zen adapter + account-aware CLI/cache + tests** *(route: delegated writer — same writer session for coherence)* — done: `e732126` (zen adapter) + `0d2ded3` (account CLI); correction `d7005f1` (major key-store shadowing fixed, validated with before/after repro) + hardening `a4a60fa`; suite 225 green.
  `core/ocgo/api.py`, `cli.py`, `cache.py`, tests.
  `fetch_zen_status` + zen→cache mapping; tri-state validation; `cache_path(account_id)`; `account` subcommands; `refresh [--account|--all]`; `status`/`auth show --account`; behavior with no registry identical to today.
- [x] **T3 — GNOME: account-aware cache + popup switcher** *(route: delegated writer)* — done: `747d646` + switch-race fix `661c29f` (validated with before/after harness); static gates green. Accepted minor: rapid consecutive switches may skip the final immediate refresh (UI reconciles; timer covers it).
  `gnome/extension.js` (+ stylesheet if needed); `gnome/scripts/check_collisions.py` must stay green.
  Read accounts/active via `ocgo account list --json`; per-account cache path + monitor re-target on switch; submenu with radio entries → `ocgo account use <id>` + refresh; header shows account label; no-subscription/error states via the existing warning row.
- [x] **T4 — GNOME: prefs account management** *(route: delegated writer — same session as T3)* — done: `5cb9d78` + guards/newest-wins fix `c8c4374` (validated PASS, no residual); static gates green.
  `gnome/prefs.js`: Accounts group — active-account combo (from `account list --json`), add/replace form (id, label, `PasswordEntry`) spawning `ocgo account add|set-key` with the key on **stdin**, remove action, feedback label; nothing secret persists in GSettings.
- [x] **T5 — Docs** *(route: same writer as T3/T4)* — done: README multi-account + security + architecture/data-source notes; `b96f90f`.
  `README.md` accounts section + security notes; update this doc.
- [x] **T6 — Verification** *(route: parent, live)* — done (parent): 225 tests; `make check-gnome`; CLI smoke (list default-only; fake-key add rejected 401 with nothing stored; refresh default real 9%/75%/63%; status; masked `auth show`); isolated `gnome-shell --devkit` session: extension v5 Enabled / State ACTIVE, no `[opencode-go-meter]` errors. Pending: user relogin test (real accounts, switch, prefs).
  `make test`; `make check-gnome`; live smoke (switch default↔named, `refresh --all`, no-subscription account state, `set-key` rotation); isolated `gnome-shell --devkit` session for popup/prefs; secret hygiene spot check (argv/logs/cache/dconf).
- [x] **T7 — Core: full account-list ownership (registry v2, remove default, empty state, `--from-db`)** *(route: delegated writer — same session)* — done: `da46ad7` + fix `5ae8e9c` (legacy-cache cleanup on default removal, refresh failure labels; validated PASS); suite 259 green.
  `core/ocgo/accounts.py`, `cli.py`, tests. Registry v2 + migration (absent/v1 → materialized seeded default); any account removable; nullable active + first-account auto-active; `account add --from-db`; no-accounts CLI errors; `account list --json` schema 2; update the old refusal tests.
- [x] **T8 — GNOME: ownership UI (empty state, remove any account, DB account from prefs, schema 2)** *(route: delegated writer — same session)* — done: `1d2a2bb` (metadata v6) + startup-refresh fix `32e06cc` (validated PASS with real-enable harness); prefs harness 11/11.
  `gnome/extension.js` (parser schema 2, no synthesis, dash + "No accounts configured", refresh skipped when no active), `gnome/prefs.js` (remove for any account with kind-aware confirm; "OpenCode login (no API key)" add option), `metadata.json` v6.
- [x] **T9 — Docs + verification** *(route: same writer + parent live)* — done: README ownership docs `de5551b`; parent live: 259 tests, `make check-gnome`, CLI smoke (no-registry seeded default; `refresh --all` real 12/81/66), devkit **v6 Enabled/ACTIVE**, no errors. Pending: user relogin test.
- [x] **T10 — api-key-only adds (remove `--from-db` + prefs switch)** *(route: delegated writer — same session)* — done: `9241965` (net −94 lines); verifier PASS, no findings; suite 253 green; metadata v7.
  `core/ocgo/cli.py`, `core/tests/test_cli.py`, `gnome/prefs.js` (metadata v7), `README.md`. Remove the no-key add path; keep the seeded `opencode-db` default working; update tests/docs.
  README (ownership model, empty state, `--from-db`), task doc; parent live checks (CLI smoke incl. remove default + re-add, devkit v6); user relogin test.

## Acceptance criteria

- `ocgo account add work --label "Work"` prompts hidden, validates, stores in keyring, registers. Invalid key → rejected; valid without subscription → stored with state.
- `account list` shows accounts + active; `use` switches; `set-key` replaces; `remove` cleans registry + keyring + cache.
- `refresh --all` covers every account; plain `refresh`/`status` follow the active one.
- GNOME: one panel; switching updates panel/popup to that account; no-subscription accounts show a clear message; prefs add/replace works and leaks nothing to dconf.
- No-registry behavior is byte-compatible with today (legacy cache path, same messages).
- Keys never in argv/logs/cache/dconf; masked everywhere else.

## Checks

- `make test` (unittest), `make check-gnome`.
- Live smoke: `ocgo account add|list|use|set-key|remove`, `refresh --all`, `status`.
- Isolated devkit session for GNOME flows.
- Manual: compare the active account's numbers against the console.

## Progress log

- 2026-10-02 — Feasibility verified live (zen 401/403/200; console rejects api-keys); route source reviewed; plan written. Baseline `make test`: 86 green. Branch `feat/multi-account` created.
- 2026-10-02 — T1 closed: `core/ocgo/accounts.py` (registry + secret-tool/file/env secret storage) with 54 tests (`f17d69f`); hardening `edb87ea` (int-only version check, unreadable-file errors, fd-leak fix, secret deleted before registry on remove); full suite 140 green; independent verifier PASS-WITH-FINDINGS (6 minor: 4 fixed + 2 documented; keyring-clear stays best-effort by design).
- 2026-10-02 — T2 closed: zen adapter (`fetch_zen_status`, `to_cache_schema_zen`; 401/403-entitlement/error mapping) + account CLI (`account add|set-key|list|use|remove`, `refresh/status/auth show --account|--all`, per-account cache paths) in `e732126`+`0d2ded3`; independent verification PASS-WITH-FINDINGS (1 major: silent key-store shadowing on `set-key --store file`; 2 minors) → fixed in `d7005f1`, validated with before/after repro; residual best-effort keyring-clear path hardened in `a4a60fa`; suite 225 green; no-registry behavior byte-compatible (verified against the pre-T2 tree).
- 2026-10-02 — T3 closed: `gnome/extension.js` account discovery (`account list --json`, fallback to default), per-account cache path + monitor re-target, popup account submenu (radio, hidden for single default), switch via `account use` + immediate refresh, named-account header; `747d646` (metadata v4); switch↔load race fixed in `661c29f` (newest-wins generation, before/after harness proof). Independent verification PASS-WITH-FINDINGS (2 minors fixed, validated; 1 accepted minor: rapid double-switch may skip the final immediate refresh).
- 2026-10-02 — T4 closed: prefs Accounts group (active combo, add/replace key via stdin, remove with confirmation, feedback) in `5cb9d78` (metadata v5); verifier PASS-WITH-FINDINGS (2 minors: double-submit guard, loads without newest-wins) → `c8c4374` validated PASS (no residual).
- 2026-10-02 — T5 closed: README multi-account + security + architecture notes (`b96f90f`).
- 2026-10-02 — T6 (parent, live): `make test` 225 green; `make check-gnome`; CLI smoke OK (fake-key add → 401, nothing stored; refresh default real 9/75/63; status; auth show masked); isolated `gnome-shell --devkit`: extension v5 Enabled / State ACTIVE, no errors. Pending: user relogin test.
- 2026-10-03 — T7 closed (change request): registry v2 (explicit list, nullable active, seeded default materialized only for absent/v1 registries; any account removable; first-account auto-active), `account add --from-db`, kind-based CLI branching, empty-state errors, `account list --json` schema 2; `da46ad7` + fix `5ae8e9c` (validated PASS); suite 259 green.
- 2026-10-03 — T8 closed: GNOME ownership UI (schema 2, no synthesis, empty state + always-present Account submenu, remove any account with kind-aware confirm, `--from-db` option in prefs; metadata v6) in `1d2a2bb`; verifier found 1 major (startup refresh skipped) + 1 minor (logs) → fixed in `32e06cc`, validated PASS (real-enable harness 17/17; prefs 11/11).
- 2026-10-03 — T9 closed: README ownership docs (`de5551b`); parent live: 259 tests, check-gnome, CLI smoke (seeded default with no registry; `refresh --all` 12/81/66), devkit v6 Enabled/ACTIVE, no errors. Pending: user relogin test.
- 2026-10-03 — T10 closed (change request 2, scope A): no-api-key add path removed (`--from-db` + prefs switch), `account add` always takes the key from stdin, seeded `opencode-db` default unchanged, dead code shrunk (net −94 lines), metadata v7; `9241965`; verifier PASS (no findings); suite 253 green.
- 2026-10-03 — User live test confirmed: after relogin, extension v7 shows the active api-key account (`martinrdilorenzo`) with live numbers — feature complete and verified end-to-end.

## Next step

Feature complete. Optional: merge `feat/multi-account` (user's call); Cinnamon frontend (base feature T8); notifications; popup mini-bars.
