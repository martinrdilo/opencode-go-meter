---
name: project-conventions
description: "Trigger: editing core, ocgo, GNOME extension, Cinnamon applet, tests, docs. Repo rules for opencode-go-meter."
license: MIT
metadata:
  author: "martinrdilo"
  version: "1.0"
---

## Activation Contract

Load before changing `core/`, `gnome/`, `cinnamon/`, `docs/`, `odd/tasks/`, the Makefile, or CI.

## Hard Rules

Core:
1. Python 3 standard library only; no new runtime or test dependencies.
2. Sensitive logic stays in `core/ocgo/` (credentials, API calls, cache writes); secrets never reach argv, logs, cache, or frontends.
3. The cache JSON (schema 1) and the CLI surface are versioned contracts:
   version shape changes, keep older versions readable.

Frontends:
4. GNOME and Cinnamon stay thin — read the cache JSON, run `ocgo`, render; no credential access, no direct API calls.
5. Pass `make check-gnome` (method/property collisions) and `make check-cinnamon` (Cinnamon 5.4 imports).
6. Never invent values; empty and error states render explicitly.

Tests and checks:
7. Tests are `unittest` under `core/tests/`; no pytest or third-party helpers.
8. Run `make test`, `make check-gnome`, `make check-cinnamon`; all green.

Docs and commits:
9. English artifacts; Conventional Commits; no AI attribution.
10. One source of truth per rule: rules here, headlines in `AGENTS.md`, reference in `docs/`.
11. New public doc: `docs/NN-name.md`, next free number; new work: `odd/tasks/<feature>.md`.

## Decision Gates

| Change | Action |
|--------|--------|
| New CLI command | `core/ocgo/cli.py` + tests in `core/tests/` |
| New frontend | New top-level dir + Makefile targets; core unchanged |
| Credential behavior | Core only (`core/ocgo/creds.py`, `core/ocgo/cli.py`) |
| Cache/CLI shape | Bump the contract version; keep consumers working |
| User-facing behavior | Update `README.md` |
| New decision | Record it in `docs/05-technical-decisions.md` |

## Execution Steps

1. Identify the owning piece in `docs/01-architecture.md`.
2. Change the core first when behavior is shared.
3. Add or update tests beside every core change.
4. Run all three checks before finishing.
5. Update user docs in the same change; commit one work unit.

## Output Contract

Report changed files, the three check results, any contract version bump and why, and any decision recorded and where.

## References

- `docs/01-architecture.md` — pieces, invariants, folder rules.
- `docs/05-technical-decisions.md` — decision records and template.
- `Makefile` — install and check targets.
- `odd/tasks/project-scaffolding.md` — scaffolding feature tracker.
