# Technical decisions

This file is the registry for decisions that shaped `opencode-go-meter`. Each
record states what was decided, why, and where the code embodies it. Records
are append-only: if a decision changes, add a new record that supersedes the
old one and say so.

To add a record: copy the template at the bottom, use the next free id, and
keep each field to a short paragraph.

### D1 — The core stays Python 3 stdlib-only

**Decision**: The core and its tests use only the Python 3 standard library —
no runtime dependencies, no test dependencies, no packaging step.

**Why**: The core must run on any Linux desktop as-is. `core/bin/ocgo` is a
plain script, the frontends only need a path to it, and nothing has to be
installed beyond Python 3 itself.

**Where**: `core/ocgo/`, `core/bin/ocgo`, `core/tests/`.

### D2 — OpenCode logins are read from their local credential stores, read-only; no OAuth implementation

**Decision**: Login-account tokens are read from OpenCode's local credential
stores — the database, falling back to the legacy `auth.json` file — opened
read-only (the active credential, or a pinned one). Token
refresh and expiry recovery stay OpenCode's job: when the stored credential is
expired, the app reports it and waits for OpenCode to refresh it. `OCGO_TOKEN`
and `OCGO_DB` environment variables exist as manual overrides for testing.

**Why**: Re-implementing OAuth would duplicate OpenCode's session handling,
drift out of sync, and touch refresh tokens the app should never own.

**Where**: `core/ocgo/creds.py`.

### D3 — API keys live in the OS keyring with a 0600 file fallback

**Decision**: API keys are stored in the OS keyring through `secret-tool`;
`--store file` writes an opt-in 0600 file under the config directory instead.
Secret values never appear in argv, logs, exception messages, the registry,
or the cache — the registry stores masked hints only. An `OCGO_TOKEN_<ID>`
environment variable takes precedence for manual use.

**Why**: OpenCode does not store API keys, so the app must; the OS keyring is
the desktop-native secret store, and the file backend keeps the CLI usable on
systems without `secret-tool`.

**Where**: `core/ocgo/accounts.py`, `core/ocgo/cli.py`.

### D4 — The cache JSON is the contract between core and frontends

**Decision**: Schema v1 fields: `schema`, `fetched_at`, `last_error`,
`last_error_at`, `product`, `renewal_ends_at`, `windows.rolling/weekly/monthly`
(`percent`, `used_usd`, `limit_usd`, `resets_at`), plus `credits` and
`extra_usage` for login accounts. Writes are atomic (temp file then rename).
A failed refresh keeps the last good values and records `last_error` and
`last_error_at` beside them. Default account:
`$XDG_CACHE_HOME/ocgo/status.json`; named accounts:
`.../ocgo/accounts/<id>/status.json`.

**Why**: Frontends need a stable, cheap read path that keeps working when a
refresh fails; a versioned shape allows growth without breaking consumers.

**Where**: `core/ocgo/cache.py`, `core/ocgo/api.py`.

### D5 — The CLI is the port; frontends never touch credentials or the API

**Decision**: The frontends read the cache JSON for values and run `ocgo` for
actions (refresh, account list and discovery, switching). Account data crossing
into the UI is display metadata from the CLI's JSON output, never a secret.

**Why**: One implementation of the sensitive paths keeps them reviewable and
keeps each frontend small; a third frontend would cost only a renderer.

**Where**: `gnome/extension.js`, `cinnamon/applet.js`, `core/ocgo/cli.py`.

### D6 — Meter math is calibrated in one place; colors follow fixed thresholds

**Decision**: Usage percent is `round(used / limit × 100)`, clamped to 0–100,
computed in a single function — the only calibration point if the console ever
disagrees. Colors: green below 50, amber 50–84, red at 85 and above. The
thresholds are named constants (`AMBER_AT`/`RED_AT`) defined in the core and
mirrored in each frontend because rendering is local; they move together.
Countdown formatting (`Xd Yh` / `Xh Ym` / `Xm`) is defined in the core and
mirrored in both frontends like the color thresholds; the monthly row counts
down to the subscription renewal date because the monthly meter has no reset
timestamp.

**Why**: Console parity is an acceptance criterion; one formula prevents the
CLI and the two frontends from drifting apart.

**Where**: `core/ocgo/format.py`, `gnome/extension.js`, `cinnamon/applet.js`.

### D7 — Accounts are a versioned registry: N accounts, `auto` or `pinned` logins

**Decision**: `$XDG_CONFIG_HOME/ocgo/accounts.json` holds accounts with stable
ids, a label, a kind, and the active account. Kinds: `opencode-db` — a stored
OpenCode login that either follows the credential OpenCode marks active (auto,
at most one account) or pins one credential id — and `api-key`. The registry
is versioned (version 3 today): absent, v1, and v2 registries are upgraded in
memory on load, and the next mutation writes version 3.

**Why**: The model grew from a single seeded `default` account (v1) to
user-owned multi-account (v3); in-memory upgrades keep existing installs
working without a migration step.

**Where**: `core/ocgo/accounts.py`, `core/ocgo/cache.py`.

### D8 — Symlink-only installs, with a dependency check first

**Decision**: `make install` links `core/bin/ocgo` into `~/.local/bin` and the
GNOME extension into the extensions directory; `make install-cinnamon` links
the applet the same way. Both targets run a dependency check first
(`scripts/install-deps.sh`; `make deps` runs it alone, `SKIP_DEPS=1` skips
it): Python 3.10+ is required, and the optional dependencies are only ever
installed with explicit consent — that consent step is the only place sudo
may be used. Uninstall removes only links that point into this repository and
leaves anything foreign alone.

**Why**: A checkout stays the source of truth — the running app updates as the
checkout does — and nothing is copied into system directories.

**Where**: `Makefile`, `scripts/install-deps.sh`.

### D9 — All checks are standard-library Python

**Decision**: `make test` runs the `unittest` suite under `core/tests/`;
`make check-gnome` and `make check-cinnamon` run the static checkers in each
frontend's `scripts/`. CI runs all three on push and pull requests.

**Why**: No third-party tooling to install or version; the checks run wherever
Python 3 does, same as the core. The checkers encode frontend-specific
guards, such as method/property collisions in the extension.

**Where**: `Makefile`, `core/tests/`, `gnome/scripts/check_collisions.py`,
`cinnamon/scripts/check_applet.py`, `.github/workflows/test.yml`.

### D10 — Documentation lives on four surfaces, one source of truth per rule

**Decision**: `AGENTS.md` is always loaded (map, commands, headlines);
`skills/` holds on-demand operational rules; `docs/` is the human reference;
`odd/tasks/` tracks features. Other surfaces point at the source of truth
instead of restating it.

**Why**: Agents and humans read different surfaces; duplicating a rule
guarantees the copies eventually contradict each other.

**Where**: `AGENTS.md`, `skills/project-conventions/SKILL.md`, `docs/`,
`odd/tasks/`.

## Template

```markdown
### Dnn — Title

**Decision**: What was decided, in one paragraph.

**Why**: The constraint or tradeoff that drove it.

**Where**: `path/to/file` — the code that embodies it.
```

## Related

- [Architecture](01-architecture.md) — the pieces, invariants, and folder rules.
- [AGENTS.md](../AGENTS.md) — the agent-facing map and non-negotiables.
