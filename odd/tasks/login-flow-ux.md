# Feature: login-flow-ux — third field-report round (Cinnamon: guided login + dialog UX)

**Status**: T1–T6 done — independent verifier: PASS WITH FINDINGS (2 MINOR + 4 NIT), all actionable ones fixed (`a6e19b1`, `c11cc47`) and re-checked live. T7 in progress — PR #5 open (CI watch), merge pending.
**Handoff**: execution continues in this session; the full cycle is pre-authorized through **merge to main** (the user tests on Mint afterwards).
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

### Verified API contract (execution session, 2026-10-13)

Sources: Cinnamon `5.4-maintenance` (GitHub) vs local 6.4.13; Mint-Y `master.mint21` (2.1.6); GNOME Terminal 3.44 docs.

- **5.4 ModalDialog**: `close()` (modalDialog.js:319-337) only fades/hides (`Tweener` onComplete → `_group.hide()`); nothing ever destroys it. `destroy()` (:135-137) = `this._group.destroy()`; `'destroy'` is emitted by `_onGroupDestroy` (:261-263) when the group is destroyed. `destroy()` right after `close()` is SAFE — Cinnamon's Tweener auto-removes tweens of destroyed actors (js/ui/tweener.js:216-218, 263-266). No `destroyOnClose`, no `_closing`.
- **6.4 ModalDialog**: `destroyOnClose` defaults `true` (:76-80), stored as private `this._destroyOnClose` (:85); `close()` (:252-273) pops the modal, fade onComplete → `'closed'` → `destroy()`. A second `destroy()` after the auto-destroy is NOT safe (re-emits DESTROY).
- **RadioButtonGroup**: byte-identical 5.4/6.4; options live in the private `_buttons` list as `{id, button}` (radioButton.js:145-158); no removeButton / per-option API; `setActive` emits `'radio-changed'` only when the id changes (:186-189).
- **Util**: `spawn()` returns a pid when the binary is found, `undefined` when missing (throws → `_handleSpawnError`); child stdout/stderr → /dev/null. `spawnCommandLineAsyncIO` supports `opts.argv` AND stdin `opts.input` on BOTH 5.4 and 6.4 (util.js 5.4:222-234 / 6.4:229-241) — the API-key stdin path is 5.4-safe.
- **St.Clipboard** works on 5.4: `St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text)` (string required, no length arg).
- **Theme/styling**: Mint-Y-Dark scopes its dialog-button chrome to `.modal-dialog-button-box .modal-dialog-button`, so a button placed in dialog CONTENT matches nothing (the field bug); 5.4 stock styles an unscoped `.modal-dialog-button`; 6.4 renamed to `.dialog .dialog-button` (content buttons DO match). Xlet `stylesheet.css` loads on both versions but the theme wins equal-specificity ties → overrides need a second class (specificity ≥ (0,2,0)).
- **Terminals (Mint 21)**: default gnome-terminal 3.44 — `-e` accepted but deprecated; Debian `gnome-terminal.wrapper` translates `-e args` → `--wait -- args`; known silent no-window failure mode = D-Bus activation env; exit status untrustworthy. `x-terminal-emulator -e sh script` is the portable Debian form; mate `-x`, xfce4 `-x`, konsole/xterm `-e`.

## Decisions

