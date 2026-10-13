# Feature: applet-ux-fixes — second report round (Cinnamon)

**Status**: Complete — T1–T7 done; PR #4 open (merge is the user's call).
T6 (independent verifier) was cancelled by the runtime; optional relaunch on
request. All gates and live passes are green.
**Repo**: `opencode-go-meter`
**Branch**: `fix/applet-ux-fixes` (from `main` @ `2829e25`; tracks `origin`)
**PR**: https://github.com/martinrdilo/opencode-go-meter/pull/4
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

## Evidence (recon + investigation, 2026-10-13)

### 1. Add flow
- `on_accounts_apply` defaulted the Type chooser to `KIND_OPENCODE_DB` whenever
  the login option existed, even with **zero discovered credentials** → any id
  ran `account add <id> --from-db` → the raw CLI message. `opencode auth login`
  is the browser flow; `x-terminal-emulator` exists on Mint.

### 2. Dialog styling
- The 5.4 theme has no `message-dialog-*` classes; it styles
  `.confirm-dialog-title` (bold 1.5em, centered) and `.run-dialog-description`
  (+ `.error`) — both also present in 6.4's theme.

### 3. The removal crash — a REAL process crash
- `removeAppletFromPanels` is byte-identical 5.4↔6.4 and try/catch'd; the
  "Cinnamon just crashed / fallback mode" dialog comes from
  `cinnamon-launcher`, i.e. the **cinnamon process exited abnormally**.
- **Investigation**: a SIGABRT core (`/tmp/opencode/apport-crash/`, cinnamon,
  `clutter-actor.c:6224: assertion failed: (priv->parent == NULL)`, re-entrant
  destroy during a dispose signal) was produced by a WRITER's intermediate
  build. The parent could **not** reproduce any abort on the final code in 10+
  variants, including the field pattern (dialog with credential items → open →
  close → destroy; removal with the dialog open; async destroys; repeated
  cycles). Conclusion: the captured core is attributed to the intermediate
  build; the **field crash root cause remains open pending the user's Mint 21
  logs** (`~/.xsession-errors`, `~/.cinnamon/glass.log`,
  `~/.cinnamon/restarts.log`). Defensive hardening ships regardless.

### 4. Make active in OpenCode
- `on_accounts_activate()` silently returned unless a pinned login was selected;
  the schema description was vague. (The popup submenu item is insensitive
  rather than silently no-opping — reported, left unchanged.)

## Decisions

- Cinnamon-first; GNOME parity is a documented follow-up.
- **Login affordance**: helper block in the add dialog whenever no credentials
  were discovered (missing DB included) — explainer + `Log in with OpenCode…`
  (writes `opencode auth login` to a tmp script, spawns
  `x-terminal-emulator -e <script>`, visible command fallback) + `Refresh`
  (re-reads accounts/credentials and updates the OPEN dialog in place).
  Type chooser defaults to **API key** when no credentials exist. The raw
  NO_CREDENTIAL stderr maps to a friendly line.
- **In-place Refresh**: a destroy-and-recreate cycle proved fragile during
  development (one abort captured on an intermediate build; root cause not
  settled), so the open dialog is reused instead of torn down. The code
  comments state exactly this, no stronger claim.
- **Restyle**: `confirm-dialog-title` + `run-dialog-description` (+ `.error`
  for failures via `_setStatus`), spacing via the Clutter layout manager
  (`St.BoxLayout` has no `spacing` property on either version), the credential
  combo carries both button classes and uses `St.Button.label` (a child
  `St.Label` rendered transparent on 6.4 — pre-existing bug, fixed).
- **Reload-safe module**: `MessageContent` is a factory, not a
  `GObject.registerClass` (re-import re-registered the type name and killed
  `ReloadXlet` — dev-loop bug since the 5.4 fix).
- **Make-active explainer**: inapplicable clicks open a short explainer dialog;
  the pinned flow is unchanged; schema description clarified.
- **Removal hardening**: the whole teardown is try/catch'd (defense in depth);
  the manager cleanup is feature-guarded (5.4's `PopupMenuManager` does have
  `destroy()` — writer-corrected note; the guard stays).
