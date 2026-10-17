# CLI reference

`ocgo` resolves a single credential, calls the matching OpenCode API, and
writes the cache the frontends read. This is the full command reference;
install steps live in the [README](../README.md), the command headlines in
[AGENTS.md](../AGENTS.md).

## Synopsis

```text
ocgo [-h] [--version] {refresh,status,auth} ...
```

The subcommand is required. `core/bin/ocgo` is the entry point; `make install`
links it into `~/.local/bin/ocgo`.

## Global behavior

| Item | Behavior |
|------|----------|
| `--version` | Prints `ocgo 0.1.0` and exits 0. |
| `-h`, `--help` | Usage and flag help for every parser level. |
| Exit 0 | Success. |
| Exit 1 | A handled failure; the reason is printed as `ocgo: <message>` on stderr. |
| Exit 2 | Usage error from argparse (unknown command or flag, missing argument). |

`status` colors each row green below 50%, amber 50–84%, red at 85% and above
(consumed use). Colors appear only when stdout is a terminal; `--no-color` or a
non-empty `NO_COLOR` disables them.

## Credential resolution

Every command that needs a credential resolves it in one order:

1. `OCGO_TOKEN` — a manual token, treated as `oauth`.
2. The local OpenCode store under the effective data directory: the database
   first (`opencode.db`), then the legacy `auth.json`. A stored credential is
   `oauth` when it carries `access` and `api` when it carries `key`.
3. The fallback API key at `$XDG_CONFIG_HOME/ocgo/api.key` (`api`), used only
   when the store has no usable (non-expired) credential.

The effective OpenCode data directory is `OCGO_DATA_DIR`, else
`opencode_data_dir` from `$XDG_CONFIG_HOME/ocgo/config.json`, else
`$XDG_DATA_HOME/opencode` (`~/.local/share/opencode`); `OCGO_DB` overrides the
database path directly.

## `ocgo refresh`

`ocgo refresh [-h]` — resolve the credential, fetch usage, and rewrite the
cache. An `oauth` credential hits the console status endpoint; an `api`
credential hits the zen usage endpoint.

On success one line:
`Refreshed OpenCode Go: rolling 42% · weekly 64% · monthly 88%` (one percent
per window, `n/a` when a value is missing). On failure the message goes to
stderr, the last good cache is kept with `last_error` and `last_error_at`
recorded beside it, and the exit code is 1.

## `ocgo status`

`ocgo status [-h] [--json] [--no-color]` — show the cached usage.

Default output, one row per window:

```text
Rolling usage   42%   Resets in 0m
Weekly usage    64%   Resets in 3d 23h
Monthly usage   88%   Resets in 15d 23h
```

Countdowns use `Xd Yh` / `Xh Ym` / `Xm`; a missing timestamp prints `n/a` and a
past one `0m`. The monthly row counts down to the subscription renewal date
because the monthly meter has no reset timestamp. When `last_error` is set, a
`Warning: …` line goes to stderr and the rows keep the last good values.

`--json` prints the cache file verbatim and exits; it is the raw stored JSON
(see the [architecture](01-architecture.md) for the schema). Without a cache
yet, both modes fail with exit 1 and point at `ocgo refresh`.

## `ocgo auth show`

`ocgo auth show [-h] [--json]` — show where the credential comes from, masking
the token:

```text
Source:  OpenCode local database
Token:   abcd12…wxyz
Expires: 2026-11-01T00:00:00Z (in 15d 23h)
```

The token hint keeps the first six and last four characters (a token of 12
characters or fewer is fully hidden as `…`); `Expires` appears only when the
credential carries an expiry. The possible sources are `OCGO_TOKEN
environment`, `OpenCode local database`, `OpenCode auth.json file`, and
`Configured API key`.

When nothing resolves, the command prints `Source:  none` and the error on
stderr, with exit 1. `--json` prints a schema 1 document:

