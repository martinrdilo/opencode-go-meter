# Feature: first-run-accounts — fresh install with an API key only

**Status**: In progress — T1 recon done; T2–T6 pending
**Repo**: `opencode-go-meter`
**Branch**: `fix/first-run-accounts` (from `main` @ `574d0f7`)
**Created**: 2026-10-13

## Objective

A first-time user whose OpenCode setup has only an API key can register their
first account from the applet/app preferences without fighting a phantom
`default` account; the seeded default exists only when a login is actually
stored; an existing OpenCode-login account can be replaced by an API key; the
empty / no-credential states explain themselves.

## Problem / Why (report, 2026-10-13 — Mint 21 / Cinnamon 5.4.13 fresh install)

With no `~/.config/ocgo/accounts.json` and only an API key in `auth.json`:

- `_effective_registry()` (accounts.py:140-165) materializes the seeded
  `default` (opencode-db, accounts.py:131) **in memory** — the user never
  registered it.
- The add dialog gates on "an opencode-db entry exists" (`hasLogin` /
  `_hasAutoLogin()` + `_credentialChoices`), so only "API key" is offered.
- Typing the obvious id `default` → `accountCommandFor` picks `set-key` →
  `cmd_account_set_key` refuses opencode-db accounts (cli.py:431-435).
- Even with a NEW id the dead-end persists: `add_account` persists the seeded
  entry alongside the new account and the active stays `default` → the panel
  stays empty with no explanation.

Report corrections (verified): removal from the UI **does** exist (Cinnamon
settings "Remove account…", GNOME Remove row; `remove_account()` explicitly
handles the seeded default, accounts.py:225-range) — the real gaps are
replace-by-key, discoverability, and messaging.

## Evidence (verified against merged main `574d0f7`)

| anchor | state |
| --- | --- |
| `accounts.py:140` `_effective_registry()` | absent → seeded default; v1 → prepends; v2/v3 stored → as-is |
| `accounts.py:131` `_seeded_default_entry()` | `{id, label, kind: opencode-db, hint: None}` |
| `accounts.py` imports | already `from .creds import mask_token` — no new layering to add the predicate |
| `creds.py:34/141` | `_ENV_TOKEN = "OCGO_TOKEN"`; `list_db_credentials()` raises `CredentialError` when the DB is missing/unreadable |
| `cli.py:420-435` | `cmd_account_set_key` refuses opencode-db accounts ("there is no API key to set") |
| `cli.py:27/145/215` | `NO_ACCOUNTS_MESSAGE` covers refresh/status empty paths |
| applet `_hasAutoLogin`/`_credentialChoices` (allowLogin) | with no accounts AND no discovered credentials the "OpenCode login" option is shown — no change needed once the phantom is gone |
| GNOME `_updateFormState` kind rebuild (prefs.js:324+) | same model (parity) |
| applet empty/error surfaces | popup 'No accounts configured' (:472) + amber 'Last refresh failed: …' row (:579-588) |
| tests pinning the seed | test_accounts.py:393/423/464/479/547/706/807 (+ CLI fixtures relying on it) — fixture ripple expected |

## Decisions

- **Seed predicate**: new `creds.has_stored_login()` = `OCGO_TOKEN` set
  (non-empty) OR DB rows exist, **any expiry state** (an expired login keeps
  the seeded default and its existing messaging). Applied **only** to the
  absent-registry case; v1 migration keeps prepending the seed; stored v2/v3
  unchanged.
- **`set-key` converts**: new `accounts.convert_to_api_key(account_id, hint)`
  (kind flips to api-key, hint set, `credential_id` dropped, id/label/active
  kept, single registry write) + CLI wiring (read key → `store_secret` →
  convert → informative message; `--store` honored). The UIs need no changes —
  they already call `set-key` for ids that exist.
- **Frontends**: expected zero changes; the live pass confirms; patch only if a
  gap appears.
