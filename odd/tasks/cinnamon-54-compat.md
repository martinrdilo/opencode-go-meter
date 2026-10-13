# Feature: cinnamon-54-compat — Cinnamon 5.4 (Linux Mint 21) compatibility

**Status**: In progress — T1 recon done; T2–T6 pending
**Repo**: `opencode-go-meter`
**Branch**: `fix/cinnamon-54-compat` (from `main` @ `6c0ad65`)
**Created**: 2026-10-13

## Objective

Make the Cinnamon applet load and work on Cinnamon 5.4 (Linux Mint 21), not only
on 6.4: fix the single incompatible API (`imports.ui.dialog`), declare the
supported range in `metadata.json`, guard the regression statically, and point
API-key users at the right `ocgo account add` form (docs + error hint).

## Problem / Why

Report from a Linux Mint 21 machine (Cinnamon 5.4.13): the applet never appears
in the panel and its settings do not open. `~/.xsession-errors`:

    [opencode-go-meter@martinrdilo]: No JS module 'dialog' found in search path
    [opencode-go-meter@martinrdilo]: Error importing applet.js from opencode-go-meter@martinrdilo

`cinnamon/applet.js` imports `imports.ui.dialog` and uses
`Dialog.MessageDialogContent` (add-account dialog, remove confirm, make-active
confirm). `js/ui/dialog.js` does not exist before Cinnamon 6.4 — verified HTTP
404 at tags 6.0.0, 6.2.0 and 6.2.9, present at 6.4.0 — so the whole module fails
to import and the applet dies before `main()`.

Secondary report (same session): on a machine with an API key and no OpenCode
login, `ocgo account add personal --from-db` fails with "No OpenCode credential
found"; neither the docs nor the error point to the API-key form
(`ocgo account add <id> --label ...` without `--from-db`).

## Evidence (recon, 2026-10-13)

Full API audit of `cinnamon/applet.js` (main revision) against the Cinnamon
5.4.13 sources (`raw.githubusercontent.com/linuxmint/cinnamon/5.4.13/*`):

| applet usage | 5.4.13 status |
| --- | --- |
| `imports.ui.dialog` / `Dialog.MessageDialogContent` | **missing** — module added in 6.4 |
| `ModalDialog.ModalDialog` (`contentLayout`, `setButtons` incl. `key`, `setInitialKeyFocus`, `buttonInfo.button`) | present (js/ui/modalDialog.js:111/171/290) |
| `Applet.TextApplet`, `Applet.AppletPopupMenu` | present (js/ui/applet.js:800/69) |
| `Settings.AppletSettings.bind(key, prop, cb)` | present (js/ui/settings.js:872/356) |
| `Util.spawnCommandLineAsyncIO` | present (js/misc/util.js:222) |
| `PopupMenu.*` (PopupMenuItem, PopupBaseMenuItem, PopupSeparatorMenuItem, PopupSubMenuMenuItem, PopupMenuManager, OrnamentType) | present (js/ui/popupMenu.js:479/97/531/2953/3466/35) |
| `PopupMenuManager({actor: ...})` | present (`_owner.actor` at popupMenu.js:3529) |
| `RadioButton.RadioButtonGroup` (addButton, setActive, getActive, `radio-changed`, `.actor`) | present (js/ui/radioButton.js:138+) |
| `Main.uiGroup` + `add_actor` | present (used by stock 5.4 code) |

`Dialog.MessageDialogContent` is the only 5.4 breakage; the reporter's warning
about further 6.x-only APIs is covered by this audit — none found.

`cinnamon-version` semantics (js/ui/extension.js, 5.4.13): `versionCheck(required,
current)` returns true when `current` is >= ANY listed entry, and an incompatible
xlet is refused with `State.OUT_OF_DATE` (extension.js:319, definition :461).
`["5.4"]` therefore means "5.4 and newer" — Mint 21 (5.4) through 6.x.

The installed broken copy on the reporter machine matches `main` line-for-line
(import at 5, sites at 797 / 940, dynamic content updates at 914-915).

## Scope

In scope:

- `cinnamon/applet.js`: drop `imports.ui.dialog`; local `MessageContent`
  (St-based, same DOM/style classes as 6.4's `MessageDialogContent`); header
  comment updated to the new floor.
- `cinnamon/metadata.json`: `"cinnamon-version": ["5.4"]`.
- `cinnamon/scripts/check_applet.py`: import allowlist guard (5.4 floor).
- `core/ocgo/cli.py` + `core/tests/test_cli.py`: actionable API-key hint when
  `account add --from-db` (auto) finds no OpenCode login.
- `README.md`: Cinnamon 5.4+ note; `--from-db` vs API-key clarification.

Out of scope:

- GNOME extension; spices distribution.
- Editing the open PR #1 branch (`feat/multi-oauth-accounts`) — after this PR
  merges, that branch needs a rebase that re-applies the fix to its three
  dialog sites (follow-up, user-driven).
- Live verification on a real 5.4 session: this machine's nested harness runs
  Cinnamon 6.4; the Mint 21 check is a user-side residual (documented).

## Decisions

- Branch: fix from `main` (the broken, installed revision) → its own PR (#2).
  Bugfix first; PR #1 rebases afterwards.
- Replacement design: `GObject.registerClass` subclass of `St.BoxLayout` with
  `title`/`description` accessors mirroring 6.4's `MessageDialogContent` — same
  style classes (`message-dialog-content` / `-title` / `-description`),
  description `line_wrap` + `ellipsize NONE` — so the call sites keep
  `new MessageContent({...})` and `content.title = ...` verbatim and 6.4
  rendering is unchanged by construction. `GObject.registerClass` works on
  gjs >= 1.62 (Mint 21 ships 1.72).
- The static guard is an allowlist, not a banlist: a new `imports.ui.<module>`
  must be added consciously after checking the 5.4 sources.
- CLI: append the API-key form only to the auto (`--from-db`, no `--credential`)
  no-credential failure — not to pinned-credential errors; the existing message
  prefix stays (several tests rely on it).
- Live verification here: nested Cinnamon 6.4 session (no-regression proof);
  real 5.4 behavior is the user's Mint 21 residual.
- Delivery: single PR; forecast ≈ 150 authored lines (< 400 budget). Strategy
  ask-on-risk (default); no chain needed.
- RDD: **off** (global) → ordinary policy; parent runs `gentle-ai review assess`
  on each writer diff to pick verification depth.
- TDD: core change is test-first (`cd core && python3 -m unittest ...`, runner
  `make test`); the JS side has no test runner in the repo (precedent:
  static checks + nested live session).
- Artifacts in English; conversation in Spanish.

## Tasks

- [x] **T1 — Recon + feature doc** *(route: parent, inline evidence batch)*.
  DONE 2026-10-13. Evidence tables above; branch seeded from `main` @ `6c0ad65`.
- [ ] **T2 — Applet compat fix** *(route: delegated writer; surfaces:
  `cinnamon/applet.js`, `cinnamon/metadata.json`)*. Replace the 6.4-only dialog
  import/component with the local `MessageContent`; declare `cinnamon-version`.
  Checks: `node --check`, `check_applet.py`, `make test`, grep for `Dialog.`
  (zero matches).
- [ ] **T3 — Static guard** *(route: delegated writer; surface:
  `cinnamon/scripts/check_applet.py`)*. Import allowlist for the 5.4 floor +
  negative probe in a /tmp copy.
- [ ] **T4 — CLI hint + core test + README** *(route: delegated writer;
  surfaces: `core/ocgo/cli.py`, `core/tests/test_cli.py`, `README.md`)*.
  Test-first: observed RED → GREEN.
- [ ] **T5 — Verification** *(route: parent + independent verifier)*. Static
  gates, nested Cinnamon 6.4 live pass (applet + dialogs), independent
  read-only verification of the whole diff; assessments recorded per task.
- [ ] **T6 — PR #2** *(route: parent; branch-pr skill)*. Push, open the PR,
  record it here; note the PR #1 rebase follow-up.

## Acceptance criteria

- On a real Cinnamon 5.4.13 session (user, Mint 21): applet appears in the
  panel, settings open, and the add/remove/activate dialogs render — user-side
  residual.
- Nested Cinnamon 6.4 session (this machine): applet loads; the three dialogs
  render with unchanged content (screenshots).
- `make check-cinnamon` fails on `imports.ui.dialog` (negative probe) and
  passes on the repo.
- `make test` green; a new test proves the `--from-db` API-key hint.
- `metadata.json` declares `["5.4"]`; README states the 5.4+ support and the
  API-key form.

## Checks

- `make test` — core suite (regression + new hint test).
- `make check-cinnamon` + negative probe (copied tree in `/tmp/opencode`).
- `node --check cinnamon/applet.js`.
- Nested session live run (recipe in `odd/tasks/cinnamon-applet.md` →
  "Nested test harness").

## Forecast

≈ 150 authored lines: applet ~+45/−4; check_applet ~+45; cli ~+8; tests ~+30;
README ~+8; metadata +1. Under the 400-line budget → single PR.

## Progress log

- 2026-10-13 — Feature opened from `main` @ `6c0ad65`. T1 recon: 5.4.13 API
  audit (dialog module is the only breakage), `cinnamon-version` semantics,
  guard + CLI-hint design, branch `fix/cinnamon-54-compat`.

---

Locator: odd/tasks/cinnamon-54-compat.md (repo: opencode-go-meter)