- `credential` — `source`, `kind` (`oauth` or `api`), `token_hint`,
  `expires_at` (ISO 8601 or `null`), or `null` when nothing resolves.
- `store` — `db_path`, `db_exists`, `auth_json_path`, `auth_json_exists`,
  `auth_json_login`, `has_login`, `data_dir`, `configured_data_dir`,
  `api_key_configured`, `api_key_hint`.

## `ocgo auth set-key`

`ocgo auth set-key [-h] [--stdin]` — read a fallback API key, verify it
against the zen endpoint, store it in `$XDG_CONFIG_HOME/ocgo/api.key` (0600
permissions), and refresh the cache right away. `--stdin` reads one line from
stdin; on a terminal without it the prompt is hidden.

A key rejected with HTTP 401, or a network failure, is never stored. A valid
key without an active Go subscription is stored with a note on stderr
(`this account has no active OpenCode Go subscription`). Empty input fails
with `no API key provided`.

## `ocgo auth clear-key`

`ocgo auth clear-key [-h]` — remove the stored fallback API key. Prints
`Cleared the stored API key`, or `No stored API key to clear` when there was
none.

## `ocgo auth set-data-dir`

`ocgo auth set-data-dir [-h] PATH` — persist `opencode_data_dir` in
`$XDG_CONFIG_HOME/ocgo/config.json` (a `~` is expanded) so the store and the
legacy file are read from there. The path must be an existing directory
(`not a directory: <path>` otherwise). Prints `OpenCode data directory set
to <path>`.

## `ocgo auth clear-data-dir`

`ocgo auth clear-data-dir [-h]` — remove `opencode_data_dir` from
`config.json` and go back to auto-detection. Prints `OpenCode data directory
reset to the default`.

## Environment variables

| Variable | Effect |
|----------|--------|
| `OCGO_TOKEN` | Manual credential, treated as `oauth`; wins over the OpenCode stores and the fallback key. |
| `OCGO_DB` | Overrides the OpenCode database path directly. |
| `OCGO_DATA_DIR` | Overrides the effective OpenCode data directory (wins over `config.json`). |
| `NO_COLOR` | Any non-empty value disables ANSI colors in `status`. |
| `XDG_CACHE_HOME` | Cache root; default `~/.cache`. |
| `XDG_CONFIG_HOME` | `config.json` and `api.key` root; default `~/.config`. |
| `XDG_DATA_HOME` | Default OpenCode store root; default `~/.local/share`. |

## File locations

| Path | What lives there |
|------|------------------|
| `$XDG_CACHE_HOME/ocgo/status.json` | The usage cache (schema 1). |
| `$XDG_CONFIG_HOME/ocgo/config.json` | `opencode_data_dir`, when configured. |
| `$XDG_CONFIG_HOME/ocgo/api.key` | Fallback API key, written 0600. |
| `$XDG_DATA_HOME/opencode/opencode.db` | OpenCode logins, read-only. |
| `$XDG_DATA_HOME/opencode/auth.json` | Legacy OpenCode login store, read-only. |

Secrets never appear in argv, logs, or the cache; the only secret file is
`api.key` (0600), and `status --json` prints usage numbers only.

## Examples

```bash
# Everyday use
ocgo status
ocgo refresh
ocgo auth show

# Machine-readable output for scripts
ocgo status --json
ocgo auth show --json

# Configure a fallback API key from a pipe
printf '%s\n' "$OPENCODE_API_KEY" | ocgo auth set-key --stdin

# Point the meter at an OpenCode store kept elsewhere
ocgo auth set-data-dir ~/backup/opencode
ocgo auth clear-data-dir

# Manual override for testing
OCGO_TOKEN=placeholder-token ocgo refresh
```

## Related

- [Architecture](01-architecture.md) — the pieces and the cache contract.
- [Technical decisions](05-technical-decisions.md) — why credentials behave
  the way they do.
- [README](../README.md) — install and uninstall.
