# Feature: oauth-account-add — OpenCode login (OAuth) as a first-class, default account option

**Status**: in progress (started 2026-10-11)
**Repo**: `opencode-go-meter`
**Branch**: `feat/oauth-account-add` (stacked on `feat/credits-panel`)
**Created**: 2026-10-11

## Objective

Make the local OpenCode Console login (OAuth credential) a first-class account option again: registrable from the CLI and from both settings UIs, offered as the **default** choice in the add flow, and resolved from the DB's **active** credential so the app follows `opencode auth switch`.

## Problem / Why

User request (2026-10-11): "Quiero que la aplicación ofrezca la posibilidad de login OAuth y quiero que sea ese por defecto."

Context: the credits feature made the OAuth login the only credential that can read credits (API keys get 403). The user experienced the gap directly: after removing the seeded default (which they did with help), there was **no way to re-add the login from the app** — it required a manual registry edit.

**History (deliberate reversal)**: `--from-db` + a prefs "OpenCode login (no API key)" switch existed (T7/T8 of the multi-account feature) and were **removed by user decision** (T10, `f232567`: "every account is added with its api-key; deletion stays permanent"). The user now reverses that decision with new information (credits need OAuth). This feature revives the path, improved.

## Design (approved by the user, 2026-10-11)

- The app does **not** implement its own OAuth flow (fragile, unofficial, duplicates OpenCode). Sign-in stays OpenCode's job (`opencode auth login "OpenCode Console"` exists). The app detects the local login and guides when missing.
- CLI: `ocgo account add <id> [--label L] --from-db` — registers the local OpenCode login (validated against the local DB: existence + not expired; no key prompt, no hint). Refused when an `opencode-db` account already exists (the login is singular).
- UIs: the add flow offers both kinds — **"OpenCode login" default** + "API key" (the OAuth option hidden/disabled when one already exists; key field only for API key). If no login is found, the error tells the user to sign in via OpenCode.
- Credential resolution: prefer the DB's `active = 1` credential (fallback: newest `time_updated`) instead of `ORDER BY id DESC` (random ids — arbitrary row with multiple console accounts).

## Data (verified 2026-10-11)

- DB `credential` table: `id, integration_id, label, value, connector_id, method_id, active, time_created, time_updated`. Current row: `integration_id='opencode'`, label `Default`, `active=1`.
- `opencode auth list` → `OpenCode Console / Default / stored`; `opencode auth login [target] [--method] [--answer]`; `opencode auth switch [target] [credential]` (multiple console accounts possible; `active` marks the active one).
- Prior art to revive: `f232567` (removal diff) — old CLI `--from-db` path, old `add_account(kind=…)`, old prefs switch.

## Tasks

- [x] **T1 — Design + recon** *(route: parent, inline)*: history recovered, DB schema + CLI surface verified, plan approved by the user. Evidence: this doc.
- [x] **T2 — Core: `--from-db` + active-credential resolution** *(route: delegated writer — multi-file)*: `accounts.add_account(kind=…)` restored with the one-`opencode-db` invariant; `creds` resolution by `active` (fallback newest `time_updated`); CLI flag + flow + errors; tests. Evidence: commit `7a228ec`; suite 309 → 326 green; checks green (parent re-ran); writer live smoke in an isolated env (fresh → refused because the seeded default occupies the slot; remove default → re-add `--from-db` → registered; second login refused; active row resolved); assess medium (431 lines, slice budget reached — `single-pr` + `size:exception` recorded).
- [x] **T3 — Frontends: add-flow kind chooser** *(route: delegated writer — GNOME + Cinnamon parity)*: "OpenCode login" (default when available) / "API key"; key row only for API key; guide when no login; GNOME metadata bump. Evidence: commit `cf5a0b8`; `node --check` ×2 + metadata JSON + checks green (parent re-ran); assess medium (177 lines, under budget); Cinnamon `RadioButtonGroup` API verified against the installed 6.4 source (`addButton`/`setActive`/`getActive` + `'radio-changed'`); devkit shell v11 `ACTIVE`, `error: ''`.
- [~] **T4 — Verification** *(route: parent + per-action)*: suite 326 green (T2); live refusal smoke OK (`an OpenCode login account already exists: 'default'`, registry untouched); devkit v11 clean. **Pending: the user's UI confirmation** (their current state has the login registered, so the add flow shows only "API key" — the OAuth default appears when none is registered).
- [x] **T5 — Docs** *(route: parent)*: README Accounts section, this doc closed. Evidence: this docs commit.

## Acceptance criteria

- `ocgo account add X --from-db` registers the login; refused with a clear message when one exists; missing/expired login → actionable error.
- Both UIs offer "OpenCode login" as the default add option; API-key flow unchanged.
- With multiple console credentials in the DB, the app reads the `active` one.
- Suite + static checks green; live smoke OK.

## Constraints / Decisions

- Core: Python 3 stdlib only; unittest via `make test`. TDD OFF. RDD off.
- Artifacts in English. Frontends still never touch credentials (they only run the CLI).
- Delivery: `single-pr` (carrying the maintainer's accepted pattern + `size:exception` from credits-panel); work-unit commits on `feat/oauth-account-add`; push/PR is the user's call.
- GNOME dev reload rule: metadata bump (10 → 11).

## Progress log

- 2026-10-11 — T1 done: user request + approval; T10 reversal recorded; branch created.
- 2026-10-11 — T2 done (delegated writer): core `--from-db` + active-credential resolution; suite 309 → 326; isolated live smoke OK; assess medium.
- 2026-10-11 — T3 done (delegated writer): kind chooser in both add flows (OAuth default); metadata v11; assess medium (177 lines); Cinnamon radio API verified against installed source.
- 2026-10-11 — T4 (automated) + T5 done: live refusal smoke + devkit v11 clean; README updated. Pending: user UI confirmation.
