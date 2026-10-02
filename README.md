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

The top bar then shows `5h 3% · 7d 64% · 30d 58%`; click it for countdowns, the renewal date, and a manual refresh. On Wayland, log out and back in if the indicator does not appear after enabling. `make uninstall` removes only links that point into this repo.

`ocgo status` sample:

```
Rolling usage    3%   Resets in 4h 24m
Weekly usage    64%   Resets in 3d 0h
Monthly usage   58%   Resets in 9d 3h
```

## Layout

- `core/` — `ocgo`, the portable poller + CLI (Python 3, stdlib only): discovers your local OpenCode credential, fetches usage from the OpenCode console API, and caches it as JSON.
- `gnome/` — GNOME Shell extension: top-bar indicator + popup with the three meters.
- `odd/tasks/opencode-go-meter.md` — living plan, decisions, and verification evidence.

## Architecture

- `core/ocgo` owns credentials, the HTTP call, and the cache (`~/.cache/ocgo/status.json`, schema v1). Frontends read that cache and spawn `ocgo refresh`; they never touch credentials.
- `gnome/` is the first frontend. Cinnamon (applet vs tray) is planned and not implemented yet.

## Security

- The credential is read **read-only** from the local OpenCode store; it is never logged, never cached, and only ever sent to `opencode.ai`.
- The cache file contains usage numbers only.
- The extension never reads the credential: it reads the cache and runs `ocgo refresh`.

## Data source

`GET https://opencode.ai/console/api/go/status` — the same endpoint that feeds the OpenCode console overview (product `go`). Colors: green < 50%, amber 50–84%, red ≥ 85%.

## Status

Work in progress. See the task document for the plan and progress.
