# Feature: cinnamon-applet — OpenCode Go meter in the Cinnamon panel

**Status**: Complete — T1–T8 done; merged to `main` (fast-forward, 2026-10-10)
**Repo**: `/home/martin/workspace/opencode-go-meter`
**Branch**: `feat/cinnamon-applet` (from `main` @ `aea2c03`)
**Created**: 2026-10-03

## Objective

Second frontend for opencode-go-meter: a **Cinnamon applet** (target: Cinnamon 6.4, Linux Mint-class desktops) showing the three OpenCode Go usage windows (rolling 5h / weekly / monthly) as consumed %, with popup countdowns, renewal date, colors, account switching, manual refresh, and the same empty/error states as the GNOME extension — reading the same `ocgo` cache and CLI.

## Problem / Why

The original plan deferred Cinnamon as T8 ("applet vs tray" undecided, no test environment). The core is desktop-agnostic by design; Cinnamon users (Linux Mint) get the same always-visible meter without any data-layer changes.

## Scope

In scope:

- `cinnamon/` applet: `metadata.json`, `applet.js`, `settings-schema.json`, icon.
- Makefile: `install-cinnamon` / `uninstall-cinnamon` symlink targets + `check-cinnamon` static checks.
- README: Cinnamon quickstart + layout/architecture notes.
- Nested test harness (dev loop) documented in this task doc.

Out of scope:

- Spices distribution (cinnamon-spices.linuxmint.com).
- Notifications, popup mini-bars.
- `core/` changes (none expected; if a fix is needed, the suite must stay green).

## Decisions

- **Applet, not tray** (open to user veto before T2): applets support panel text, a rich popup, and native settings; the XApp tray gives only a status icon (no popup, no text, no placement control). This is the Cinnamon counterpart of the GNOME indicator.
- Panel placement: Cinnamon lets users drag applets; no zone/order preferences (the GNOME panel prefs do not carry over).
- Settings: `settings-schema.json` + `AppletSettings` (auto-generated UI in Cinnamon Settings → Applets → gear); refresh interval + `ocgo` path override. No custom prefs code.
- uuid: `opencode-go-meter@martin.local` (same as GNOME). Max instances: 1.
- Testing environment (user-approved 2026-10-03): Cinnamon 6.4 + Xephyr on this Ubuntu GNOME machine; **nested sessions** for live verification, isolated from the real session (own X display + private dconf/config).
- Dev loop (proven in T1): hot reload via D-Bus `org.Cinnamon.ReloadXlet` (type `APPLET`, uppercase); screenshots via `cjs` + Gdk3 root capture. Nested-session recipe below.
- Account resolution (post-correction `def2eee`): **CLI-only** via `ocgo account list --json` (GNOME parity — a fresh install sees the seeded `default` without registry writes; the cache is read only for the active id). Earlier "registry v2" mentions in T2/T3 describe the pre-correction implementation.
- Accepted deviations / residuals (T6): set-but-unresolvable `ocgo-path` fails visibly (GNOME silently falls back — deliberate fail-closed); no-cache label `5h — · 7d — · 30d —` (GNOME `Go —`; intentional); tooltip always names the active account; `check_applet.py`'s anchored regex covers inline comments — a `function main(` inside a multi-line block comment remains a documented residual; the initial-refresh flag is also consumed by a CLI-failure startup (the 300 s timer and footer Refresh still work); the double-load `ReloadXlet` quirk is dev-harness-only (appletManager racing enable+reload).
- Delivery: work-unit commits on `feat/cinnamon-applet`, local merge by the user (repo has **no remote**; chained PRs N/A). Forecast ≈ 650–850 authored lines (>400 budget recorded; slicing via work-unit commits).
- RDD (receipt-driven development): **off** (`gentle-ai review mode status`: global off) → ordinary repository policy. After each delegated writer, the parent assesses the diff tier with `gentle-ai review assess` (RDD-off path) to pick verification depth.
- TDD: **not applicable** — no JS test runner in the repo; core `make test` stays green as regression; the applet is verified by static checks + live nested session + independent diff verification.
- Artifacts in English; conversation in Spanish.

## Verification approach

- Nested session: recipe + proven commands below ("Nested test harness"). Fully isolated from the real desktop session (scratch HOME, private dbus/dconf, own X display); real-ish data via read-only opencode.db symlink + snapshots of the ocgo registry/cache.
- Applet loaded from the repo via symlink into the scratch applet dir; hot reload via `ReloadXlet`; screenshots via `cjs`.
- Static: `make check-cinnamon` (JSON validation + `node --check`), `make test` (core regression).
- Live: compare panel/popup values against `ocgo status`; exercise refresh, account switch (isolated registry), empty state, stale/error state.

