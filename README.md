# opencode-go-meter

[![tests](https://github.com/martinrdilo/opencode-go-meter/actions/workflows/test.yml/badge.svg)](https://github.com/martinrdilo/opencode-go-meter/actions/workflows/test.yml)

OpenCode Go subscription usage in your panel — rolling 5-hour, weekly, and
monthly meters, always visible. A GNOME Shell extension and a Cinnamon applet,
backed by one portable Python core.

## Quick start

### GNOME Shell

```bash
git clone https://github.com/martinrdilo/opencode-go-meter
cd opencode-go-meter
make install
gnome-extensions enable opencode-go-meter@martinrdilo
```

The installer is safe to re-run and never copies files into system
directories. On Wayland, log out and back in if the indicator does not appear.

### Cinnamon

```bash
git clone https://github.com/martinrdilo/opencode-go-meter
cd opencode-go-meter
make install-cinnamon
```

Then right-click the panel → **Add applets to the panel** → **OpenCode Go
Meter**. The applet supports Cinnamon 5.4 and newer (Linux Mint 21 and up).

Uninstall with `make uninstall` / `make uninstall-cinnamon` — they remove only
links pointing into this repository.

### Dependencies

Both installers run a dependency check first:

- **python3 3.10+** — required.
- **glib-compile-schemas** (`libglib2.0-bin` on Mint/Ubuntu) — needed by
  `make install` to compile the GNOME schema.

Run the check alone with `make deps`, or skip it with
`SKIP_DEPS=1 make install-cinnamon`.

## What you see

The panel shows the three windows as percentages in rolling, weekly, monthly
order, with the rolling session's reset countdown in parentheses:
`0% (4h 58m) · 16% · 37%`. Figures are consumed percentages, colored green
below 50%, amber 50–84%, red at 85% and above.

Click the indicator for the popup: each window with its percentage and a
parenthesized reset countdown, the subscription renewal date in the header, and
a manual refresh with the time of the last update. The popup shows the three Go
usage windows only; the console's credits and auto-recharge panel is not
mirrored.

In the terminal, `ocgo status` prints the three windows with their consumed
percentages and reset countdowns, and `ocgo refresh` updates the data now. When
a refresh fails, the panel keeps the last good values and the popup explains the
error — nothing is invented.

## Credentials

The meter works zero-config: it reads the OpenCode login already on your
machine from OpenCode's local store (`~/.local/share/opencode/opencode.db`,
falling back to the legacy `auth.json`) and refreshes usage from it. An
OpenCode login is read in read-only mode and drives the console status
endpoint; an API key stored by OpenCode drives the Zen usage endpoint.
`OCGO_DATA_DIR`, or a configured data directory, points the meter at a store
kept elsewhere.

When no usable OpenCode login is present, you can store a single fallback API
key. `ocgo auth` covers both cases:

```bash
ocgo auth show                            # credential source and store status
ocgo auth set-data-dir ~/opencode-data    # use a custom OpenCode data directory
ocgo auth clear-data-dir                  # back to auto-detection
ocgo auth set-key --stdin                 # read the fallback API key from stdin
ocgo auth clear-key                       # remove the stored fallback API key
```

`ocgo auth set-key` verifies the key with OpenCode first and then stores it in
`~/.config/ocgo/api.key` with `0600` permissions; the key is used only while
the local store has no usable credential. The GNOME preferences and the
Cinnamon applet settings expose the same actions, and the key always travels
to the CLI over stdin. On a terminal, `ocgo auth set-key` prompts for it
hidden.

OpenCode logins carry their own expiry. When the stored login has expired the
meter reports it and waits: use OpenCode once so it refreshes its login, then
press Refresh.

## Security

- Credentials are handled only by `ocgo`: the OpenCode login is read from
  OpenCode's local stores in read-only mode, and the fallback API key lives in
  a private `0600` file under `~/.config/ocgo` — never in logs, argv, or the
  usage cache.
- The GNOME and Cinnamon frontends never touch credentials: they read the usage
  cache and run the CLI. The API key travels to the CLI over stdin only.
- Requests go only to `opencode.ai`; the cache holds usage numbers only.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Development

```bash
make test            # Python unittest suite (core/tests)
make check-gnome     # GNOME extension static checks
make check-cinnamon  # Cinnamon applet static checks
make deps            # dependency check (also run by the installers)
```

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) covers the setup, the checks,
and the conventions.

See [AGENTS.md](AGENTS.md) for the agent-facing map and non-negotiables, and
[docs/01-architecture.md](docs/01-architecture.md) for the design.

The full CLI, frontend, and testing references: [docs/02-cli-reference.md](docs/02-cli-reference.md), [docs/03-frontends.md](docs/03-frontends.md), [docs/04-testing.md](docs/04-testing.md).

Release history: [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
