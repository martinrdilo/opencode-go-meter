# Feature: login-detection — sixth field-report round (accept the OpenCode Go integration and every credential shape OpenCode v2 writes)

**Status**: IN PROGRESS — T1/T2 done (`322017b`); T3 verification pending.
**Repo**: `opencode-go-meter`
**Branch**: `fix/login-detection` (worktree `opencode-go-meter-worktrees/login-detection`, from `main` @ `b48b8b2`)
**Created**: 2026-10-16

> Coordination note: the primary checkout sits on `feat/accounts-window`
> (`3a9e15e`) and is used by parallel sessions; this round works only in the
> dedicated worktree and keeps its commits path-scoped.

## Objective

Field report 6 (same Mint/Cinnamon field machine, 2026-10-16):

- The login terminal now opens (PR #8 behaviour confirmed on the field machine).
- OpenCode itself reports the account connected ("OpenCode Go (connected)" in
  the `opencode auth login` integration picker).
- The applet still says "No OpenCode login found on this machine." and the
  Refresh button still answers "No new credentials found yet."

The meter must detect the login the user actually has, and only ask for a
login when the store really holds none.

## Problem

`core/ocgo/creds.py` matches exactly one integration id — `integration_id =
'opencode'` in `opencode.db` and the `"opencode"` key in the legacy
`auth.json`. Current OpenCode v2 ships more than one OpenCode-owned
integration (`opencode-go` ranks above `opencode` inside OpenCode itself),
stores credential entities whose token may sit behind a `value` wrapper or in
an API-key field, and the field machine is the first environment where none of
the currently accepted rows exist. Every one of those cases reads as "no
login found" while OpenCode itself is logged in.

## Evidence

### Dev-box recon (2026-10-16, `main` @ `b48b8b2`)

- Store truth: `~/.local/share/opencode/opencode.db` holds one active
  `integration_id='opencode'` credential (label `Default`, email
  `martinrdilorenzo@gmail.com`, expiry 2026-10-27). No `auth.json` exists.
- `ocgo account discover --json` → `schema: 1`, one credential,
  `store.has_login: true`; `ocgo auth show` resolves it; `ocgo status` fetches
  live usage (rolling/weekly/monthly + credits).
- The Cinnamon sandbox applet (`/tmp/opencode/cinnamon-test`, applet symlinked
  to the repo) reports `_storeHasLogin() === true` and one discovered
  credential against the same store.
- `opencode auth list` (local CLI 2.0.18) prints `OpenCode Console / Default /
  stored`; the running services are the desktop app CLI (2.0.29) and a dev
  server from `/home/martin/workspace/opencode` (`serve --service`, port 3084).
- OpenCode's own ordering maps rank `opencode-go` before `opencode`
  (binary strings, 2.0.18 + 2.0.29).

### Still open

- The field machine's store dump (`ocgo account discover --json` + the
  standalone diagnostic one-liner) — needed for a final verdict on that box.

## Scope

In: `core/ocgo/creds.py` (detection), its tests, the decision record, and any
doc surface that names the accepted integration ids.

Out: frontend changes (both frontends consume the CLI payload unchanged), new
CLI commands, contract version bumps.

## Constraints

- Core stays Python 3 standard library only; tokens never printed, logged, or
  cached.
- `store_status()` keeps its six documented fields and their exact types
  (the frontends parse them strictly); no new payload keys.
- Test-first: new tests must fail against the current reader (RED) before the
  implementation lands (GREEN).
- Crash-safe on hostile input: malformed rows/files still read as "no login".

## Tasks

- [x] **T1 — core: accept the OpenCode-owned integration ids and every
  credential shape OpenCode v2 writes.** `core/ocgo/creds.py`:
  - accepted ids: `opencode-go`, `opencode`, plus any other id starting with
    `opencode` (lowest priority); preference order for selection and listing:
    exact `opencode-go` → exact `opencode` → remaining `opencode*` (newest
    `time_updated` first inside a tier, active rows before inactive ones).
  - credential value: token from `access` (oauth) or `key` (api key); descend
    once into a `value` wrapper when present; `type` optional; `expires`
    honoured when present and sane.
  - legacy `auth.json`: same id set (key trailing `/` tolerated), same
    preference order, same tolerant shape.
  - `has_stored_login()`, `list_db_credentials()`, `resolve_credential()`,
    `_metadata_strings()` follow the same rules.
  - Route: delegated writer (writer trigger: 2 non-trivial files).
  - Done 2026-10-16, commit `322017b`: RED first (`Ran 97 tests, failures=6,
    errors=12` — the 18 new tests, all pre-existing green), then GREEN
    (`Ran 97 tests — OK`); full suite `Ran 478 tests — OK`.
