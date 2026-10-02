# Feature: opencode-go-meter — OpenCode Go usage meter (GNOME first, Cinnamon planned)

**Status**: in progress
**Repo**: `/home/martin/workspace/opencode-go-meter`
**Branch**: `feat/gnome-indicator` (implementation)
**Created**: 2026-10-01

## Objective

Show OpenCode Go subscription usage (rolling 5h / weekly / monthly) permanently in the Linux desktop UI. First frontend: GNOME Shell top-bar indicator (Ubuntu 26.04, GNOME Shell 50.1, Wayland). The data layer stays portable for a future Cinnamon frontend (Linux Mint — planned, not implemented yet).

## Problem / Why

The OpenCode Go console (`opencode.ai/console`) is the only place showing the three usage windows, which breaks flow. The user wants an always-visible, local indicator with the same numbers:

- **consumed %** (not remaining), per user's reference capture;
- reset countdowns;
- color coding (green / amber / red);
- subscription renewal date;
- bar shows all three windows as text: `5h X% · 7d Y% · 30d Z%` (user choice, 2026-10-01).

## Data source (verified live, 2026-10-01)

- Endpoint: `GET https://opencode.ai/console/api/go/status` — the same endpoint that feeds the console. Auth: `Authorization: Bearer <OpenCode OAuth access token>`. No extra headers required (`x-org-id` not needed).
- Credential: auto-discovered, **read-only**, from the OpenCode local DB `$XDG_DATA_HOME/opencode/opencode.db` (fallback `~/.local/share/opencode/opencode.db`) → table `credential` → `integration_id = 'opencode'` → `value` is JSON → field `access` (OAuth token; `expires` is ms epoch; OpenCode keeps it refreshed while in use).
  - Env overrides: `OCGO_TOKEN` (token), `OCGO_DB` (db path) — for manual/testing use.
- NOT used for now: `https://opencode.ai/zen/go/v1/usage` requires an `oc_sk_…` API key (not present on this machine). Keep as a future option.
- Live response (trimmed, values from the verified run):

```json
{"product":"go","access":{"endsAt":"2026-10-11T02:26:15.000Z",
  "meters":{
    "fiveHour":{"resetsAt":"2026-10-02T03:46:18.527Z","limitMicroCents":"1200000000","usedMicroCents":"18211143"},
    "week":{"resetsAt":"2026-10-05T00:00:00.000Z","limitMicroCents":"3000000000","usedMicroCents":"1909286550"},
    "month":{"limitMicroCents":"6000000000","usedMicroCents":"3471303267"}}}}
```

- Mapping:
  - `rolling` ← `fiveHour`, `weekly` ← `week`, `monthly` ← `month`.
  - Micro-cents: `1e-8` USD (1,200,000,000 = $12).
  - **percent = round(used / limit × 100), clamped 0–100** — single calibration function; adjust there if the console ever differs by ±1.
  - Monthly has **no `resetsAt`** → its countdown uses `access.endsAt` (subscription renewal, "Renews Oct 11").
  - Countdown format: `Xd Yh` / `Xh Ym` / `Xm` (e.g. `4h 24m`, `3d 0h`, `9d 3h`).
  - Colors: green < 50, amber 50–84, red ≥ 85 (tunable constants).

## Scope

In scope now:

- Core CLI `ocgo` (portable, Python 3 stdlib only).
- GNOME Shell extension: top-bar text indicator + popup with the three meters, countdowns, colors, manual refresh.
- Install / uninstall scripts + README + core unit tests.

Planned, not now:

- Cinnamon frontend (applet vs tray) — the core must stay desktop-agnostic.
- `oc_sk_…` / zen-endpoint support; threshold notifications; publishing to extensions.gnome.org.

## Constraints / Decisions

- Core: Python 3 stdlib only (no pip deps at runtime). Tests: `unittest` (pytest is NOT installed on this machine).
- Extension: GJS (ESM), `shell-version: ["50"]`, uuid `opencode-go-meter@martin.local` (local install; widen versions after testing).
- Cache: `$XDG_CACHE_HOME/ocgo/status.json` (fallback `~/.cache/ocgo/status.json`); schema v1 below; atomic writes; a failed refresh keeps the last good values and records `last_error`.
- CLI: `ocgo refresh` / `ocgo status [--json] [--no-color]` / `ocgo auth show` / `ocgo --version`. Root `Makefile`: `test` now; `install` / `uninstall` in T5 (no sudo — symlinks under `~/.local`).
- Refresh cadence: every ~5 min (extension-driven) + manual click.
- TDD mode: OFF (no project/session TDD config). Unit tests are ordinary verification.
- Delivery: `single-pr` (new local repo; no external gates). Work-unit commits on `feat/gnome-indicator`.
- RDD (gentle-ai review): off (global) — ordinary repository policy.
- Artifacts in English.