## Nested test harness (T1, proven 2026-10-08)

Scratch root `$CT=/tmp/opencode/cinnamon-test`; isolated `$CT/home`; persistent private session bus; Xephyr `:19`.

1. Bus (must be started with the scratch HOME so dconf/service activation stays isolated):
   `HOME=$CT/home dbus-daemon --session --address=unix:path=$CT/bus --fork --print-address`
2. Display (once): `Xephyr :19 -screen 1600x900 -glamor -no-host-grab`
3. Session (background; NEVER bare `cinnamon` — it tries a Wayland display server and hits logind EBUSY against the host session):
   `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 XDG_SESSION_TYPE=x11 HOME=$CT/home DISPLAY=:19 DBUS_SESSION_BUS_ADDRESS=unix:path=$CT/bus cinnamon --x11 --sm-disable`
4. Enable applet (isolated dconf):
   `HOME=$CT/home DBUS_SESSION_BUS_ADDRESS=unix:path=$CT/bus dconf write /org/cinnamon/panels-enabled "['1:0:top']"`
   `HOME=$CT/home DBUS_SESSION_BUS_ADDRESS=unix:path=$CT/bus dconf write /org/cinnamon/enabled-applets "['panel1:right:0:opencode-go-meter@martin.local']"`
   Applet dir: symlink the repo `cinnamon/` into `$CT/home/.local/share/cinnamon/applets/opencode-go-meter@martin.local`.
5. Hot reload: `gdbus call --session --dest org.Cinnamon --object-path /org/Cinnamon --method org.Cinnamon.ReloadXlet "opencode-go-meter@martin.local" "APPLET"` (type MUST be uppercase); watch `$CT/logs/cinnamon.log`.
6. Screenshot: `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 DISPLAY=:19 SHOT_PATH=<out.png> cjs $CT/shot.js` (helper: `imports.gi.versions.Gdk = "3.0"`, `Gdk.Display.open($DISPLAY)`, `pixbuf_get_from_window`).
7. Data plumbing (in place): `$CT/home/.local/bin/ocgo` → repo `core/bin/ocgo`; `$CT/home/.local/share/opencode` → real `~/.local/share/opencode` (read-only creds for the `default` account); copies of `~/.config/ocgo` and `~/.cache/ocgo` (snapshot — tests never mutate the real registry).

## Cinnamon 6.4 API contract (T1)

Paths abbreviate `/usr/share/cinnamon`: `A`=js/ui/applet.js, `P`=js/ui/popupMenu.js, `S`=js/ui/settings.js, `M`=js/ui/appletManager.js, `X`=js/ui/extension.js, `U`=js/misc/util.js; examples `E`=applets/settings-example@cinnamon.org, `K`=applets/keyboard@cinnamon.org, `SO`=applets/sound@cinnamon.org.

