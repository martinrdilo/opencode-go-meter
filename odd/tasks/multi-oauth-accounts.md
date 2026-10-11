# Feature: multi-oauth-accounts — multiple OpenCode Console (OAuth) logins as first-class accounts

**Status**: IN PROGRESS — T1–T2 done; T3–T5 pending
**Repo**: `opencode-go-meter`
**Branch**: `feat/multi-oauth-accounts`
**Created**: 2026-10-11
**Delivery**: `single-pr` + `size:exception` (repo precedent); work-unit commits; forecast ~600–800 authored lines

## Objective

Let the app register and use **multiple** OpenCode Console (OAuth) logins — one per credential row in the local OpenCode database — instead of the current singular `opencode-db` account that only ever follows the DB's `active` credential. Each login becomes an app account with its own meters/credits, independent from OpenCode's global active credential. Plus: a read-only listing of bindable credentials for both add-flow pickers, and a small action to make an app login the active credential in OpenCode (`opencode auth switch`).

## Problem / Why

User request (2026-10-11, seed in Engram topic `odd/multi-oauth-accounts/idea`): support MULTIPLE OAuth accounts, not just one. Current model: 1 `opencode-db` account (follows DB `active = 1`, fallback newest `time_updated`) + N `api-key`. To see another OAuth account's meters you must switch OpenCode's global active credential and wait for the app refresh.

Option A (chosen by the user 2026-10-11) beat option B (switch-only action) because it lets all accounts' meters/credits be visible without touching OpenCode's global state; B's switch action rides along as a small bonus (see `activate-in-opencode`).

## Data (verified 2026-10-11, read-only)

- `opencode auth switch [target] [credential]` — credential id/label accepted positionally; the account picker only opens when the credential is omitted → non-interactive switching is possible.
- Local DB today: 1 credential (`label=Default`, `active=1`, `method=device`, `type=oauth`). `value` JSON keys: `access`, `expires`, `refresh`, `metadata` (`accountID`, `email`, `orgID`, `orgName`, `server`).
- Token TTL 30 days; `time_updated` == creation (no rotation yet) → dormant-credential staleness is mild (~30d grace; refreshed when used in OpenCode). `EXPIRED_MESSAGE` already covers the stale case.
- Injection points (line refs corrected after verification): the `creds.resolve_credential` resolver sites are `_refresh_one`, `cmd_auth_show`, and the `--from-db` add path (`cmd_status` is cache-only and never resolves); the singular invariant lived in `add_account`; frontends pin the accounts JSON payload `schema = 2` (`gnome/prefs.js:9`, `cinnamon/applet.js:27`) — the additive `credential_id` field keeps it at 2.
- Recon memory: Engram obs #1438 (`odd/multi-oauth-accounts/recon`).

## Design (approved by the user, option A)

### Core model

- Registry file version 2 → **3** (core-internal; v1/v2 read-compat, no forced migration: a v2 singular login reads as the *auto* binding).
- `opencode-db` entries gain an optional `credential_id`:
  - absent/None = **auto** (follows the DB `active` credential, fallback newest `time_updated`) — at most ONE, preserved from v2;
  - present = **pinned** to that DB credential id (stable binding; label is display-only) — duplicate pins refused.
- `accounts.Account` gains `credential_id: str | None = None`; `account list --json` payload keeps `schema: 2` (additive change) with `credential_id` in entries (null when N/A) so old consumers keep working.
- `creds.resolve_credential(*, credential_id=None)`: pinned → `WHERE integration_id='opencode' AND id = ?`; dangling id → clear actionable error; expiry check unchanged (`EXPIRED_MESSAGE`). `OCGO_TOKEN` stays the global manual override (checked first, as today).
- New `creds.list_db_credentials()` → read-only listing (id, label, active, email, org_name; malformed metadata → nulls; never tokens) for the CLI picker command.
- Add (`--from-db`): validates existence + not-expired of the target credential (parity with the current flow). New `--credential <id-or-label>` selects a pinned target (exact id first, then exact label; ambiguous label → error); without it → auto. `--credential` requires `--from-db`.

### CLI (new)

- `ocgo account discover --json` — read-only listing of the DB's opencode credentials for the pickers: `{"schema": 1, "credentials": [{"id", "label", "active", "email", "org_name"}]}` (email/org_name nullable; order `time_updated` desc). Human-readable mode too.
- `ocgo account activate-in-opencode <account-id>` — pinned login → runs `opencode auth switch opencode <credential_id>`; errors: account not found / not `opencode-db` / auto (nothing to switch) / `opencode` missing from PATH / `opencode` non-zero (relay its message).

