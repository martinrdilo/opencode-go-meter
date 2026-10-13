# Feature: first-run-accounts — fresh install with an API key only

**Status**: T1–T5 done — T6 in progress (PR #3)
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
handles the seeded default) — the real gaps are replace-by-key,
discoverability, and messaging.

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
| tests pinning the seed | test_accounts.py:393/423/464/479/547/706/807 (+ CLI fixtures) — fixture ripple, all updated to a stored-login fixture |

## Decisions

- **Seed predicate**: new `creds.has_stored_login()` = `OCGO_TOKEN` set
  (non-empty) OR an `opencode` DB row exists, **any expiry state**. Applied
  **only** to the absent-registry case; v1 migration keeps prepending; stored
  v2/v3 unchanged. (T5 correction `2d679d0`: the probe is a bare existence
  query on stable columns — the listing query's `label` dependency made
  label-less schemas read as "no login".)
- **`set-key` converts**: `accounts.convert_to_api_key(account_id, hint)`
  (kind flips to api-key, hint set, `credential_id` dropped, id/label/active
  kept, single registry write) + CLI wiring. The UIs needed no changes — they
  already route existing ids to `set-key`. Validation parity with the other
  key paths was added in `529a585` (the UI copy promises CLI validation);
  T5 correction `6212d81` rolls the secret back if the conversion fails
  (mirrors `cmd_account_add`).
- **Cache messaging** (`281a1a3`): credential-resolution failures now record
  `last_error` for every account kind (the old `if not is_db` guard was the
  only thing silencing lost/expired logins; no test or doc pinned its
  behavior, and `ApiError` failures already wrote the same field). No prior
  cache → still nothing written, so fresh states stay clean. No frontend
  changes: both GUIs read the same cache (the amber row).
- **Frontends**: zero changes (verified: `git diff f521d4d..HEAD -- cinnamon
  gnome` is empty); live pass confirms.
- **Docs**: README Accounts intro describes both first-run starts; the
  `set-key` comment notes login conversion.