- [x] **T2 — docs**: record the decision as D12 in
  `docs/05-technical-decisions.md` (template at the file's tail) and align any
  doc surface that names the accepted integration ids / store shapes
  (`docs/02-cli-reference.md`, `README.md` when it states the login rule).
  - Done 2026-10-16, commit `322017b`: D12 recorded; the CLI reference's
    `account discover` section now names the accepted ids and their order.
    README needed no edit — it names neither integration ids nor shapes.
- [ ] **T3 — verify**: `make test`, `make check-gnome`, `make check-cinnamon`;
  real-store re-check on the dev box (`ocgo account discover --json`,
  `ocgo auth show`, `ocgo status`); sandbox applet still reports a login; hand
  the field machine its diagnostic one-liner.

## Acceptance criteria

- All three checks green; new tests cover: a DB row under `opencode-go`, both
  ids present (Go wins), a nested `value` wrapper, an API-key row, a legacy
  `auth.json` keyed `opencode-go`, and precedence inside the legacy file.
- Dev-box behaviour unchanged: one credential discovered, live usage still
  fetched, applet still detects the login.
- Field-machine story is actionable: either the same CLI detects the login
  after updating, or the diagnostic output names exactly why not.

## Checks

- `make test` (unittest, `core/tests/`)
- `make check-gnome`, `make check-cinnamon`
- `cd core && python3 -c "from ocgo import creds; import json;
  print(json.dumps(creds.store_status(), indent=2))"`
- `ocgo account discover --json`, `ocgo status --no-color`

## Delivery forecast

- Authored lines: ~250 (core ~60, tests ~150, docs ~40) — under the 400-line
  work-unit budget; one branch, one work unit, no chained PR needed.
- Delivery strategy: `ask-on-risk` (no slicing triggered).

## Progress

- 2026-10-16 — feature doc created; dev-box recon recorded; T1/T2 delegated to
  a bounded writer; T3 to the parent.
- 2026-10-16 — T1/T2 implemented test-first by the delegated writer, commit
  `322017b` (4 files, +421/−63): accepted-id preference (`opencode-go` →
  `opencode` → other `opencode*`), tolerant values (one `value` wrapper,
  `access`/`key`, optional `type`), legacy `auth.json` parity; D12 recorded;
  `store_status()` untouched. Full suite + both frontend checks green;
  dev-box real-store re-check OK (one credential, live usage fetched).

## Verification evidence

- `PYTHONPATH=tests python3 -m unittest tests.test_creds -v` — RED before the
  implementation: `Ran 97 tests ... FAILED (failures=6, errors=12)` with the
  18 new tests failing and every pre-existing test green; GREEN after:
  `Ran 97 tests ... OK`.
- `make test` — `Ran 478 tests ... OK`.
- `make check-gnome` — `ok: no method/property collisions in extension.js`.
- `make check-cinnamon` — `ok: cinnamon applet checks passed
  (opencode-go-meter@martinrdilo)`.
- `creds.store_status()` one-liner — the six documented fields,
  `has_login: true`, `db_exists: true`, `auth_json_exists: false`.
- `ocgo account discover --json` — one credential (label `Default`, active,
  email) and `store.has_login: true`.
- `ocgo status --no-color` — `Rolling 1% · Weekly 28% · Monthly 18% ·
  Credits $2.59`; `ocgo refresh` — `Refreshed OpenCode Go (default): rolling
  1% · weekly 28% · monthly 18% · $2.59`.

## Next step

- Review of the writer's diff, then T3 checks, then the field-machine
  diagnostic to the user.
