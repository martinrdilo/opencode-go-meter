# Feature: login-flow-ux — third field-report round (Cinnamon: guided login + dialog UX)

**Status**: In progress — field reports 3 + 3b triaged. **Two functional bugs confirmed**: (1) accounts dialog cannot reopen after close on Cinnamon 5.4 (root cause confirmed in Cinnamon sources); (2) "Log in with OpenCode…" silently no-ops on the field machine (cause under isolation; robust relaunch + fallbacks planned). T1 mostly done (code/version analysis); harness re-run pending; T2–T7 next.
**Handoff**: execution continues in a **fresh session**; the full cycle is pre-authorized through **merge to main** (the user tests on Mint afterwards). The nested test harness is down — rebuild per `odd/tasks/cinnamon-applet.md` (section "Nested test harness").
**Repo**: `opencode-go-meter`
**Branch**: `fix/login-flow-ux` (from `main` @ `0eadac1`)
**Created**: 2026-10-13

## Objective

Third field report (same Mint/Cinnamon user, right after PR #4 merged) — the account dialog/login flow is still confusing and partly broken:

1. The dialog opened by "Add / replace key…" reads as "horrible" and, on the field machine, **cannot be reopened after closing**.
2. The login affordance is opaque: "Log in with OpenCode…" opens nothing on the field machine; the user expected the browser login directly; "Account ID" is unexplained; the no-credentials state ends in a designed dead-end.
3. "Make a pinned OpenCode login active in OpenCode…" is still not understood.
4. User verdict: "no se arreglaron bien los problemas de antes"; asks for something simple.

## Evidence

### Field report 3 (2026-10-13)

- Screenshot (real Cinnamon desktop, dark theme): Add-account dialog, no-credentials state —
  helper "No OpenCode login found on this machine." + `[Log in with OpenCode…]` `[Refresh]`;
  jargon description ("Registers an OpenCode login. Pick the auto binding…"); Type "OpenCode login" selected / "API key";
  Credential "Auto (follows the active account)"; red status duplicating the no-login message; `[Cancel]` `[Add account]`.
- User narrative: login button → "no pasa nada / no se ve nada"; dialog can't reopen a second time;
  "Account ID: no sé qué poner"; the red error reproduced; "tengo OpenCode configurado, ¿por qué no anda?".

### Field report 3b — functional bugs (2026-10-13, follow-up)

- **"Log in with OpenCode…" does nothing** on the field machine: no terminal, no visible outcome.
- **Dialog cannot reopen**: first open OK; after closing, pressing "Add / replace key…" (or remove/activate) opens nothing until applet reload.
- Dead-end confirmed: any id + "OpenCode login" + "Add account" → red "No OpenCode login found on this machine — use "Log in with OpenCode…" or switch the type to API key."

### Root-cause analysis (verified against Cinnamon sources)

- **Reopen bug — CONFIRMED (5.4-specific)**: Cinnamon 5.4 `ModalDialog.close()` (js/ui/modalDialog.js:319-334) only fades/hides — **never destroys, never emits 'destroy'**; `_onGroupDestroy` is the only 'destroy' emitter. The applet clears `this._accountsDialog` ONLY from the dialog's 'destroy' handler, so the `if (this._accountsDialog) return;` guards (add/remove/activate) block every later open until reload. On 6.4, `destroyOnClose` defaults to `true` (modalDialog.js:79; close() destroys at 252-270) → the bug is masked in our 6.4 harness.
- **Login button no-op — cause under isolation**: `Util.spawn` exists on 5.4 (js/misc/util.js:94, same implementation family as 6.4); `GLib.file_set_contents` 2-arg appears visible in GJS 1.72's arg-cache (verifier's partial analysis; unfinished); `GLib.chmod` works against GLib 2.88 locally; GLib 2.72 typelib check inconclusive (package fetch 404). Field-visible failure modes remaining: terminal invocation silently dying (`x-terminal-emulator -e <script>`; spawn "succeeds" and returns a pid, no window; stderr → /dev/null) or an API throw whose only trace is the easily-missed status line. → Fix must be robust regardless: multi-terminal fallback, unmissable feedback + copyable command, login auto-detection.
- `opencode auth login` TUI (local v2.0.18): "Connect an integration / Select integration / Search:"; methods for opencode: "OpenCode Console account" (browser) / "API key (service account)". Strings "Log in with my account" / "Log out" do not exist in the repo, opencode v2.0.18, desktop CLI 2.0.27 or app.asar.

