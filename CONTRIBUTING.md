# Contributing

`opencode-go-meter` shows OpenCode Go subscription usage in the Linux desktop
panel: a Python 3 core (`ocgo`, standard library only) and two thin frontends
— a GNOME Shell extension and a Cinnamon applet. This guide covers setup, the
checks every change must pass, and the conventions this repository follows.

If you are new to the codebase, read the
[architecture overview](docs/01-architecture.md) first — the pieces, the data
flow, and where new things go.

## Setup

```bash
git clone https://github.com/martinrdilo/opencode-go-meter
cd opencode-go-meter
make deps
```

- **Python 3.10+** is required; `make deps` verifies it (see
  `scripts/install-deps.sh`).
- To install the app on your desktop, follow the [README](README.md) quick
  start instead of repeating it here.
- The test suite and the GNOME check need no third-party packages; the
  Cinnamon check needs Node (`node --check`).

## The checks

Run all three from the repository root before opening a pull request — this is
what CI runs on every push and pull request:

| Command | What it runs |
|---------|--------------|
| `make test` | the `unittest` suite under `core/tests/` |
| `make check-gnome` | GNOME extension static checks |
| `make check-cinnamon` | Cinnamon applet static checks |

`make deps` runs the dependency check the installers run; it is not a test.
See the [testing guide](docs/04-testing.md) for what each file covers and how
CI works.

## Conventions

- **English artifacts.** Code, comments, docs, commit messages, and UI copy
  are English.
- **Conventional Commits.** `type: summary`, for example
  `docs: update the CLI reference`.
- **No AI attribution.** No `Co-Authored-By` trailers or generated-by notes.
- **Core stays stdlib-only.** `core/` and `core/tests/` use the Python 3
  standard library — no new runtime or test dependencies.
- **Frontends stay thin.** The GNOME and Cinnamon code reads the usage cache
  and runs `ocgo`; no credential access, no direct API calls.
- **Work-unit commits.** One deliverable per commit, with tests and docs in
  the same commit as the behavior they cover.

## Pull requests

1. Branch from `main`.
2. Run the three checks and fix any failure.
3. Fill in the pull request template: the type of change and every checklist
   item.
4. Keep the diff focused on one work unit.

For stacked or chained PRs, fill in the **Chain Context** section of the
template (chain name, base branch, position, review budget) so reviewers can
see where the slice sits in the chain.

## Versioning and releases

- The version policy is [decision D11](docs/05-technical-decisions.md):
  SemVer, with `__version__` in `core/ocgo/__init__.py` as the single source
  of truth.
- User-visible changes are recorded in [CHANGELOG.md](CHANGELOG.md).
- `make pack` builds the GNOME and Cinnamon release archives into the
  gitignored `dist/`.

## Questions

Open an issue — bug report and feature request forms are available. For
security reports, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue.
