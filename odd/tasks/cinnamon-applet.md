# Feature: cinnamon-applet — OpenCode Go meter in the Cinnamon panel

**Status**: Open (T1 next) — 2026-10-03
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
- Delivery: work-unit commits on `feat/cinnamon-applet`, local merge by the user (repo has **no remote**; chained PRs N/A). Forecast ≈ 650–850 authored lines (>400 budget recorded; slicing via work-unit commits).
- RDD (receipt-driven development): **off** (`gentle-ai review mode status`: global off) → ordinary repository policy. After each delegated writer, the parent assesses the diff tier with `gentle-ai review assess` (RDD-off path) to pick verification depth.
- TDD: **not applicable** — no JS test runner in the repo; core `make test` stays green as regression; the applet is verified by static checks + live nested session + independent diff verification.
- Artifacts in English; conversation in Spanish.

## Verification approach

- Nested session (exact command proven in T1): `Xephyr` display + `dbus-run-session`, private `XDG_CONFIG_HOME` (isolated dconf) so the user's real session is untouched; real `ocgo` data/cache flows through (`XDG_CACHE_HOME` stays real).
- Applet loaded from the repo via symlink into the applet dir; dev reload via Cinnamon restart inside the nested session.
- Static: `make check-cinnamon` (JSON validation + `node --check`), `make test` (core regression).
- Live: compare panel/popup values against `ocgo status`; exercise refresh, account switch, empty state (isolated registry), stale/error state.

## Tasks

- [ ] **T1 — Spike: nested Cinnamon harness + API contract** *(route: parent env + explorer contract)*. Proven nested-session command; minimal smoke applet visible in the nested panel; ≤2k-token API contract (applet base classes; popup/submenu API; settings binding; icon/label handling incl. colored text; applet load/reload loop; enabling the applet in a fresh nested session) with `path:line` evidence from the installed Cinnamon 6.4 sources.
  - Env prerequisite (user-run; sudo needs a password): `sudo apt-get install -y cinnamon xserver-xephyr`.
- [ ] **T2 — Applet core** *(route: delegated writer; `gnome/extension.js` as behavior reference)*. `cinnamon/` skeleton; panel label `5h X% · 7d Y% · 30d Z%` with per-figure colors; cache discovery for the active account (registry v2 → cache path); refresh every interval + on click via `ocgo refresh`; stale (`last_error`) and empty states (`—` + "No accounts configured"); `ocgo` path resolution with settings override. Work-unit commit.
- [ ] **T3 — Popup + accounts** *(route: same writer)*. Header "OpenCode Go — Renews <date>", three rows (label, colored %, "Resets in …"), "no active OpenCode Go subscription" warning, Account radio submenu from `ocgo account list --json` (available in the empty state), footer "Updated Xm ago · Refresh", empty state. Work-unit commit.
- [ ] **T4 — Settings schema** *(route: with the writer)*. `settings-schema.json`: refresh interval (default 300 s), `ocgo` path override; bindings via `AppletSettings`. Work-unit commit.
- [ ] **T5 — Install/uninstall + docs** *(route: delegated writer or parent)*. Makefile `install-cinnamon` / `uninstall-cinnamon` (symlinks under `~/.local/share/cinnamon/applets/`, foreign-link guard), `check-cinnamon`; README Cinnamon section (quickstart, account notes, layout); keep `install` (GNOME) as-is. Work-unit commit.
- [ ] **T6 — Verification** *(route: parent + fresh verifier)*. Nested live run end-to-end vs real cache/CLI (refresh, switch, empty, stale); `make test` + `make check-cinnamon` green; independent verification of the full diff (tier via `gentle-ai review assess`). Evidence in this doc.
- [ ] **T7 — Close** *(route: parent)*. Feature doc final state + Engram mirror; merge note for the user.

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

---

Locator: odd/tasks/cinnamon-applet.md (repo: opencode-go-meter)