### Cache schema v1 (contract for the extension)

```json
{"schema":1,"fetched_at":"2026-10-01T23:30:00Z","last_error":null,"last_error_at":null,"product":"go",
 "renewal_ends_at":"2026-10-11T02:26:15Z",
 "windows":{
   "rolling":{"percent":3,"used_usd":0.3103,"limit_usd":12.0,"resets_at":"2026-10-02T03:46:18Z"},
   "weekly":{"percent":64,"used_usd":19.221,"limit_usd":30.0,"resets_at":"2026-10-05T00:00:00Z"},
   "monthly":{"percent":58,"used_usd":34.8412,"limit_usd":60.0,"resets_at":null}}}
```

Note: `used_usd` / `limit_usd` carry up to 4 decimals (do not assume a fixed number).

## Tasks

- [x] **T1 — Spike** *(route: inline — credential-sensitive)*: endpoint + credential verified live (HTTP 200; numbers match the console capture). Evidence: see Data source.
- [x] **T2 — Core CLI `ocgo`** *(route: delegated writer — 2+ non-trivial files)*: credentials (env > opencode DB), HTTP fetch, compute, cache, `refresh` / `status [--json]`, `auth show` (masked), error handling (no credential, expired, 401, network). Evidence: commits `ff91984`, `9df28eb`, `6eded03`, hardening `6bf2cb8`; `make test` 86 green; live smoke OK (rolling 3% · weekly 64% · monthly 58%); independent verification pass-with-findings → all fixed.
- [ ] **T3 — GNOME extension** *(route: delegated writer)*: metadata (uuid `opencode-go-meter@martin.local`, shell-version 50), top-bar label `5h X% · 7d Y% · 30d Z%` with per-figure colors, popup: header "OpenCode Go — Renews <date>", three rows (label, colored %, "Resets in …"; simple bar if clean to implement), footer "Updated Xm ago · Refresh". Reads cache; triggers `ocgo refresh` (5 min timer + click).
- [ ] **T4 — Extension ↔ core wiring** *(route: same writer as T3)*: cache path discovery, `ocgo` path resolution (`~/.local/bin/ocgo` default, pref override), stale/error state.
- [ ] **T5 — Install / uninstall** *(route: same writer as T3/T4)*: `make install` (CLI symlink `~/.local/bin/ocgo` + extension symlink into the GNOME extensions dir), `make uninstall`; README quickstart (Wayland note about enabling the extension).
- [ ] **T6 — Verification** *(route: parent, live)*: live `ocgo refresh` + `status` matching the console; extension visible after install; failure injection (no credential, network down, stale cache).
- [ ] **T7 — Docs** *(route: with T5)*: README final (install, security, architecture, Cinnamon note).
- [ ] **T8 — (Deferred)** Cinnamon frontend (applet vs tray) — out of current scope.

## Acceptance criteria

- Bar label shows consumed % for the three windows; popup shows countdowns + colors matching the console; refresh ≤ 5 min + on click.
- Values match the console (percent rounding per above).
- Failures: last good values are kept, `last_error` state is visible; never invented zeros; the token is never logged or cached.
- `make test` green; `make install` on Ubuntu 26.04 / GNOME 50 yields a working indicator (after enabling the extension).

## Checks

- `make test` (unittest).
- Live smoke (parent-run; the token is never printed): `core/bin/ocgo refresh && core/bin/ocgo status`.
- Manual: enable the extension, compare bar/popup against the console.

## Progress log

- 2026-10-01 — Repo scaffolded (commits on `main`); T1 verified live (console endpoint HTTP 200; numbers match the capture). Credential strategy: read-only from the opencode DB.
- 2026-10-01 — T2 closed: core CLI (`ff91984`, `9df28eb`, `6eded03`), hardening (`6bf2cb8`); `make test` 86 green; live smoke OK; independent verification pass → findings fixed.
- Next step: T3–T5 (GNOME extension + install/uninstall + docs) via delegated writer.
