# Testing

The test suite and the GNOME check are standard-library Python — nothing
third-party is installed to run them. The Cinnamon check additionally needs
Node on `PATH` for its `node --check` syntax pass. All commands run from the
repository root, and the same three checks run in CI on every push and pull
request. See [AGENTS.md](../AGENTS.md) for the
command headlines and the [architecture](01-architecture.md) for what the
checks protect.

## Commands

| Command | What it runs |
|---------|--------------|
| `make test` | `cd core && python3 -m unittest discover -s tests -v` |
| `make check-gnome` | `python3 gnome/scripts/check_collisions.py` |
| `make check-cinnamon` | `python3 cinnamon/scripts/check_applet.py` |
| `make deps` | `scripts/install-deps.sh` — the dependency check (not a test). |

## Test layout

`core/tests/` holds the whole suite: 235 tests, isolated from your real
environment and never hitting the network.

| File | Tests | Focus |
|------|-------|-------|
| `core/tests/test_api.py` | 34 | HTTP transport (injected, never live), console and zen payload mapping to cache schema v1, entitlement handling. |
| `core/tests/test_cache.py` | 12 | The single cache path, atomic IO, malformed-cache errors, the removed per-account surface. |
| `core/tests/test_cli.py` | 52 | The parser surface and every command (`refresh`, `status`, `auth show/set-key/clear-key/set-data-dir/clear-data-dir`), TTY color behavior, error paths. |
| `core/tests/test_creds.py` | 119 | Credential resolution order (env token, database, legacy `auth.json`, fallback key), `Credential.kind` detection, the configured and environment data directories, the `0600` `api.key` file, masking, store status. |
| `core/tests/test_format.py` | 18 | Pure helpers: percent, USD, countdown, ISO time. |
| `core/tests/_support.py` | — | Shared helpers (see below). |

## Conventions for new tests

- **Stdlib `unittest` only**; no pytest or third-party helpers in `core/tests/`.
- **Offline.** The HTTP transport is injected and mocked; a test must never
  open a network connection.
- **Environment isolation.** Tests pin `XDG_*` and `OCGO_*` variables into
  temporary directories; SQLite fixtures are temporary files. No keyring or
  external helper is involved — the fallback API key is a plain temporary
  file.
- **Temporary directories.** `_support.temp_dir()` prefers `/tmp/opencode`
  when it exists and falls back to the system temporary directory.
- **Placement.** Tests belong with the behavior they verify, in the same
  commit (see `skills/project-conventions/SKILL.md`).

## Static checkers

Two frontend-specific guards run where the JS lives:

- **`gnome/scripts/check_collisions.py`** flags names that are both an
  instance property (`this.name = …`) and a prototype method (`name() {`) in
  `extension.js`. That mix is the class of bug that once broke `enable()`,
  where `_panelBox` was both the panel container and a settings reader.
- **`cinnamon/scripts/check_applet.py`** validates that `metadata.json` and
  `settings-schema.json` parse as JSON, that `applet.js` passes
  `node --check` (Node is required for this check), that the metadata uuid
  matches the directory and the Makefile, that `main()` is defined, and that
  every `imports.*` module exists in the oldest supported Cinnamon (5.4); a
  new import must be verified against that release and added to the allowlist
  in the script.

## CI

`.github/workflows/test.yml` defines one job on `ubuntu-latest`, triggered on
push and pull requests:

```text
checkout → make test → make check-gnome check-cinnamon
```

There is no Python setup step: the runner's default `python3` is used, and the
project needs 3.10 or newer.

## Before opening a pull request

- [ ] `make test` is green.
- [ ] `make check-gnome` is green.
- [ ] `make check-cinnamon` is green.
- [ ] Tests were added or updated beside any core behavior change.
- [ ] User-facing behavior changes are reflected in the README or docs.
- [ ] English artifacts, Conventional Commits, no AI attribution, no secrets
      in the diff.

## Related

- [Architecture](01-architecture.md) — the invariants the suite protects.
- [CLI reference](02-cli-reference.md) — the command surface the CLI tests pin.
- [Frontends](03-frontends.md) — the checks and dialogs of both frontends.
