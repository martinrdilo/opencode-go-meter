# AGENTS.md

`opencode-go-meter` shows OpenCode Go subscription usage (rolling 5h, weekly,
monthly) in the Linux desktop panel: a GNOME Shell extension and a Cinnamon
applet, both powered by the portable `ocgo` CLI — Python 3, standard library
only.

## Map

| Path | What it holds |
|------|----------------|
| `core/` | `ocgo` CLI, credentials, cache, tests |
| `gnome/` | GNOME Shell 50 extension |
| `cinnamon/` | Cinnamon 5.4+ applet |
| `docs/` | Human reference docs, numbered |
| `odd/tasks/` | Feature tracking, one file per feature |
| `skills/` | Agent convention skills |
| `Makefile` | Install, uninstall, and check targets |

## Commands

- `make test` — Python `unittest` suite (`core/tests/`).
- `make check-gnome` / `make check-cinnamon` — frontend static checks.
- `make install` / `make install-cinnamon` — symlink installs, no sudo.
- `ocgo status` / `ocgo refresh` — everyday CLI usage.

## Non-negotiables

- Core is Python 3, standard library only.
- Credentials live only in the core; no secrets in logs, argv, cache, or frontends.
- Frontends stay thin: read the cache, run `ocgo`, render.
- Cache JSON and the accounts registry are versioned contracts.
- Never invent values; empty and error states are explicit.
- English artifacts, Conventional Commits, no AI attribution.

## Skills

- **project-conventions** — repo edit rules for core, frontends, tests, docs.
  Path: [skills/project-conventions/SKILL.md](skills/project-conventions/SKILL.md)
  Trigger: editing core, ocgo, GNOME extension, Cinnamon applet, tests, or docs.

## Docs

- [docs/01-architecture.md](docs/01-architecture.md) — pieces, data flow,
  invariants, where new things go.
- [docs/02-cli-reference.md](docs/02-cli-reference.md) — every `ocgo` command,
  flag, environment variable, and file location.
- [docs/03-frontends.md](docs/03-frontends.md) — GNOME and Cinnamon behavior,
  settings, compatibility.
- [docs/04-testing.md](docs/04-testing.md) — the test suite, static checkers,
  and CI.
- [docs/05-technical-decisions.md](docs/05-technical-decisions.md) — decision
  records and the template for new ones.