## Decisions

- Cinnamon-first (report platform); GNOME parity remains a documented follow-up.
- **Reopen fix**: version-independent dismiss path — clear `this._accountsDialog` whenever we close (keep the guarded 'destroy' handler as backstop). No reliance on 'destroy' or 'closed' for cleanup on 5.4.
- **No-credentials state → guided single path**: no dead-end offering (login type/combo hidden or disabled with explanation when nothing can be bound); plain-language copy; "Account id" prefilled and explained ("just a name for you").
- **Login launch**: keep the official `opencode auth login` terminal flow; add fallback terminal candidates; failure → copyable command (St.Clipboard) — silence is unacceptable; after launch, poll `account discover` and update the open dialog in place when the login lands.
- One status surface; no duplicated messages.
- "Make active in OpenCode…": self-explanatory label/description + plain-language explainer; behavior unchanged.
- Styling pass driven by the field capture + live repro on the 5.4 theme.

## Tasks

- [x] **T1 — Recon** *(route: parent + source analysis; harness re-run pending)*: field reports folded; reopen RC confirmed (5.4 vs 6.4 sources); login-button API checks done (spawn/chmod/file_set_contents). Pending: harness re-run on the current build (live before/after capture).
- [ ] **T2 — Dialog reliability + simplification** *(route: delegated writer)*: reopen fix (dismiss helper clearing the ref on every close path); remove the dead-end offering; guided no-credentials state (login or API key); "Account id" prefilled + explained; single status surface. Surface: `cinnamon/applet.js`.
- [ ] **T3 — Login launch robustness + auto-detect** *(route: delegated writer, same session)*: robust terminal launch (fallback candidates, unmissable feedback, copy-command fallback); poll `account discover` after launch; in-place update when detected. Surface: `cinnamon/applet.js`.
- [ ] **T4 — "Make active in OpenCode…" clarity** *(same session)*: label + schema description + explainer copy. Surfaces: `cinnamon/applet.js`, `cinnamon/settings-schema.json`.
- [ ] **T5 — Styling pass** *(same session)*: 5.4 look from the field screenshot + repro; helper buttons must read as buttons.
- [ ] **T6 — Verification** *(route: parent + independent verifier)*: gates; live 6.4 passes; fix notes for 5.4 (source-verified where live isn't possible); verifier over the range.
- [ ] **T7 — Delivery** *(route: parent; branch-pr)*: PR (single) + user retest on Mint.

## Acceptance criteria

- Closing and reopening the accounts dialog works repeatedly on both 5.4 (source-verified fix) and 6.4 (live).
- With no OpenCode login: the dialog explains in plain words; only guided paths are offered (login or API key); "Add account" cannot dead-end on the login type; no duplicated error text; "Account id" is prefilled and explained.
- Pressing the login button can never silently no-op: a terminal opens, or a copyable command + next steps appear; after login completes, the dialog detects the new credential by itself.
- The dialog renders presentably under the 5.4 theme; "Make active in OpenCode…" explains itself.
- Gates green.

## Forecast

≈ 300–500 authored lines (applet.js + schema). Single PR (repo precedent; size exception if needed).

## Progress log

- 2026-10-13 — Field report 3 triaged; doc seeded; recon of the dialog code + `opencode auth login` TUI.
- 2026-10-13 — Field report 3b folded: reopen bug root-caused (5.4 `close()` ≠ destroy; 6.4 `destroyOnClose` default masks it); login-button silent failure analyzed (spawn/chmod/file_set_contents checks); tasks restructured to T1–T7.

---

Locator: odd/tasks/login-flow-ux.md (repo: opencode-go-meter)
