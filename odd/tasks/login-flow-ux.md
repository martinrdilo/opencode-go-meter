# Feature: login-flow-ux — third field-report round (Cinnamon: guided login + dialog UX)

**Status**: In progress — field report 3 triaged; T1 (live recon) next
**Repo**: `opencode-go-meter`
**Branch**: `fix/login-flow-ux` (from `main` @ `0eadac1`)
**Created**: 2026-10-13

## Objective

Third field report (same Mint/Cinnamon user, right after PR #4 merged into main):

1. The dialog opened by "Add / replace key…" still reads as **"horrible"** to the user.
2. The login affordance is opaque: pressing **"Log in with OpenCode…"** opens a terminal TUI ("Connect an integration" / "Select integration" / "Search:") that the user did not understand ("no sé qué tengo que poner ahí"); they expected the **browser login** to start directly. After the attempt, the dialog said "No OpenCode login found on this machine".
3. The "OpenCode login" type + "Auto (follows the active account)" combo are a **designed dead-end** when no credentials exist: the first submit fails and the red message duplicates the helper text.
4. **"Make a pinned OpenCode login active in OpenCode…"** is still not understood ("no entiendo para qué está esa opción").
5. User verdict: "Creo que no se arreglaron bien los problemas de antes."

## Evidence (2026-10-13, field + code)

- **Field screenshot** (real Cinnamon desktop, dark theme): Add-account dialog, no-credentials state —
  helper "No OpenCode login found on this machine." + `[Log in with OpenCode…]` `[Refresh]`;
  description "Registers an OpenCode login. Pick the auto binding (follows the active OpenCode credential) or a discovered credential.";
  Type: **OpenCode login** selected / API key; Credential: "Auto (follows the active account)";
  red status duplicating the no-login message; `[Cancel]` `[Add account]`.
- **Code anchors** (`cinnamon/applet.js` @ `0eadac1`):
  - helper block `1025-1109` region: `on_accounts_apply` helper `1100-1184`; login button → `ocgo-opencode-login.sh` + `x-terminal-emulator -e` `1128-1143`; Refresh in-place reload `1147-1180`.
  - type chooser `1194-1203` — defaults to API key with no credentials; combo `1215-1252` — offers "Auto (follows the active account)" with nothing to follow.
  - `_failureMessage` `1545-1553` — duplicates the helper sentence.
  - `_openActivateExplainer` `1451-1471`; `settings-schema.json` `55-57` (activate button copy).
- **`opencode auth login` TUI** (verified locally, v2.0.18): opens "Connect an integration / Select integration / Search:"; methods for opencode (from binary strings): "OpenCode Console account" (browser flow) / "API key (service account)". The applet's script runs bare `opencode auth login`.
- **Not found anywhere**: the strings "Log in with my account" / "Log out" (repo tracked files, opencode v2.0.18, desktop CLI 2.0.27, desktop app.asar). Origin to be located with the user (terminal picker? browser page? their opencode version?).

## Decisions (draft)

- Cinnamon-first (report platform); GNOME parity remains a documented follow-up.
- Direction: when no login exists, offer a **guided single-path flow** — "Log in with OpenCode…" (explained in plain words) or API key; remove the dead-end type/combo offering for that state.
- **Auto-detect the login**: after the terminal/browser step, poll `account discover` and update the open dialog in place (keep the round-2 in-place pattern; no destroy-recreate).
- One status surface: no duplicated "no login found" messaging.
- Keep the terminal as the login vehicle (official `opencode auth login`), with the visible-command fallback; explain it in-place.
- "Make active in OpenCode…": self-explanatory label/description + plain-language explainer; behavior unchanged.
- Styling pass driven by a live repro of the field state (6.4 + 5.4 theme).

## Tasks

- [ ] **T1 — Live recon** *(route: parent + per-action harness)*: reproduce the no-credentials dialog on the 6.4 harness + the 5.4 theme; capture screenshots vs the field capture; verify what pressing "Log in with OpenCode…" does in the scratch (terminal spawn) and what a 5.4 user sees.
- [ ] **T2 — Dialog redesign (no-credentials state)** *(route: delegated writer — applet.js redesign + JS checks)*: guided login block (plain copy, steps), no dead-end offering, single status line, auto-detect polling with in-place update; friendly failure copy. Surface: `cinnamon/applet.js`.
- [ ] **T3 — "Make active in OpenCode…" clarity** *(route: delegated writer — same session as T2)*: label + schema description + explainer copy. Surfaces: `cinnamon/applet.js`, `cinnamon/settings-schema.json`.
- [ ] **T4 — Styling pass on 5.4** *(route: same writer session; uses T1 evidence)*.
- [ ] **T5 — Verification** *(route: parent + independent verifier per delegated gate)*: gates (`make test`, `make check-cinnamon`, `node --check`), live passes (empty + login + 5.4 theme), verifier over the range.
- [ ] **T6 — Delivery** *(route: parent; branch-pr)*: PR (single; repo precedent) + user retest on Mint.

## Acceptance criteria

- No OpenCode login on the machine → the dialog explains in plain words; the only offered paths are "Log in with OpenCode…" (explained) and API key; "Add account" cannot dead-end on the login type; no duplicated error text.
- After the terminal/browser login completes, the dialog detects the new credential by itself and updates (credential selectable without pressing Refresh).
- The dialog renders presentably under the 5.4 theme (screenshots) and is unchanged-or-better on 6.4.
- "Make active in OpenCode…" explains itself where it lives; no behavior change.
- Gates green.

## Forecast

≈ 250–450 authored lines, applet.js-focused (+ schema small). Single PR (repo precedent; size exception if needed).

## Progress log

- 2026-10-13 — Field report 3 triaged (screenshot + repro notes); recon of the current dialog code + `opencode auth login` TUI; this doc seeded.

---

Locator: odd/tasks/login-flow-ux.md (repo: opencode-go-meter)
