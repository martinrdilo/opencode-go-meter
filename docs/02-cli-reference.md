# CLI reference

`ocgo` resolves credentials, calls the OpenCode console API, and writes the
cache the frontends read. This is the full command reference; install steps
live in the [README](../README.md), the command headlines in
[AGENTS.md](../AGENTS.md).

## Synopsis

```text
ocgo [-h] [--version] {refresh,status,auth,account} ...
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

## `ocgo refresh`

`ocgo refresh [-h] [--account ID | --all]` — fetch usage and rewrite the cache.
Without a flag it refreshes the active account; `--account ID` and `--all` are
mutually exclusive. Login accounts also fetch credits, best-effort: a billing
failure is recorded as `credits.error` without failing the refresh.

On success, one line per account:
`Refreshed OpenCode Go (<id>): rolling 42% · weekly 64% · monthly 88% · $3.25`
(the id is omitted for the seeded login without a registry file; the dollar
figure appears only when credits resolved). On failure the message goes to
stderr, the last good cache is kept with `last_error` recorded, and the exit
code is 1.

## `ocgo status`

`ocgo status [-h] [--json] [--no-color] [--account ID]` — show the cached
usage; `--account ID` picks a named account, otherwise the active one is used.

Default output, one row per window plus a credits row when the cache has one:

```text
Rolling usage   42%   Resets in 0m
Weekly usage    64%   Resets in 3d 23h
Monthly usage   88%   Resets in 15d 23h
Credits        $3.25   Running low
```

Countdowns use `Xd Yh` / `Xh Ym` / `Xm`; a missing timestamp prints `n/a` and a
past one `0m`. The monthly row counts down to the subscription renewal date.
The credits row prints `$X.XX`, optionally followed by `Running low` (prepaid
under $5 without healthy auto-recharge) or `No credits left` (zero balance); a
billing error prints `n/a   unavailable`. When `last_error` is set, a
`Warning: …` line goes to stderr and the rows keep the last good values.

`--json` prints the cache file verbatim and exits; it is the raw stored JSON
(see the [architecture](01-architecture.md) for the schema). Without a cache
yet, both modes fail with exit 1 and point at `ocgo refresh`.

## `ocgo auth show`

`ocgo auth show [-h] [--account ID]` — show the credential source for the
account, masking the token (first six and last four characters, or `…` for
short values):

```text
Source:  OpenCode local database
Token:   abcd12…wxyz
Expires: 2026-11-01T00:00:00Z (in 15d 23h)
```

`Expires` appears only when the credential carries an expiry. For an API-key
account the source reads `stored API key (account '<id>')`; the token is the
registry hint.

## `ocgo account add`

`ocgo account add [-h] [--label LABEL] [--store {auto,file}] [--from-db]
[--credential ID_OR_LABEL] ID` — register an account. The id is 1–64 characters
matching `[a-z0-9][a-z0-9._-]*`; `--label` defaults to the id. Without
`--from-db` the command reads an API key — hidden prompt on a terminal, one
line from stdin otherwise — validates it against the console API, stores it,
and registers an `api-key` account. A valid key without an active subscription
is still stored, with a note on stderr.

- `--store auto` (default) stores the key in the OS keyring through
  `secret-tool` (fails when unavailable); `--store file` stores it in an opt-in
  0600 file under the config directory.
- `--from-db` registers the local OpenCode login instead of an API key, with no
  prompt; with `--credential ID_OR_LABEL` it pins one stored login (exact id
  first, then exact label; an ambiguous label is an error).

## `ocgo account set-key`

`ocgo account set-key [-h] [--store {auto,file}] ID` — replace the API key of
an existing account (same key input and store choices as `add`). When the
account is a login account it is converted in place to an `api-key` account,
keeping the id, label, and active state and freeing the login slot.

## `ocgo account list`

`ocgo account list [-h] [--json]` — list accounts, marking the active one with
`*`:

```text
* work         Work  (api-key, ocgo_s…1234)
  default      Default  (opencode-db)
```

`--json` prints a document with `schema`, `active`, and `accounts[]` (`id`,
`label`, `kind`, `hint`, `active`, `credential_id`). With none configured it
prints `no accounts configured` and exits 0.

## `ocgo account discover`

`ocgo account discover [-h] [--json]` — list the OpenCode credentials in the
local database (never tokens): `id`, `label`, `active`, `email`, then the
database path. `--json` adds a `store` block with the checked paths and whether
a login exists. With none present it prints `no OpenCode credentials found in
<path>` (exit 0) and mentions the legacy `auth.json` when that file exists.

## `ocgo account activate-in-opencode`

`ocgo account activate-in-opencode [-h] ID` — make a pinned login the
credential `opencode auth switch` marks active, by running
`opencode auth switch opencode <credential-id>` (10-second timeout; `opencode`
must be on PATH). Only pinned logins qualify: an `api-key` account and the auto
login (which already follows the active credential) fail with exit 1.

## `ocgo account use`

`ocgo account use [-h] ID` — switch the account shown by the meter. Prints
`Active account: <id>`.

## `ocgo account remove`

`ocgo account remove [-h] ID` — remove the account. An `api-key` account's
secret is deleted first; its cache file is cleaned best-effort (a failed
cleanup is a warning, not an error). Removing the last account leaves the list
empty.

## Environment variables

| Variable | Effect |
|----------|--------|
| `OCGO_TOKEN` | Manual login token; wins over the OpenCode stores for login accounts. |
| `OCGO_TOKEN_<ID>` | API key for account `<id>`: the id uppercased with non-alphanumerics mapped to `_` (`work-2` → `OCGO_TOKEN_WORK_2`). Wins over the keyring and file backends. |
| `OCGO_DB` | Overrides the OpenCode database path. |
| `NO_COLOR` | Any non-empty value disables ANSI colors in `status`. |
| `XDG_CACHE_HOME` | Cache root; default `~/.cache`. |
| `XDG_CONFIG_HOME` | Registry and key-store root; default `~/.config`. |
| `XDG_DATA_HOME` | OpenCode store root; default `~/.local/share`. |

## File locations

| Path | What lives there |
|------|------------------|
| `$XDG_CACHE_HOME/ocgo/status.json` | Cache for the default account (`accounts/<id>/status.json` for named accounts). |
| `$XDG_CONFIG_HOME/ocgo/accounts.json` | Accounts registry (version 3). |
| `$XDG_CONFIG_HOME/ocgo/keys/<id>.key` | `--store file` secret, written 0600. |
| OS keyring (`secret-tool`, service `ocgo`, account `<id>`) | `--store auto` secret. |
| `$XDG_DATA_HOME/opencode/opencode.db` | OpenCode logins, read-only. |
| `$XDG_DATA_HOME/opencode/auth.json` | Legacy OpenCode login store, read-only. |

Secrets never appear in argv, logs, the registry, or the cache; the registry
stores masked hints only.

## Examples

```bash
# Everyday use
ocgo status
ocgo refresh
ocgo auth show

# Machine-readable output for scripts
ocgo status --json
ocgo account list --json

# Register accounts
ocgo account add work --label "Work"                # API key, prompted hidden
ocgo account add personal --from-db                  # the auto OpenCode login
ocgo account add pinned --from-db --credential CREDENTIAL_ID

# Point the meter at another account
ocgo account use work

# Manual override for testing
OCGO_TOKEN=placeholder-token ocgo refresh
```

## Related

- [Architecture](01-architecture.md) — the pieces and the cache contract.
- [Technical decisions](05-technical-decisions.md) — why credentials behave
  the way they do.
- [README](../README.md) — install and uninstall.
