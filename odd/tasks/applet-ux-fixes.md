# Feature: applet-ux-fixes — second report round (Cinnamon)

**Status**: In progress — T1 recon done; T2–T7 pending
**Repo**: `opencode-go-meter`
**Branch**: `fix/applet-ux-fixes` (from `main` @ `2829e25`)
**Created**: 2026-10-13

## Objective

Fix the four issues of the second field report (Mint 21 / Cinnamon 5.4.13):

1. The add-account flow confuses and dead-ends for a login-less user — and the
   user expected a **browser login affordance** ("un link para loguearme con el
   navegador").
2. The account dialog looks bad on 5.4 ("horrible, muy fea").
3. **Cinnamon hard-crashed** ("fallback mode" dialog) when the applet was
   removed from the panel.
4. The "Make active in OpenCode…" settings button is unexplained and silently
   no-ops when not applicable.

## Evidence (recon, 2026-10-13)

### 1. Add flow
- `on_accounts_apply` defaults the Type chooser to `KIND_OPENCODE_DB` whenever
  the login option exists (`allowLogin`), even with **zero discovered
  credentials** → typing any id runs `account add <id> --from-db` → always
  fails with the raw CLI message. Stderr is surfaced verbatim in the dialog.
- `opencode auth login` **is** the browser flow (CLI help: methods/answers,
  opens the browser); `x-terminal-emulator` exists on Mint.

### 2. Dialog styling
- The 5.4 theme has **no** `message-dialog-*` classes (the module and its
  styles are 6.4+); the local `MessageContent` + `_labeledRow` layout has no
  spacing and no title style there. 5.4's theme **does** style
  `.confirm-dialog-title` (standalone: bold 1.5em, centered, padding-bottom
  12px) and `.run-dialog-description` (+ `.error`) — both also exist in 6.4.

### 3. The removal crash — a REAL process crash
- `removeAppletFromPanels` is byte-identical 5.4↔6.4 and wraps the xlet
  callback in try/catch; JS exceptions are logged, never fatal.
- The "Cinnamon just crashed / running in fallback mode" dialog comes from
  `cinnamon-launcher` (strings match, `confirm_restart()`), i.e. the
  **cinnamon process exited abnormally** during/after the removal.
- Local 6.4 repro (real path: dconf `enabled-applets` change) is clean.
- Need the user's `~/.xsession-errors`, `~/.cinnamon/glass.log`,
  `~/.cinnamon/restarts.log` (+ `coredumpctl list` if present) to pin the
  stack. Defensive hardening proceeds regardless (see T2).

### 4. Make active in OpenCode
- `on_accounts_activate()` silently returns unless a pinned login is selected
  (`_isPinnedLogin`); the schema description is vague. With no accounts / an
  API-key account it looks broken.

## Decisions

- Cinnamon-first (report platform). GNOME parity for the add-flow affordances
  is a documented follow-up, not this round.
- **Login affordance (design)**: when `_credentials` is empty, the account
  dialog shows a helper block — "No OpenCode login found…" + a
  **"Log in with OpenCode…"** button (spawns a terminal running
  `opencode auth login`, the browser flow; script-in-tmp + `x-terminal-emulator
  -e <script>`; visible command fallback if the spawn fails) + a **"Refresh"**
  button (reload accounts/credentials and reopen the dialog). The Type chooser
  defaults to **API key** when no credentials exist, so the first impression is
  the path that works. Raw NO_CREDENTIAL stderr is mapped to a friendly line.
- **Restyle**: title gets `confirm-dialog-title` (5.4-styled; harmless on 6.4
  where `message-dialog-title` still applies), description gets
  `run-dialog-description`, failure status gets `run-dialog-description error`,
  `contentLayout.spacing = 6` in `_openAccountsDialog()`, and the credential
  combo button picks the class that renders well on both themes
  (`.modal-dialog-button` exists on both; `.dialog-button` only on 6.4 themes —
  verify visually).
- **Hardening (not claimed as the fix until logs arrive)**: wrap the whole
  `on_applet_removed_from_panel` in try/catch (log, never propagate); destroy
  the dialog's `PopupMenuManager` **only if supported** (5.4's class has no
  `destroy()` — feature-detect); keep the teardown conservative (no new API
  calls that 5.4 lacks).
- **Make active**: clicking it when inapplicable opens a short explainer dialog
  (what the action does + why it does not apply); applicable flow unchanged;
  schema description clarified.
- Verification: live nested Cinnamon 6.4 (empty + login scratches) with
  screenshots; **5.4-theme trick**: load `/tmp/opencode/c54/cinnamon.css` as a
  custom theme in the scratch to see what Mint 21 shows; independent verifier;
  user confirms on Mint.
- Delivery: single PR (#4); forecast ≈ 250–350 authored lines.
- RDD off → per-diff assess; artifacts English; conversation Spanish.

## Tasks

- [x] **T1 — Recon** *(route: parent)*. DONE 2026-10-13. Evidence + decisions
  above; branch seeded from `2829e25`.
- [ ] **T2 — Removal-crash hardening + log chase** *(route: writer (B) +
  parent)*. try/catch around the removal handler; feature-detected manager
  teardown; 6.4 removal repro in the harness stays clean. Root cause pending
  user logs (xsession-errors / glass.log / restarts.log).
- [ ] **T3 — Add-flow UX + login affordance** *(route: writer (A); surface:
  `cinnamon/applet.js`)*. Default type, helper block (login/refresh), friendly
  no-credential message.
- [ ] **T4 — Restyle the account dialogs** *(route: writer (A), same session;
  surface: `cinnamon/applet.js`)*. Dual-version classes + spacing + button
  class; screenshots under the normal and the 5.4 theme.
- [ ] **T5 — Make-active explainer** *(route: writer (B); surfaces:
  `cinnamon/applet.js`, `cinnamon/settings-schema.json`)*. Explainer dialog on
  inapplicable clicks + schema description.
- [ ] **T6 — Verification** *(route: parent + independent verifier)*. Gates,
  live passes (empty + login + 5.4-theme), verifier over the range.
- [ ] **T7 — PR #4** *(route: parent; branch-pr skill)*.

## Acceptance criteria

- Fresh login-less user: the dialog opens defaulted to **API key**, with a
  visible "Log in with OpenCode…" path; typing a bogus/any id with API key
  reaches the real validation; NO_CREDENTIAL failure reads as a friendly
  explanation, not raw stderr.
- The dialog renders presentably under the 5.4 theme (screenshot) and is
  unchanged-or-better on 6.4.
- Removal from the panel in the harness is clean (log) — Mint confirmation by
  the user after the report, with hardening in place.
- "Make active in OpenCode…" explains itself when inapplicable.
- Gates green (`make test`, `make check-cinnamon`, `node --check`).

## Forecast

≈ 250–350 authored lines (applet.js-focused; schema + docs small). Under the
400 budget → single PR.

## Progress log

- 2026-10-13 — T1: report triaged; launcher evidence for the real crash;
  5.4-theme class inventory; branch `fix/applet-ux-fixes` from `2829e25`.

---

Locator: odd/tasks/applet-ux-fixes.md (repo: opencode-go-meter)