- Delivery: single PR (#3); forecast ≈ 300 authored lines; **actual 798
  changed lines (706+/92−, tests are ~85%)** → `single-pr` +
  documented size exception (repo precedent).
- RDD **off** → per-diff assess: T2 medium/under_budget, T3 medium/
  under_budget, T3-correction+T4+T4b medium/under_budget (146), corrections
  medium (104). TDD on core throughout (RED/GREEN per commit).
- Artifacts in English; conversation in Spanish.

## Tasks

- [x] **T1 — Recon + feature doc** *(route: parent)*. DONE 2026-10-13, commit
  `f521d4d`. Report verified line-by-line against merged main; corrections and
  design recorded above; branch seeded from `574d0f7`.
- [x] **T2 — Core: conditional seeding** *(route: delegated writer; surfaces:
  `core/ocgo/creds.py`, `core/ocgo/accounts.py`, `core/tests/{test_creds,test_accounts,test_cli}.py`)*.
  DONE 2026-10-13, commit `cfe6c08` (+15/−9 accounts, +14 creds, test ripple
  across the three files). RED: 13-test run with 5 failures + 8 errors
  (missing `has_stored_login`; the phantom listed). GREEN: 414 tests OK.
  Assessment medium/under_budget (`executable_change`) → writer
  self-verification + parent spot checks.
- [x] **T3 — CLI: set-key converts** *(route: same writer session; surfaces:
  `core/ocgo/{accounts,cli}.py`, `core/tests/{test_accounts,test_cli}.py`)*.
  DONE 2026-10-13, commit `6de9722` (+25 accounts, +13/−5 cli, +197 tests).
  RED: 17-test run with 5 failures + 7 errors (missing `convert_to_api_key`;
  old refusal message). GREEN: 414 tests OK at that point. Assessment
  medium/under_budget.
- [x] **T3 correction — validation parity** *(route: same writer session;
  surfaces: `core/ocgo/cli.py`, `core/tests/test_cli.py`)*. DONE 2026-10-13,
  commit `529a585` (+20/−14 cli, +62/−5 tests): the conversion now runs
  `fetch_zen_status` like `add`/api-key `set-key` (entitlement → warning +
  convert; `ApiError` → fail with nothing stored). RED: 3 failures.
- [x] **T4 — README + messaging trace** *(route: same writer session; surfaces:
  `README.md`)*. DONE 2026-10-13, commit `5a11aa6` (+2/−2). Trace findings:
  state "no accounts" fully surfaced (CLI message, tooltip, submenu);
  state "login registered, credentials gone/lost" had silent paths — see T4b.
- [x] **T4b — cache recording** *(route: same writer session; surfaces:
  `core/ocgo/cli.py`, `core/tests/test_cli.py`)*. DONE 2026-10-13, commit
  `281a1a3` (+4/−2 cli, +35 tests): removed the `if not is_db` guard after
  evidence that no test pinned it and `ApiError` already recorded the same
  field. RED: 2 failures (both cache paths silent). GREEN: 418 tests OK;
  live CLI smoke shows the recorded `last_error` with prior windows kept.
- [x] **T5 — Verification** *(route: parent + independent verifier)*. DONE
  2026-10-13. **Static gates**: `make test` (418→422), `make check-cinnamon`
  + `check-gnome`, `node --check` — green. **Live pass (nested Cinnamon
  6.4.13, fresh scratch `:20`, clean env)**: fresh no-login → `accounts=0`
  (no phantom), panel `—`, popup empty rows, **Add dialog shows both
  "OpenCode login" and "API key"** (screenshot `add-dialog-empty.png`); CLI
  in the same env → `no accounts configured`, empty JSON, refresh
  `NO_ACCOUNTS_MESSAGE`, `add` fails at the live API validation (HTTP 401),
  `set-key default` → "does not exist". T4b spot: prior cache + missing
  credential → `last_error` recorded, windows kept. Login regression: the
  real-DB scratch still lists `default`. Screenshots:
  `/tmp/opencode/fra-live/{panel,popup,add-dialog}-empty.png` (+ stateB
  captures from a mis-env'd launch that serendipitously validated the
  "registered login + credentials unavailable" state). **Independent
  verifier** (`f521d4d..281a1a3`, fresh read-only, adversarial probes):
  verdict `verified with findings` — no MAJOR/MINOR. Findings: LOW (probe
  depended on the listing query's `label` column — corrected in `2d679d0`),
  NIT (no secret rollback on conversion failure — corrected in `6212d81`),
  NOTE (absent-registry DB probe cost ~39 ms; negligible, recorded).
  Corrections re-checked by the parent (targeted 25-test run OK; diffs
  reviewed). Post-correction suite: **422 OK**; live smoke on a label-less DB
  seeds the default again.
- [ ] **T6 — PR #3** *(route: parent; branch-pr skill)*.

## Acceptance criteria

- No login stored, no registry: `ocgo account list` → empty; `refresh` →
  `NO_ACCOUNTS_MESSAGE`; applet popup shows the empty state; the Add dialog
  offers both options; adding an API key becomes active and lands data — the
  live pass covers everything except the final real-key add (residual below).
- Login stored (incl. expired): seeded default exactly as before.
- `ocgo account set-key <login-id>` converts (validation parity, rollback on
  failure); UIs unchanged; registry valid v3.
- Gates green; README updated. → DONE (suite 422 OK; static checks green).

## Residuals (documented)

- Real-key happy paths (add / convert / refresh with a real API key; keyring
  backend) — covered by mocked tests + live 401 rejection; the real round-trip
  is the user's field check (same policy as prior features).
- GNOME live pass not run (frontends unchanged; static verification only).
- `account discover` still requires the `label` column (only the seed probe
  was made schema-independent) — noted by the verifier.

## Checks

- `make test` (core; 422 tests).
- `make check-cinnamon` / `make check-gnome`; `node --check cinnamon/applet.js`.
- Nested Cinnamon 6.4 run (recipe `odd/tasks/cinnamon-applet.md`; drive via
  `org.Cinnamon.Eval` as in `odd/tasks/cinnamon-54-compat.md` T5).

## Forecast

≈ 300 forecast; **798 actual changed lines (706+/92−)** — tests are the bulk
(T2/T3 fixture ripple + new coverage). Single PR with a documented size
exception (precedent: multi-oauth-accounts).

## Progress log

- 2026-10-13 — T1 done (`f521d4d`): report verified against merged main; two
  corrections; design (predicate + convert + docs); branch from `574d0f7`.
- 2026-10-13 — T2 done (`cfe6c08`): conditional seed + fixture ripple; RED
  evidence; 414 OK. Assessment medium/under_budget.
- 2026-10-13 — T3 done (`6de9722`) + validation parity (`529a585`): set-key
  conversion with the same API validation as every other key path.
- 2026-10-13 — T4 done (`5a11aa6`) + T4b (`281a1a3`): README twins the two
  first-run paths; credential failures now reach the GUIs' amber row via the
  cache (guard removal justified by evidence). 418 OK.
- 2026-10-13 — T5 done: live nested pass (empty state + both options +
  regression) and independent verifier `verified with findings`; corrections
  `2d679d0` (schema-independent probe) + `6212d81` (secret rollback) →
  **422 OK**. Next: T6 (PR #3).

---

Locator: odd/tasks/first-run-accounts.md (repo: opencode-go-meter)
