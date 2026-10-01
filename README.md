# opencode-go-meter

Always-visible OpenCode Go subscription usage (rolling 5h / weekly / monthly) on Linux desktops — starting with a GNOME Shell top-bar indicator, with the data layer kept portable for a future Cinnamon frontend (Linux Mint).

## Layout

- `core/` — `ocgo`, the portable poller + CLI (Python 3, stdlib only): discovers your local OpenCode credential, fetches usage from the OpenCode console API, and caches it as JSON.
- `gnome/` — GNOME Shell extension: top-bar indicator + popup with the three meters.
- `odd/tasks/opencode-go-meter.md` — living plan, decisions, and verification evidence.

## Data source

`GET https://opencode.ai/console/api/go/status` — the same endpoint that feeds the OpenCode console overview (product `go`).

## Privacy

- The credential is read **read-only** from the local OpenCode store; it is never logged, never cached, and only ever sent to `opencode.ai`.
- The cache file contains usage numbers only.

## Status

Work in progress. See the task document for the plan and progress.