- Delivery: single PR (#4); actual 500 changed lines (applet.js + schema) →
  documented `size:exception` (repo precedent).
- RDD off → per-diff assess (round: medium). Artifacts English; conversation
  Spanish.

## Tasks

- [x] **T1 — Recon** *(route: parent)*. DONE 2026-10-13, commit `93e5197`.
- [x] **T2 — Removal-crash hardening + log chase** *(route: writer + parent)*.
  DONE 2026-10-13, commit `53c33d2` (+34/−21): whole handler in try/catch,
  feature-guarded manager destroy, teardown calls unchanged. Verified: remove→
  re-add clean on both scratches, INCLUDING with the dialog open (field
  scenario) — process alive, re-add functional, 0 errors. Root cause of the
  FIELD crash still pending the user's 5.4 logs.
- [x] **T3 — Add-flow UX + login affordance** *(route: writer; surface:
  `cinnamon/applet.js`)*. DONE 2026-10-13, commits `287bb9f` (+125/−10) +
  correction `02e2804` (+8/−6, login button now offered whenever no credentials
  — the field case). Verified live: missing-DB state → error helper +
  `Log in with OpenCode…` + `Refresh` + API-key default (screenshot
  `T3-missing-db.png`); empty-DB state → `No OpenCode login found…` + both
  buttons (`T3-empty-db.png`); login button click → terminal opens
  `opencode auth login` (`T3-login-clicked.png`); Refresh → in-place update
  (`Credentials reloaded.` after inserting a row); `_failureMessage` mapping
  probed.
- [x] **T4 — Restyle the account dialogs** *(route: writer, same session;
  surface: `cinnamon/applet.js`)*. DONE 2026-10-13, commit `22470ac`
  (+52/−31). Verified visually by the parent under BOTH themes: default 6.4
  and the **5.4 theme loaded in the harness** (`T4-final-relive54.png` — bold
  centered title, outlined buttons, radio dots, real spacing; vs the field
  screenshot's unstyled dialog).
- [x] **T5 — Make-active explainer** *(route: writer; surfaces:
  `cinnamon/applet.js`, `cinnamon/settings-schema.json`)*. DONE 2026-10-13,
  commit `03a8bb6` (+33/−6 across 2 files). Verified live: non-pinned
  selection → explainer dialog (`T5-explainer.png`); pinned → unchanged
  confirm (`T5-confirm-pinned.png`); schema JSON valid.
- [x] **T5b — Reload-safe MessageContent** *(route: writer, folded in)*.
  DONE 2026-10-13, commit `6964b1e` (+41/−37): factory instead of
  `GObject.registerClass`; `ReloadXlet` now succeeds on both scratches (no
  `already registered`).
- [ ] **T6 — Independent verification** *(route: verifier)*. LAUNCHED
  2026-10-13 and **CANCELLED by the runtime before delivering a verdict**.
  Optional for this medium-risk round (gate requires writer self-verification
  + parent spot checks, both done). Can be relaunched on request.
- [x] **T7 — PR #4** *(route: parent; branch-pr skill)*. DONE 2026-10-13:
  pushed and opened PR #4 — https://github.com/martinrdilo/opencode-go-meter/pull/4 (label `bug`; no linked issue — no
  issue-first flow, documented in the body). CI runs on it. Merge is the
  user's call; residuals: the field crash root cause (pending the reporter's
  5.4 logs), GNOME parity, the popup item note.

## Acceptance criteria

- Fresh login-less user: dialog defaults to API key; `Log in with OpenCode…`
  visible in both no-credential states; friendly failure text. → DONE
  (screenshots).
- Dialog presentable under the 5.4 theme; unchanged-or-better on 6.4. → DONE
  (screenshots under both themes).
- Removal clean in the harness with hardening in place; Mint confirmation
  pending the user (root cause of the field crash still open). → HARNESS DONE.
- "Make active in OpenCode…" explains itself when inapplicable. → DONE.
- Gates green: `make test` 422 OK, `make check-cinnamon` ok,
  `node --check` ok, schema JSON ok. → DONE.

## Checks

- `make test` (422), `make check-cinnamon`, `node --check cinnamon/applet.js`.
- Live nested Cinnamon 6.4 (both scratches) + the 5.4-theme pass.

## Forecast

≈ 250–350 forecast; actual ≈ 500 changed lines (applet.js + schema). Single
PR with documented size exception.

## Progress log

- 2026-10-13 — T1: report triaged; launcher evidence (real process crash);
  5.4-theme class inventory; branch seeded.
- 2026-10-13 — T3/T4 done (`287bb9f`, `22470ac`): login affordance +
  restyle; writer captured one SIGABRT (intermediate build) and reported the
  destroy-abort hypothesis.
- 2026-10-13 — Parent investigation: abort NOT reproducible on the final code
  (10+ variants incl. the field pattern); core attributed to the intermediate
  build; in-place Refresh kept.
- 2026-10-13 — Corrections + T5 + T2 + T5b (`02e2804`, `6964b1e`, `03a8bb6`,
  `53c33d2`): gating fix (field case), reload-safe factory, make-active
  explainer, removal hardening; removal/re-add verified with the dialog open;
  reload verified.
- 2026-10-13 — Parent verification: static gates green; 5.4-theme screenshot
  captured (presentable); field-case screenshot reviewed. T6 verifier
  cancelled by the runtime. T7: PR #4 opened — https://github.com/martinrdilo/opencode-go-meter/pull/4.

---

Locator: odd/tasks/applet-ux-fixes.md (repo: opencode-go-meter)
