# Feature: compact-usage — compact panel and popup usage display

**Status**: COMPLETE — pushed to `main` at `44f83e9` (2026-10-22; pending live UI confirmation)
**Repo**: `opencode-go-meter`
**Branch**: `feat/compact-usage` (stacked on `refactor/simplify-auth` @ `6ee8c9a`)
**Created**: 2026-10-21

## Objective

The panel is too long and the popup feels too large and spread out. Make both
frontends read like the Cloud app's compact meter:

- Panel: drop the `5h` / `7d` / `30d` window labels, keep the three consumed
  percentages, and show the rolling session's reset countdown in parentheses
  after its percentage: `0% (4h 58m) · 16% · 37%`.
- Popup: keep the three reset countdowns, compact them into parentheses
  (`(4h 58m)`, `(5d 8h)`, `(21d 10h)`), drop the `Resets in` prefix, and tighten
  the columns and the vertical spacing.

## Specs

- **S1. Panel**: GNOME and Cinnamon render `0% (4h 58m) · 16% · 37%` in rolling,
  weekly, monthly order, with the existing color thresholds. Only the rolling
  percentage carries `(countdown)`.
- **S2. Panel empty state**: both frontends show `Go —` without a cache. The
  Cinnamon `5h — · 7d — · 30d —` variant is retired with the labels.
- **S3. Popup rows**: keep the `Rolling usage` / `Weekly usage` / `Monthly usage`
  labels, the colored percentage, and a parenthesized countdown on every row.
  The monthly row still counts down to `renewal_ends_at`; rolling and weekly use
  `resets_at`.
- **S4. Popup density**: no `Resets in` prefix; compact row padding/spacing and
  narrowed label, percent, and countdown columns.
- **S5. Unknown values**: `—` and `(—)` stay explicit; never invent a value.
- **S6. Docs and contracts**: README and `docs/03-frontends.md` describe the new
  display; the cache schema (v1) and the CLI output are unchanged.

## Tasks

- [x] **T1 — Frontend rendering and styling** (GNOME + Cinnamon): panel labels,
  popup rows, CSS. Route: inline. DONE 2026-10-21, commit `4330bd7`.
- [x] **T2 — Docs and changelog**: README, `docs/03-frontends.md`, `CHANGELOG.md`.
  Route: inline. DONE 2026-10-21.
- [x] **T3 — Checks**: `make test`, `make check-gnome`, `make check-cinnamon`,
  `make pack`; render spot check against the live cache. Route: inline.
  DONE 2026-10-21.

## Log

- L1 — User request (2026-10-21, verbatim excerpts): "Yo quiero que en nuestra
  aplicación saquemos la información que dice '5 horas', '7 días' y '30 días'
  porque es irrelevante. [...] pondríamos el tiempo solamente en la sesión de 5
  horas y de nuestra sesión actual [...] nos quedaría entre paréntesis el tiempo
  que nos falta para renovar la sesión actual."
- L2 — User request (2026-10-21, verbatim excerpt): "cuando se presiona el
  botón, la aplicación queda como un poco extenso, grande, espaciado. Las
  columnas del uso de la tabla que hay ahí, se podría achicar un poquito."
- L3 — User decision (2026-10-21): popup option 1 — keep all three reset times,
  compact in parentheses, and shrink the columns.
- L4 — Implementation (2026-10-21): GNOME and Cinnamon render `0% (countdown) ·
  weekly% · monthly%` in the panel; both popups show three `(countdown)` rows
  with compact padding and narrower columns; Cinnamon's empty panel state is
  now `Go —`, matching GNOME. Live cache spot check produced the expected
  `0% (4h 38m) · 17% · 37%` and popup `(4h 38m)` / `(4d 9h)` / `(20d 12h)`.
  `make test` 235 OK, `make check-gnome`, `make check-cinnamon`, and `make pack`
  green.
- L5 — Delivery (2026-10-22): merged `feat/compact-usage` into `main` with merge
  commit `44f83e9` and pushed `main` to `origin`; checks re-run green on the
  merged tree.

## Next step

Confirm the compact layout live in GNOME Shell and Cinnamon.