### Frontends (parity GNOME + Cinnamon)

- Add flow: type "OpenCode login" reveals a credential combo: (a) "Auto (follows the active account)" when no auto login exists yet, and (b) each discovered credential not already registered. The "OpenCode login" type is offered while (a) or (b) is non-empty. Key row stays API-key-only.
- Accounts list: N logins listed; a "Make active in OpenCode" action for the selected pinned login (confirmation dialog, repo pattern) with feedback via the status row.
- Dangling feedback: after loading accounts + discover, a pinned login whose credential id is gone from the DB gets a feedback line naming it (remove or re-add).
- GNOME `metadata.json` 12 → 13.

## Tasks

- [x] T1 — Design + recon *(route: parent, inline)*: facts live-verified, options A/B presented, user approved A (with the activate-in-opencode bonus). Evidence: this doc + Engram #1438. Pending (non-blocking): live probe of refresh-on-switch behavior (needs user OK) — affects UX copy only.
- [x] T2 — Core *(route: delegated writer — multi-file core + tests)*: registry v3 + pinned binding + `creds` resolve-by-id + `list_db_credentials` + CLI (`--credential`, `discover`, `activate-in-opencode`) + tests. Evidence: commits `12f9fec` + `4f5afae`; suite 326 → 384 green; isolated smoke OK (3 synthetic credentials: discover/add-by-id/add-by-label/list/activate/dangling + `refresh --all` continuation); independent verifier **verified** (57/57 probes, 0 blockers, 0 minors); assess `unassessable/high` (OpenCode runtime not eligible for immutable receipt review — RDD off) → independent verifier path per the delegated gate; 3 nit findings closed in bounded correction `c7cdb92` (explicit-null tolerance, load-time cross-entry validation, 10s `opencode` subprocess timeout); parent spot check 390 green.
- [ ] T3 — Frontends *(route: delegated writer — GNOME + Cinnamon parity)*: credential picker, multi-login list, activate action, dangling feedback; metadata 13. Evidence: TBD.
- [ ] T4 — Verification *(route: parent + per-action)*: `make test` + static checks; isolated smoke via `OCGO_DB` temp DB with synthetic credentials; user UI confirmation; optional real smoke once a 2nd account is logged in (`opencode auth login`, user action). Evidence: TBD.
- [ ] T5 — Docs *(route: parent)*: README accounts section + doc close. Evidence: TBD.

## Acceptance criteria

- Registry v3: auto singular + N pinned logins; duplicates/dangling/expired produce actionable errors; v1/v2 registries read cleanly.
- `ocgo account discover --json` lists DB credentials (schema 1) without exposing secrets.
- `ocgo account activate-in-opencode <id>` switches OpenCode's active credential for pinned logins; clear errors otherwise.
- Per-account refresh/status reads each login's own credential (pinned) or the active one (auto).
- Both UIs: add flow offers Auto + unregistered credentials; N logins visible; activate action works; dangling state surfaced.
- Suite + static checks green; isolated smoke OK.

## Constraints / Decisions

- Core: Python 3 stdlib only; tests via `make test` (full suite). TDD OFF (repo convention) — tests still required and the suite must stay green.
- RDD off (global, user decision) — ordinary checks; parent runs risk assess for the record (repo precedent).
- Artifacts in English; frontends never touch credentials or the DB directly (CLI only).
- Delivery: `single-pr` + `size:exception` (precedent); work-unit commits on the branch; push/PR is the user's call.
- The app never implements OAuth or token refresh itself: sign-in and refresh stay OpenCode's job (prior decision upheld).

## Progress log

- 2026-10-11 — T1 done: recon recovered + completed (live-verified switch args, 30d TTL, DB state, injection points); options A/B presented; user approved option A including the `activate-in-opencode` bonus. Branch created.
- 2026-10-11 — T2 done (delegated writer, two work-unit commits `12f9fec` + `4f5afae`): registry v3 + pinned credentials + resolve-by-id + `discover` + `activate-in-opencode`; suite 326 → 384.
- 2026-10-11 — T2 verification: independent verifier `verified` (57/57 probes; nits only); assess `unassessable/high` (runtime ineligible; RDD off) → verifier path per the delegated gate; nit correction round `c7cdb92` (load-time invariants, null tolerance, `opencode` timeout) → suite 390 green; parent spot check green.
