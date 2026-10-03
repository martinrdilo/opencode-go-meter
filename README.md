# opencode-go-meter

Always-visible OpenCode Go subscription usage (rolling 5h / weekly / monthly) on Linux desktops — starting with a GNOME Shell top-bar indicator, with the data layer kept portable for a future Cinnamon frontend (Linux Mint).

## Quickstart

```bash
make install
gnome-extensions enable opencode-go-meter@martin.local
ocgo status
```

`make install` is idempotent, needs no sudo, and only creates symlinks:

| What | Where |
|------|-------|
| `ocgo` CLI | `~/.local/bin/ocgo` → `core/bin/ocgo` |
| GNOME extension | `~/.local/share/gnome-shell/extensions/opencode-go-meter@martin.local` → `gnome/` |

The top bar then shows `5h 3% · 7d 64% · 30d 58%`; click it for countdowns, the renewal date, and a manual refresh. Pick the panel zone (left / center / right) and the order within it in the extension preferences. On Wayland, log out and back in if the indicator does not appear after enabling. `make uninstall` removes only links that point into this repo.

`ocgo status` sample:

```
Rolling usage    3%   Resets in 4h 24m
Weekly usage    64%   Resets in 3d 0h
Monthly usage   58%   Resets in 9d 3h
```

## Multiple accounts

`default` is your OpenCode app login, read **read-only** from its local database — nothing to configure. Named accounts use `oc_sk_…` API keys from the OpenCode console (workspace → API Keys); each keeps its own usage cache.

```bash
ocgo account add work --label "Work"   # key prompted hidden, validated against the API
ocgo account list
ocgo account use work
ocgo account set-key work              # replace / rotate a key
ocgo account remove work
ocgo refresh --all                     # refresh every account
```

In GNOME, the popup has an **Account** submenu (radio) to switch accounts; the panel always shows the active one. Preferences → **Accounts** manages the list, adds or replaces keys (typed in prefs, sent to the CLI over stdin), and removes accounts. Accounts without an active Go subscription can be registered — the popup shows the "no active OpenCode Go subscription" warning instead of breaking. Adding an account does not switch the active one.

## Layout

- `core/` — `ocgo`, the portable poller + CLI (Python 3, stdlib only): resolves the active account's credential, fetches usage, and caches it as JSON.
- `gnome/` — GNOME Shell extension: top-bar indicator + popup with the three meters.
- `odd/tasks/opencode-go-meter.md` — living plan, decisions, and verification evidence.

## Architecture

- `core/ocgo` owns credentials, the HTTP call, and the cache (`~/.cache/ocgo/status.json`, schema v1). Frontends read that cache and spawn `ocgo refresh`; they never touch credentials.
- The accounts registry is `~/.config/ocgo/accounts.json` (single source of truth for the list and the active account): metadata only — id, label, kind, masked hint, active.
- Cache paths: the default account keeps `~/.cache/ocgo/status.json` (no migration); named accounts use `~/.cache/ocgo/accounts/<id>/status.json`.
- `gnome/` is the first frontend. Cinnamon (applet vs tray) is planned and not implemented yet.

## Security

- The default credential is read **read-only** from the local OpenCode store; it is never logged, never cached, and only ever sent to `opencode.ai`.
- Named-account API keys live in the OS keyring (Secret Service via `secret-tool`) — never in dconf/GSettings, never in argv, never in the usage cache, never logged. Only masked hints (`oc_sk_…1b2c`) appear in `ocgo account list` and `ocgo auth show`.
- Fallback (only when no keyring is available): `--store file` keeps a key in a 0600 file under `~/.config/ocgo/keys/`; `OCGO_TOKEN_<ID>` overrides a stored key for testing or headless use.
- The cache file contains usage numbers only.
- The extension never reads credentials: it reads the cache and runs `ocgo refresh`; account switching runs `ocgo account use`.

## Data source

- `default` (OAuth): `GET https://opencode.ai/console/api/go/status` — the same endpoint that feeds the OpenCode console overview (product `go`).
- Named accounts (API key): `GET https://opencode.ai/zen/go/v1/usage` with `Authorization: Bearer oc_sk_…`.

Colors: green < 50%, amber 50–84%, red ≥ 85%.

## Status

Work in progress. See the task document for the plan and progress.
