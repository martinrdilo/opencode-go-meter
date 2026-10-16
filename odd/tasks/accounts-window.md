# Feature: accounts-window — fifth field-report round (Cinnamon: keyring runtime fallback + a real account window + login detection copy)

**Status**: COMPLETE (code + live verification) — commits `1a53684` (keyring
fallback) + `57ef94a` (window + wiring) on `feat/accounts-window-v2`; delivery
(PR/merge) pending user decision.
**Repo**: `opencode-go-meter`
**Branch**: `feat/accounts-window-v2` (worktree `opencode-go-meter-worktrees/accounts-window`, from `main` @ `8f9fab5`)
**Created**: 2026-10-15

> Coordination note: a parallel session is committing to `main`-adjacent branches
> (`docs/reference-docs`, `chore/versioning-pack`) in the primary checkout and
> switched branches there while this round was in flight. This round moved to an
> isolated git worktree and keeps its commits path-scoped; the primary checkout
> was restored to that session's branch state.

## Objective

Field report 5 (same Mint/Cinnamon user; images captured 2026-10-15 right after the PR #8/#9 retest):

1. **API key → keyring dead-end.** The add-key submit still lands on the red
   "system keyring (libsecret-tools) is not installed" status (image 1). The
   user asks that dependencies be resolved at install time so nothing has to be
   installed by hand outside the app.
2. **The modal dialog blocks the desktop.** "Add / replace account key" is a
   Cinnamon `ModalDialog`: it grabs input and blocks every other window,
   including the login terminal the dialog itself opens ("se me abre por detrás
   una terminal... no puedo acceder"). The user wants a normal window (image 2).
3. **"Connected" vs "no login".** "Log in with OpenCode…" opens the OpenCode
   TUI; OpenCode itself reports connected; Refresh still answers "No new
   credentials found yet." and the dialog keeps claiming no login (images 3–5).
   The meter-side states are verified on the dev box; the field machine's store
   still needs `ocgo account discover --json` for a final verdict.

## Evidence

### Dev-box recon (2026-10-15, main @ 907199c)

- Store truth (dev box): `opencode.db` holds an active `integration_id='opencode'`
  credential since 2026-09-27; `ocgo status` resolves it; `ocgo account discover
  --json` reports `store.has_login: true` and one credential. No `auth.json` in
  `~/.local/share/opencode/`.
- The applet's three empty-store branches map exactly to CLI payloads (all
  verified with temp stores): missing/empty db → exit 0, `credentials: []`,
  `has_login: false` → "No OpenCode login found on this machine" helper +
  "No new credentials found yet."; corrupt db (no schema) → exit 1 → "Could not
  read the OpenCode credential store."
- **Keyring runtime failure reproduced** (nested/sandbox session, no Secret
  Service on the session bus): `secret-tool` resolves, `secret-tool store`
  **times out after 10 s**, CLI reports `secret-tool could not store the secret
  for account '<id>': ... timed out after 10 seconds`. The applet's fallback
  only matches `secret-tool is not available` (binary absent) → a runtime
  failure dead-ends on the raw error.
- **Modal is by construction**: `ModalDialog.open()` → `Main.pushModal` (global
  input grab). Empirical spikes on the nested `:19` session: (a) a chrome
  (non-modal) `St` actor receives neither clicks nor keyboard (input region
  excludes it); (b) a popped modal leaves the dialog inert (`_eventBlocker`).
  An in-shell non-modal dialog is not viable.
- **GTK window via `cjs` works**: `cjs` + Gtk3 on `:19` renders a normal
  decorated window (title bar, focus, movable) — `/tmp/opencode/cinnamon-test/
  gtk-window-shot.png`. `cjs` ships with Cinnamon; no new dependency.
- Repo state: `main` contains PRs #8/#9 + scaffolding rounds; RDD switch is off
  (global). A parallel docs round is in flight (dirty `AGENTS.md`/`README.md`/
  `docs/01-architecture.md`, untracked `docs/02-04`) — **do not touch those
  files**, and keep commits path-scoped.
- Nested harness: Xephyr `:19`, sandbox `HOME=/tmp/opencode/cinnamon-test/home`,
  `opencode.db` **hardlinked** to the real store (do NOT run a real
  `opencode auth login` in the harness), `eval.sh`/`shot.sh`, XTest input
  injection available (ctypes, libXtst — proven).

## Decisions (frozen contracts)

- **The Cinnamon add/replace flow becomes a real window**: new
  `cinnamon/accounts-window.js`, a standalone `cjs`+GTK3 process spawned by the
  applet (`argv: [cjs, <script>, --ocgo <path>]`). Normal WM window: movable,
  focusable, non-blocking; coexists with the terminal it opens.
- **The applet keeps the ModalDialog code only as a last-resort fallback**
  (script or `cjs` missing / spawn failed); the menu action prefers the window.
- **Behavioral parity**: the window ports the visible texts, the CLI
  commands/args/stdin discipline (secrets never in argv), the two-step keyring
  fallback, the login script + terminal candidates + clipboard fallback, the
  detection poll, the store-paths line, and the sanitizers
  (`stripToolToken`/`formatFailureDetail`/`shortenHomePath`/`truncate`) as
  deliberate mirrors with a keep-in-sync note (existing repo precedent).
- **Keyring fallback triggers on** `secret-tool is not available` (binary
  missing) **or** `secret-tool could not store the secret` (runtime failure:
  no keyring service, timeout). Two messages differentiate the causes; the
  offer stays a two-step explicit opt-in (`--store file` on the retry).
- **Install-time dependency resolution already exists**
  (`scripts/install-deps.sh`, run by `make install`/`make install-cinnamon`):
  it offers `sudo apt-get install libsecret-tools` on a tty. Wording aligned to
  reality ("the app offers a private local file", not a promise of automatic
  fallback).
- **Detection copy**: never claim "no login" when the store has one; a re-auth
  of an existing credential (same id) is not reported as "no new credentials".
- No new dependencies, no `sudo` from the applet, no secrets in argv/logs.

## Tasks

- [x] **T1 — Applet: keyring runtime fallback + message split** *(route: parent)*.
  DONE (worktree): `SECRET_TOOL_STORE_FAILED_MARKER` added; the offer now
  matches either marker and splits the message (binary missing vs runtime
  failure); `scripts/install-deps.sh` wording aligned. Checks:
  `node --check` + `bash -n` + `make check-cinnamon` green (pre-window-file).
- [x] **T2 — New `cinnamon/accounts-window.js` (cjs+GTK3)** *(route: delegated
  writer)*. DONE (commit `57ef94a`): 1332-line standalone window; port map in
  the file header; 20/21 copied helpers byte-identical to `applet.js` (one
  comment word differs); the writer's driven tests covered both keyring
  markers (message split + `--store file` retry with an identical stdin digest),
  the from-db submit (empty stdin), the login poll detection, the refresh
  messages, the login-script bytes (identical to the applet's) and the
  unresolved-binary / no-terminal branches; `node --check` + GTK smoke on `:19`
  green.
- [x] **T3 — Applet wiring + checks** *(route: parent)*. DONE (commit
  `57ef94a`): `on_accounts_apply` prefers `_openAccountsWindow()` (cjs + script
  next to applet.js at the installed location, no shell, accounts refreshed
  when the window exits) and falls back to the in-shell dialog when it cannot
  launch; `check_applet.py` now also `node --check`s `accounts-window.js` and
  forbids `imports.ui.*` there.
- [x] **T4 — Verification** *(route: parent; live `:19`)*. DONE — live evidence
  (nested Cinnamon on `feat/accounts-window-v2` code, applet settings →
  callback path):
  - The window opens from the applet as a separate `cjs` process and a normal
    decorated window ("Add account"), coexisting with the Cinnamon Settings
    window (no grab).
  - Real store: login radio enabled and preselected, credential combo shows
    `Default (martinrdilorenzo@gmail.com)`, helper hidden.
  - Fake-ocgo empty store: helper + "Log in with OpenCode…" + Refresh exactly
    as in the field report; Refresh answers "No new credentials found yet."
    after re-running `account list`/`discover` (verified in the fake's log).
  - **Terminal coexistence (the field complaint)**: the login button opened a
    terminal (ptyxis) while the window kept working — Refresh clicked WITH the
    terminal open triggered a new list/discover round. The old modal blocked
    this entirely.
  - Cancel closes the window; the process exits; no applet errors in the
    journal; the sandbox was restored (ocgo + applet symlinks, Cinnamon
    restarted, no stray processes).
  - Harness limitation recorded: synthetic XTest keystrokes do not reach X
    clients on this Xephyr (pointer needs `XSync` + slow double clicks and
    works); entry typing was therefore verified via the writer's programmatic
    driver, not synthetic keys.
- [x] **T5 — Docs** *(route: parent)*. This doc updated (commit below);
  README / `docs/03-frontends.md` notes wait for the parallel docs round to
  land first (deliberately untouched while that branch is in flight).

## Field-machine diagnostics to request from the user

- `ocgo account discover --json` on the Mint machine (full output), plus
  `ls -la ~/.local/share/opencode/` — needed to settle report item 3.
