# Feature: multi-account — add, switch, and replace OpenCode Go accounts (one panel)

**Status**: In progress — T1 done (2026-10-02); T2 next
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
- The registry is the single source of truth for the account list and the active account (no dconf key for it).
- Cache: `default` → legacy `~/.cache/ocgo/status.json` (zero migration); named accounts → `~/.cache/ocgo/accounts/<id>/status.json`.
- zen cache mapping: `windows.<rolling|weekly|monthly>` ← `percent` + `resetsAt`; `used_usd`/`limit_usd` = `null`; `renewal_ends_at` ← `monthly.resetsAt`; schema stays v1 (nullable USD documented).
- Add/set-key tri-state: `401` → rejected; `403 EntitlementError` → stored with "no subscription" state; `200` → active.
- TDD: OFF (no project/session config; repo convention). Runner: `make test`.
- RDD: off (global) → ordinary repository policy; work-unit commits.
- Delivery: no remote/PR gate in this repo; work-unit commits on `feat/multi-account`. The ~400-line heuristic is advisory here (no reviewer run); keep commits reviewable.
- Artifacts in English.

## Tasks

- [x] **T1 — Core: accounts module + tests** *(route: delegated writer — new module + tests, 2+ non-trivial files)* — done: commits `f17d69f` + hardening `edb87ea`; suite 140 green; independent verification PASS-WITH-FINDINGS (all minor, fixed).
  `core/ocgo/accounts.py`, `core/tests/test_accounts.py`.
  Registry at `~/.config/ocgo/accounts.json` (`$XDG_CONFIG_HOME` fallback): id/label/kind/hint/active; atomic writes, 0600; id validation (`[a-z0-9][a-z0-9._-]*`, reserved `default`); secret-tool store/lookup/delete via subprocess; masked hint; opt-in 0600 file store; `OCGO_TOKEN_<ID>` override; unit tests with a fake `secret-tool` on PATH and temp XDG dirs.
- [ ] **T2 — Core: zen adapter + account-aware CLI/cache + tests** *(route: delegated writer — same writer session for coherence)*
  `core/ocgo/api.py`, `cli.py`, `cache.py`, tests.
  `fetch_zen_status` + zen→cache mapping; tri-state validation; `cache_path(account_id)`; `account` subcommands; `refresh [--account|--all]`; `status`/`auth show --account`; behavior with no registry identical to today.
- [ ] **T3 — GNOME: account-aware cache + popup switcher** *(route: delegated writer)*
  `gnome/extension.js` (+ stylesheet if needed); `gnome/scripts/check_collisions.py` must stay green.
  Read accounts/active via `ocgo account list --json`; per-account cache path + monitor re-target on switch; submenu with radio entries → `ocgo account use <id>` + refresh; header shows account label; no-subscription/error states via the existing warning row.
- [ ] **T4 — GNOME: prefs account management** *(route: delegated writer — same session as T3)*
  `gnome/prefs.js`: Accounts group — active-account combo (from `account list --json`), add/replace form (id, label, `PasswordEntry`) spawning `ocgo account add|set-key` with the key on **stdin**, remove action, feedback label; nothing secret persists in GSettings.
- [ ] **T5 — Docs** *(route: same writer as T3/T4)*
  `README.md` accounts section + security notes; update this doc.
- [ ] **T6 — Verification** *(route: parent, live)*
  `make test`; `make check-gnome`; live smoke (switch default↔named, `refresh --all`, no-subscription account state, `set-key` rotation); isolated `gnome-shell --devkit` session for popup/prefs; secret hygiene spot check (argv/logs/cache/dconf).

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

## Next step

Start T2 (zen adapter + account-aware CLI/cache).