- Entry: `function main(metadata, orientation, panel_height, instance_id)` (M:599); class `constructor(orientation, panel_height, instance_id)` (K:219-220). Bases: `Applet` (A:129), `IconApplet` (A:674), `TextApplet` (A:801), `TextIconApplet` (A:852), `Applet.AppletPopupMenu` (A:70).
- Panel text: `set_applet_label()` is plain text (A:833); per-figure colors via `this._applet_label.clutter_text.set_markup('<span foreground="…">…</span>')` (idiom at menu@cinnamon.org:273, notifications:274). Tooltip: `set_applet_tooltip(text, use_markup)` (A:301).
- Popup: `this.menuManager = new PopupMenu.PopupMenuManager(this)`; `this.menu = new Applet.AppletPopupMenu(this, orientation)`; `menuManager.addMenu(menu)` (E:14-16); AppletPopupMenu self-parents to `Main.uiGroup` (A:79-83). Items: `PopupMenuItem(text)` (P:479) + `activate` signal; sections `PopupMenuSection` (P:2906); submenu `PopupSubMenuMenuItem` (P:2920) with children at `submenu.menu.addMenuItem()`; NO `RadioMenuItem` in 6.4 — radio = `item.setOrnament(PopupMenu.OrnamentType.DOT, selected)` (P:499, P:35); `menu.addActor(actor)` (P:2094); `toggle/open/close` (P:2137/2324/2423).
- Settings: `new Settings.AppletSettings(this, metadata.uuid, instance_id)` (S:883); `bind(key, prop, cb)` (S:356); `connect("changed::key", cb)` (S:623); `settings.finalize()` in removal (S:866; E:131-135). `settings-schema.json` next to applet.js enables the Configure menu (A:606-615); `spinbutton` needs `min`/`max`/`step` (E schema:98-107). Config at `$XDG_CONFIG_HOME/cinnamon/spices/<uuid>/<uuid>.json` for single-instance xlets (verified in T4; S:692).
- Spawn: `Util.spawn(['ocgo','refresh'])` non-blocking argv (U:101-110); `Util.spawnCommandLineAsyncIO` for output callbacks (U:229-251); timers `Mainloop.timeout_add_seconds` + `Mainloop.source_remove` on removal (SO:345-419).
- Lifecycle: `on_applet_added_to_panel(userEnabled)` (A:397); `on_applet_removed_from_panel(deleteConfig)` (A:407) ← do cleanup here (no `finalize` on Applet). Search dir `~/.local/share/cinnamon/applets/<uuid>` (X:59/629); uuid == dir name (X:332); metadata needs `uuid`/`name`/`description` (X:50-51), optional `icon`/`max-instances`/`cinnamon-version` (X:752/X:336).
- Enable: GSettings `org.cinnamon` `enabled-applets`, entries `panel1:<left|center|right>:<order>:<uuid>:<applet_id>` (M:148-152; id optional).
- Gotchas: legacy `imports.*` only (no ESM); callbacks not auto-bound (arrows/`Lang.bind`); destroy rebuilt menu items (`item.destroy()` K:309) or `menu.removeAll()` (P:2124); `AppletPopupMenu` needs a `PopupMenuManager`.

## Tasks