- **Messaging**: the existing surfaces (CLI `NO_ACCOUNTS_MESSAGE`, popup empty
  state + warning row) are expected to cover the states; verify and patch only
  a silent path.
- **Docs**: README Accounts intro nuance — the default exists only when a login
  is stored; the API-key-only fresh start goes straight to the add dialog.
- Delivery: single PR (#3); forecast ≈ 300 authored lines incl. the test
  ripple; ask-on-risk, no chain expected.
- RDD **off** → per-diff assess for verification depth; TDD on core (fixtures
  with/without a stored login); JS side static + live nested Cinnamon 6.4.
- Artifacts in English; conversation in Spanish.

## Tasks

- [x] **T1 — Recon + feature doc** *(route: parent)*. DONE 2026-10-13. Report
  verified line-by-line against merged main; corrections and design recorded
  above; branch seeded from `574d0f7`.
- [ ] **T2 — Core: conditional seeding** *(route: delegated writer; surfaces:
  `core/ocgo/creds.py`, `core/ocgo/accounts.py`, `core/tests/test_creds.py`,
  `core/tests/test_accounts.py`, `core/tests/test_cli.py`)*.
  `creds.has_stored_login()` + absent-registry branch in `_effective_registry()`
  + test ripple (seed-pinning tests get a login fixture — `OCGO_TOKEN` or a
  crafted DB; new tests for the no-login empty view). RED→GREEN where testable.
- [ ] **T3 — CLI: set-key converts** *(route: same writer session; surfaces:
  `core/ocgo/accounts.py`, `core/ocgo/cli.py`, `core/tests/test_accounts.py`,
  `core/tests/test_cli.py`)*. `convert_to_api_key` + wiring + tests (conversion
  from CLI, pinned login drops the pin, slot freed for a new `--from-db` login,
  refusal test replaced).
- [ ] **T4 — Docs + messaging verification** *(route: writer or parent;
  surfaces: `README.md`, plus a frontend patch only if a gap is verified)*.
- [ ] **T5 — Verification** *(route: parent + independent verifier)*. Gates;
  live nested Cinnamon 6.4: fresh **no-login** scratch → empty state, add works
  with id `default`, panel shows data after refresh; **login** scratch → default
  still seeded as before; `set-key` conversion live (CLI in the scratch, plus
  the settings path if feasible). Independent verifier over the range.
- [ ] **T6 — PR #3** *(route: parent; branch-pr skill)*.

## Acceptance criteria

- No login stored, no registry: `ocgo account list` → empty; `ocgo refresh` →
  `NO_ACCOUNTS_MESSAGE`; applet popup shows the empty state; the Add dialog
  offers both options; adding id `default` as an API key **succeeds**, becomes
  active, and the panel shows data after refresh.
- Login stored (incl. expired): seeded default exactly as today; messaging
  unchanged.
- `ocgo account set-key <login-id>` with a key converts the entry (kind
  api-key, masked hint stored, label/active kept, credential slot freed) —
  from the CLI and from both UIs' add/replace path; registry stays valid v3.
- Gates green: `make test`, `make check-cinnamon`, `make check-gnome`,
  `node --check`; README updated.

## Checks

- `make test` (core; seed fixtures + conversion tests).
- `make check-cinnamon` / `make check-gnome`; `node --check cinnamon/applet.js`.
- Nested Cinnamon 6.4 run (recipe in `odd/tasks/cinnamon-applet.md`; driving via
  `org.Cinnamon.Eval` as in `odd/tasks/cinnamon-54-compat.md` T5).

## Forecast

≈ 300 authored lines including the test ripple (core ~60; tests ~200; README
~10). Under the 400-line budget → single PR.

## Progress log

- 2026-10-13 — T1: feature opened from `main` @ `574d0f7` (post-#1 merge).
  Report verified against the merged code; two corrections recorded; design
  (predicate + convert + docs) decided; branch `fix/first-run-accounts`.

---

Locator: odd/tasks/first-run-accounts.md (repo: opencode-go-meter)