- Cinnamon-first (report platform); GNOME parity remains a documented follow-up.
- **Reopen fix**: version-independent dismiss path — clear `this._accountsDialog` whenever we close (keep the guarded 'destroy' handler as backstop). No reliance on 'destroy' or 'closed' for cleanup on 5.4. Shared `_closeAccountsDialog(dialog)` used by every close path: clears the ref, runs per-dialog cleanups (`dialog._ocgoCleanups`), calls `close()`, and — when `dialog._destroyOnClose !== true` (5.4) and the dialog was not already destroyed — calls `destroy()` explicitly (5.4's close never destroys; without this the hidden actor leaks on every cycle).
- **No-credentials state → guided single path**: the "OpenCode login" radio is disabled (insensitive) with explanation whenever no concrete credential can be bound (`choices.some(c => c.credentialId !== null)` false); reaching the option actor goes through the guarded private `_buttons` shape. Plain-language copy; "Account id" prefilled (`work` / first free `work-N`) and explained ("just a name for you").
- **Login launch**: keep the official `opencode auth login` terminal flow; terminal candidates in order x-terminal-emulator → gnome-terminal → mate-terminal → xfce4-terminal → konsole → xterm (each with `sh <script>`); the command is ALWAYS copied to the clipboard on click; failure → explicit status, never silence; after launch, poll `account discover` every 4 s (≤5 min) and update the open dialog in place when the login lands.
- One status surface; no duplicated messages.
- **"Make active in OpenCode…"**: rename to plain language ("Use the selected login in OpenCode…" / "Use in OpenCode"), self-explanatory explainer; behavior unchanged.
- **Styling**: helper rows carry `modal-dialog-button-box ocgo-helper-buttons`; new `cinnamon/stylesheet.css` (xlet stylesheet) overrides the box chrome with a double class to beat the theme; buttons keep the theme's own chrome through the ancestor class.
- Styling pass driven by the field capture + live repro on the 6.4 harness; 5.4 theme behavior verified by sources (Mint-Y scoping above).

## Tasks

- [x] **T1 — Recon** *(route: parent + source analysis)*: field reports folded; reopen RC confirmed (5.4 vs 6.4 sources); login-button API checks done (spawn/chmod/file_set_contents). Execution session re-verified the full contract above.
- [x] **T2 — Dialog reliability + simplification** *(route: delegated writer)*: DONE 2026-10-13, commits `6357c5a` + `c5dcce9`. Shared `_closeAccountsDialog` (ref clear + per-dialog cleanups + 5.4 explicit destroy) on every close path; guided radio state (login option disabled when nothing bindable); id prefilled (`work`/`work-N`) + hint; single status surface. Live 6.4: 3 open/close cycles ref-clean with no uiGroup accumulation; real Cancel-button path verified; reopen after Cancel verified (`t6-no-creds.png`).
- [x] **T3 — Login launch robustness + auto-detect** *(route: delegated writer, same session)*: DONE, commit `cb3169c`. Script with resolved/quoted opencode path; 6 terminal candidates; clipboard always; never-silent statuses; 4 s × 75 poll with serial guard. Live: terminal window opened on the nested display; an injected credential was detected in ~4 s and the dialog updated in place (`t6-login-terminal.png`, `t6-login-detected.png`); full guided add completed (account `work` pinned to the test credential in the sandbox registry).
- [x] **T4 — "Make active in OpenCode…" clarity** *(same session)*: DONE, commit `4d56f3b`. "Use in OpenCode" across schema/popup/dialog copy; explainer reworded; behavior unchanged. GNOME copy parity remains the documented follow-up.
- [x] **T5 — Styling pass** *(same session)*: DONE, commit `d361413`. `cinnamon/stylesheet.css` (box-chrome override via second class) + `modal-dialog-button-box ocgo-helper-buttons` on the helper row and the credential row; the Mint-Y scoping mechanism is documented in the stylesheet comment. 6.4 live: buttons/combo carry visible chrome.
- [x] **T6 — Verification** *(route: parent + independent verifier)*: DONE 2026-10-13. Gates green (`make test` 422, `make check-cinnamon`, `make check-gnome`, `node --check`, schema). Live 6.4: reopen cycles, guided state, login launch, 4 s auto-detect, guided add, refresh-selection fix. 5.4 behavior source-verified (contract above). Independent verifier (fresh read-only session, `d820325..HEAD`): PASS WITH FINDINGS — keyboard activation of the disabled type (`can_focus` fix), refresh leaving a dead-end selection (selection move + `_hasBindableLogin`), stale helper text after error→empty refresh, `/tmp` script symlink risk (runtime dir), ignored `open()` result (destroy on `false`); all fixed in `a6e19b1` + `c11cc47`; GNOME copy parity stays the documented follow-up.
- [ ] **T7 — Delivery** *(route: parent; branch-pr)*: PR (single) + user retest on Mint.

## Acceptance criteria

- Closing and reopening the accounts dialog works repeatedly on both 5.4 (source-verified fix) and 6.4 (live).
- With no OpenCode login: the dialog explains in plain words; only guided paths are offered (login or API key); "Add account" cannot dead-end on the login type; no duplicated error text; "Account id" is prefilled and explained.
- Pressing the login button can never silently no-op: a terminal opens, or a copyable command + next steps appear; after login completes, the dialog detects the new credential by itself.
- The dialog renders presentably under the 5.4 theme; "Make active in OpenCode…" explains itself.
- Gates green.

## Forecast

≈ 300–500 authored lines (applet.js + schema + stylesheet). Single PR (repo precedent; size exception if needed).

## Progress log

- 2026-10-13 — Field report 3 triaged; doc seeded; recon of the dialog code + `opencode auth login` TUI.
- 2026-10-13 — Field report 3b folded: reopen bug root-caused (5.4 `close()` ≠ destroy; 6.4 `destroyOnClose` default masks it); login-button silent failure analyzed (spawn/chmod/file_set_contents checks); tasks restructured to T1–T7.
- 2026-10-13 — Fresh execution session: full API contract re-verified against 5.4/6.4 sources (above); design frozen; T2–T5 delegated to one writer; harness rebuilt for the live pass; T6/T7 next.
- 2026-10-13 — T2–T5 closed by the writer (`6357c5a`, `c5dcce9`, `cb3169c`, `d361413`, `4d56f3b`; +379/−129 across applet.js, schema, stylesheet.css). Gates: `make test` 422 OK, `make check-cinnamon`, `node --check`, schema JSON. Writer smoke harness (46 checks, fake Cinnamon imports) green. Parent live pass on the 6.4 harness: reopen cycles ×3 ref-clean; guided no-credentials state; login terminal launched on the nested display; 4 s auto-detect updated the open dialog; guided add end-to-end. `review assess` over the range: high/unassessable (opencode runtime is not eligible for immutable receipt review; RDD off) → independent verifier launched for T6. Next: verifier verdict → T7 PR + merge.
- 2026-10-13 — T6 closed: independent verifier PASS WITH FINDINGS; fixes `a6e19b1` (keyboard/refresh paths into the disabled login type; helper-text refresh) + `c11cc47` (runtime-dir script path; `open() === false` destroys the never-opened dialog) re-checked live (refresh moves the selection to API key; script lands in the runtime dir). Gates green after the fixes. The writer smoke harness is stale vs the corrected code (fake env lacks the new APIs: `get_user_runtime_dir`, `has_key_focus`); the live pass + gates carry the evidence. Next: T7 PR + merge.

---

Locator: odd/tasks/login-flow-ux.md (repo: opencode-go-meter)
