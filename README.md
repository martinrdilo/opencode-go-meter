# opencode-go-meter

Always-visible OpenCode Go subscription usage (rolling 5h / weekly / monthly) on Linux desktops — a GNOME Shell top-bar indicator and a Cinnamon panel applet (Linux Mint), both reading the same portable data layer.

## Quickstart

### GNOME Shell

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

### Cinnamon

```bash
make install-cinnamon
ocgo status
```

`make install-cinnamon` is idempotent, needs no sudo, and only creates symlinks:

| What | Where |
|------|-------|
| `ocgo` CLI | `~/.local/bin/ocgo` → `core/bin/ocgo` |
| Cinnamon applet | `~/.local/share/cinnamon/applets/opencode-go-meter@martin.local` → `cinnamon/` |

Then add the applet: right-click the panel → **Add applets to the panel**, or open **Cinnamon Settings → Applets**, and pick "OpenCode Go Meter". Cinnamon lets you drag the applet to position it in the panel. The panel then shows `5h 3% · 7d 64% · 30d 58%`; click it for countdowns, the renewal date, account switching, and a manual refresh. The applet gear (Cinnamon Settings → Applets, or Configure in its context menu) sets the refresh interval and the `ocgo` command path. `make uninstall-cinnamon` removes only links that point into this repo.

`ocgo status` sample:

```
Rolling usage    3%   Resets in 4h 24m
Weekly usage    64%   Resets in 3d 0h
Monthly usage   58%   Resets in 9d 3h
```

## Multiple accounts

The account list is fully yours: add, switch, and remove any account — including the seeded `default` (your OpenCode app login, read **read-only** from its local database). API-key accounts use `oc_sk_…` keys from the OpenCode console (workspace → API Keys); each account keeps its own usage cache.

```bash
ocgo account add work --label "Work"   # key prompted hidden, validated against the API
ocgo account list
ocgo account use work                  # any account can be the shown one
ocgo account set-key work              # replace / rotate a key
ocgo account remove default            # the seeded default is removable too
ocgo refresh --all                     # refresh every account
```

A fresh install seeds `default` automatically; once `~/.config/ocgo/accounts.json` exists it is authoritative. Every account is added with its api-key — the seeded `default`, once removed, comes back only by adding that account's console api-key. Remove every account and the meter shows an empty state — a dash in the panel and "No accounts configured" in the popup; nothing is invented. Adding the first account to an empty list makes it active automatically; otherwise adding does not switch the active one.

In GNOME, the popup's **Account** submenu (radio) switches accounts and stays available in the empty state; the panel always shows the active one. Preferences → **Accounts** manages the list, adds or replaces API keys (typed in prefs, sent to the CLI over stdin), and removes any account. Accounts without an active Go subscription can be registered — the popup shows the "no active OpenCode Go subscription" warning instead of breaking.

## Layout

- `core/` — `ocgo`, the portable poller + CLI (Python 3, stdlib only): resolves the active account's credential, fetches usage, and caches it as JSON.
- `gnome/` — GNOME Shell extension: top-bar indicator + popup with the three meters.
- `cinnamon/` — Cinnamon applet: panel label + popup (countdowns, renewal date, account switching) and its settings schema.
- `odd/tasks/opencode-go-meter.md` — living plan, decisions, and verification evidence.

## Architecture

- `core/ocgo` owns credentials, the HTTP call, and the cache (`~/.cache/ocgo/status.json`, schema v1). Frontends read that cache and spawn `ocgo refresh`; they never touch credentials.
- The accounts registry is `~/.config/ocgo/accounts.json` (schema v2, authoritative once it exists): the list and the active account (`active` may be `null`) — metadata only: id, label, kind, masked hint, active. A fresh install seeds `default`; removing it is permanent.
- `ocgo account list --json` emits schema 2; an empty list and a `null` active account are valid.
- Cache paths: the `default` id keeps `~/.cache/ocgo/status.json` (no migration); every other id uses `~/.cache/ocgo/accounts/<id>/status.json`.
- `gnome/` and `cinnamon/` are the two shipped frontends (GNOME Shell extension and Cinnamon applet); both only read the cache and run the CLI.

## Security

- OpenCode login credentials are read **read-only** from the local OpenCode store; they are never logged, never cached, and only ever sent to `opencode.ai`.
- API-key accounts store their key in the OS keyring (Secret Service via `secret-tool`) — never in dconf/GSettings, never in argv, never in the usage cache, never logged. Only masked hints (`oc_sk_…1b2c`) appear in `ocgo account list` and `ocgo auth show`.
- Fallback (only when no keyring is available): `--store file` keeps a key in a 0600 file under `~/.config/ocgo/keys/`; `OCGO_TOKEN_<ID>` overrides a stored key for testing or headless use.
- The cache file contains usage numbers only.
- The extension never reads credentials: it reads the cache and runs `ocgo refresh`; account switching runs `ocgo account use`.

## Data source

- OpenCode login accounts (OAuth): `GET https://opencode.ai/console/api/go/status` — the same endpoint that feeds the OpenCode console overview (product `go`).
- API-key accounts: `GET https://opencode.ai/zen/go/v1/usage` with `Authorization: Bearer oc_sk_…`.

Colors: green < 50%, amber 50–84%, red ≥ 85%.

## Status

Work in progress. See the task document for the plan and progress.