- [x] **T1 — Spike: nested Cinnamon harness + API contract** *(route: parent env + explorer contract)*. DONE 2026-10-08. Proven: nested `cinnamon --x11` session on Xephyr `:19` with private bus + scratch HOME; smoke applet loaded and rendered in the panel; hot reload via `ReloadXlet` confirmed (log: `Loaded applet ocgo-smoke@test in 18 ms`); screenshots verified (panel label before/after reload). Contract: see "Cinnamon 6.4 API contract" above. Env installed (user-run): cinnamon 6.4.13 + xserver-xephyr + cjs 128.1.
- [x] **T2 — Applet core** *(route: delegated writer; `gnome/extension.js` as behavior reference)*. DONE 2026-10-08, commit `072680f` (332-line `applet.js` + `metadata.json`). Verified live in the nested session: label `5h 1% · 7d 6% · 30d 70%` (green/green/amber; markup 49→green, 50→amber, 85→red), stale/error tooltip, empty state `—` + "No accounts configured" (isolated registry), click refresh rewritten cache (`last_error_at` matched), `make test` 253 OK, `node --check` + JSON OK. Assessment: medium / under_budget (no review due). Findings: (a) dconf-enable + immediate `ReloadXlet` can double-load and leave the applet unparented — a second reload recovers; check `appletManager.definitions[i].applet` after reloads in T3/T6; (b) scratch harness `ocgo refresh` takes ~10 s (no keyring) — clicks coalesce via `_refreshInProgress`; (c) registry parsing is strict v2 (a v1 registry renders `—` until core materializes v2); (d) Cinnamon tooltips are plain text only (`set_markup` forwards to `set_text`).
- [x] **T3 — Popup + accounts** *(route: same writer)*. DONE 2026-10-08, commit `225e4cb` (`applet.js` now 656 lines). Verified live: header `OpenCode Go · <label> — Renews <date>`, amber `last_error` warning row, three rows with countdowns (`4h 2m` / `2d 22h` / `2d 1h`) and colors, `Account` radio submenu from `ocgo account list --json` (dot moves on switch; the switch wrote the isolated registry; switched-to empty account shows `—`, never invented values), footer `Updated 30m ago · Refresh` re-rewrote the cache, true-empty registry → `No accounts configured`, 5 open/close cycles leak-free, `make test` 253 OK. Assessment: medium / under_budget. Findings: (a) Cinnamon items have no `.visible` — use `item.actor.visible`; (b) `Params.parse` throws on GNOME-only params like `can_focus`; (c) radio state at `item._ornament.child.checked` (DOT+false renders an empty circle); (d) submenus expand inline, not floating; (e) missing-registry split: label (registry-driven) shows `—` while the CLI-seeded submenu lists `Default` — T6 check for GNOME parity.
- [x] **T4 — Settings schema** *(route: with the writer)*. DONE 2026-10-08, commit `f252779` (`settings-schema.json` + `applet.js` wiring; timer restart, path override, `finalize()`). Verified live: settings UI renders both fields (screenshot), interval `300 → 30` restarts the timer live (cache rewritten on the new cadence) and back, bogus `ocgo-path` fails cleanly without inventing data (restored), `make test` 253 OK. Assessment: medium / under_budget. Findings: (a) single-instance xlets store settings at `$XDG_CONFIG_HOME/cinnamon/spices/<uuid>/<uuid>.json` (not `<instance_id>.json` as the T1 contract first assumed); (b) deliberate: a set-but-unresolvable `ocgo-path` fails visibly (GNOME silently falls back — T6 parity check); (c) `xlet-settings` highlight sticks if killed — clear with `org.Cinnamon.highlightXlet <uuid> <id> false`.
- [x] **T5 — Install/uninstall + docs** *(route: delegated writer)*. DONE 2026-10-08, commit `211b632` (+148/−3). Verified: `make check-cinnamon` passes (negative tests: corrupt JSON, uuid mismatch, missing `main`, node syntax errors → exit 1); fake-HOME install idempotent + uninstall removes only repo links (foreign links kept; the shared `ocgo` link is silent-guarded); `make -n install` byte-identical (GNOME target untouched); `make test` 253 OK. Note: `check_applet.py` compares `metadata.uuid` against the Makefile `UUID` (the checked-in dir is `cinnamon/`, not the uuid); in an installed copy it compares the real dir name.
- [x] **T6 — Verification** *(route: parent + independent verifier)*. DONE 2026-10-08. Independent verification (fresh read-only session) over `aea2c03..HEAD`: gates green (`make test` 253, `make check-cinnamon`, `node --check`, both JSONs); security OK (no credential access; argv spawns; no injection); parity/lifecycle OK. Findings fixed: **MAJOR** — fresh-install registry gating (dead `—` panel, false "No accounts configured", refresh disabled) → `def2eee` CLI-only resolution (live-verified: seeded `Default`, refresh landed with real values); **MINOR** — `check_applet.py` main false-negative → anchored regex + negative test; **NIT** — CLI stderr logged → silenced; **MINOR** — initial-refresh startup race → `bc5cc83` pending-flag fix (deterministic slow-path race test; parent reviewed the diff). Scoped re-verification confirmed the fixes. Parent live pass: label/popup match `ocgo status` (screenshots `t6-panel.png`, `t6-popup.png`); true-empty, fail-closed, and seeded-default paths verified. Tier trail: per-task medium/under_budget; full-branch and correction diffs `high` (process_boundary) with RDD off → independent verification, no review start.
- [x] **T7 — Close** *(route: parent)*. DONE 2026-10-08: feature doc final state + Engram mirror; sandbox harness left running for inspection; local merge is the user's call (repo has no remote).
- [x] **T8 — Accounts management in preferences (GNOME parity)** *(route: delegated writer; user-requested 2026-10-10)*. DONE 2026-10-10, commits `e8db106` (+286 `applet.js`, +25 schema, README) + `d297754` (duplicate-label fix). Delivered: Accounts section in the applet settings — Active-account combobox (dynamic options via `setOptions`; switching runs `ocgo account use` with restore-on-failure), "Add / replace key…" (`set-key` when the id exists else `add`; `--store auto`; `--label` for add; key via **stdin only**), "Remove account…" (kind-specific confirm body; `account remove <id>`), GNOME-identical validation messages; transient inputs only — the key never touches the settings JSON. Verified live: invalid input never spawns; a fake key surfaced the CLI's HTTP 401 in the dialog (proving stdin receipt + `--store auto` argv); grep assertion — the test key appears in NO config/cache/journal file; remove flows (both kinds) and the active switch verified; duplicate labels render as deterministic `label (id)` options (both selectable). Independent reviewer: secret path and parity verified; the one MINOR (duplicate-label collapse) fixed in `d297754` + re-verified. Gates: `node --check`, `make check-cinnamon`, `make test` 253; assessment medium/under_budget. Residuals (documented): an OPEN settings dialog does not rebuild combo options until reopened (host `setOptions` limitation); a failed combo switch restores selection silently (journal line only); the dialog can be closed mid-command (safe — the key is already in the stdin pipe; `closed` guards widget access).

## Acceptance criteria

- In a nested Cinnamon 6.4 session with real data: panel shows consumed % for the three windows; popup shows countdowns, renewal, colors (green <50, amber 50–84, red ≥85); manual + timed refresh work; account submenu switches; empty state shows `—` / "No accounts configured"; stale/error never invents zeros.
- The applet never reads credentials (cache + `ocgo` CLI only), same security contract as GNOME.
- `make install-cinnamon` idempotent, no sudo, only symlinks; `make uninstall-cinnamon` removes only links into this repo.
- `make test` green; `make check-cinnamon` green.
- README documents the Cinnamon quickstart.

## Checks

- `make test` — core regression (253 tests expected green).
- `make check-cinnamon` — new static checks.
- Nested session live run — documented command; manual comparison vs `ocgo status`.
- `node --check cinnamon/applet.js`.

## Progress log

- 2026-10-03 — Feature opened from `main` @ `aea2c03`. Test environment decided with the user: Cinnamon 6.4 + Xephyr on this Ubuntu machine, nested sessions for live verification (user-approved). RDD global off; no git remote (local merge delivery). Plan committed.
- 2026-10-08 — T1 closed. Env installed (cinnamon 6.4.13, xserver-xephyr, cjs 128.1). Nested harness proven: `cinnamon --x11` on Xephyr `:19` + private bus/scratch HOME (bare `cinnamon` fails with logind EBUSY against the host session); smoke applet loaded and rendered; hot reload via `ReloadXlet` OK; screenshots via cjs OK. API contract captured (above). Data plumbing snapshot in place. Next: T2.
- 2026-10-08 — T2 closed (`072680f`): applet core with colored panel label, registry v2 → cache discovery, 300 s + click refresh, stale/error tooltip, empty state. Live-verified in the nested session; `make test` 253 OK. Assessment medium/under_budget. Next: T3 (popup + accounts) with the same writer.
- 2026-10-08 — T3 closed (`225e4cb`): popup with header/renewal, warning row, meter rows + countdowns, account radio submenu + switching, footer refresh, empty states; leak-free rebuilds; live-verified incl. account-switch round-trip. `make test` 253 OK. Assessment medium/under_budget. Next: T4 (settings).
- 2026-10-08 — T4 closed (`f252779`): settings schema + live wiring (interval restart, path override, clean bad-path failure); settings UI renders both fields. `make test` 253 OK. Assessment medium/under_budget. Next: T5 (install/uninstall + docs).
- 2026-10-08 — T5 closed (`211b632`): Makefile `install-cinnamon`/`uninstall-cinnamon`/`check-cinnamon`, `check_applet.py` (with negative tests), README Cinnamon quickstart. `make test` + `make check-cinnamon` green; fake-HOME install/uninstall verified. Full-branch assess: **high** (process_boundary on `check_applet.py`) — RDD off, so independent verification in T6 (no review start). Next: T6.
- 2026-10-08 — T6 closed: independent verification + two bounded corrections (`def2eee`, `bc5cc83`) + scoped re-verification; live end-to-end pass green (label/popup = CLI values, fresh-install, true-empty, fail-closed). Accepted deviations documented in Decisions.
- 2026-10-08 — T7 closed: doc final + Engram mirror. Feature complete pending the user's local merge; sandbox harness at `/tmp/opencode/cinnamon-test` left running for inspection.
- 2026-10-10 — T8 opened (user request after live review of both frontends): port GNOME's Accounts management to the Cinnamon preferences with transient inputs — key via stdin only, never persisted. Sandbox rebuilt (system tmp cleanup wiped it) and verified live again; user is inspecting it.
- 2026-10-10 — T8 closed (`e8db106` + `d297754`): GNOME-parity Accounts management in the Cinnamon preferences (active switch, add/replace with stdin-only key, remove with kind-specific confirm); live-verified incl. the no-persistence assertion; independent review passed with one MINOR fixed. Feature complete again; local merge still the user's call.
- 2026-10-10 — Merged to `main` (fast-forward `f9c58a1`, user-authorized). Sandbox `/tmp/opencode/cinnamon-test` still running for inspection; branch `feat/cinnamon-applet` kept (optional cleanup).

---

Locator: odd/tasks/cinnamon-applet.md (repo: opencode-go-meter)
