# opencode-go-meter

[![tests](https://github.com/martinrdilo/opencode-go-meter/actions/workflows/test.yml/badge.svg)](https://github.com/martinrdilo/opencode-go-meter/actions/workflows/test.yml)

OpenCode Go subscription usage in your panel — rolling 5-hour, weekly, and monthly meters, always visible.

- **GNOME Shell** — top-bar indicator with popup (countdowns, renewal date, account switching).
- **Cinnamon** — panel applet with the same popup and a settings page.

![OpenCode Go meters in the GNOME top bar and popup](docs/screenshots/gnome-popup.png)

## Install

### GNOME Shell

```bash
git clone https://github.com/martinrdilo/opencode-go-meter
cd opencode-go-meter
make install
gnome-extensions enable opencode-go-meter@martinrdilo
```

The top bar shows `5h 3% · 7d 64% · 30d 58%`. Click it for countdowns, the renewal date, and a manual refresh. On Wayland, log out and back in if it doesn't appear.

### Cinnamon

```bash
git clone https://github.com/martinrdilo/opencode-go-meter
cd opencode-go-meter
make install-cinnamon
```

Then right-click the panel → **Add applets to the panel** → **OpenCode Go Meter**.

The installers only create symlinks (no sudo), are safe to re-run, and uninstall with `make uninstall` / `make uninstall-cinnamon` — they remove only links pointing into this repo.

## Usage

- Panel colors: green < 50%, amber 50–84%, red ≥ 85%.
- Terminal: `ocgo status` for the same view, `ocgo refresh` to update now.

## Credits

When the active account is the OpenCode login, the popup also mirrors the console's credits panel: the balance with its console state (`Running low` under $5, `No credits left` at zero), the extra-usage switch, and the auto-recharge state. `ocgo status` adds the same `Credits` row.

API-key accounts show the meters only — the console API rejects API keys for billing (HTTP 403) and the zen endpoint has no credits data. To see credits, keep the OpenCode login active (`ocgo account use <login-id>`). Show or hide the section from the settings (GNOME: Preferences → Popup → Show credits; Cinnamon: applet settings → Show credits).

## Accounts

A fresh install uses your local OpenCode login (read **read-only**). The add flow offers both kinds — the OpenCode login (the default when none is registered; sign in with `opencode auth login` first if you are logged out) and API-key accounts from the OpenCode console (`oc_sk_…`). Switch between accounts or replace keys:

```bash
ocgo account add personal --from-db    # register the local OpenCode login (no API key)
ocgo account add work --label "Work"   # key prompted hidden, validated against the API
ocgo account use work                  # switch the shown account
ocgo account set-key work              # replace / rotate a key
ocgo account remove work               # remove an account
ocgo refresh --all                     # refresh every account
```

With no accounts configured the panel shows a dash and the popup explains — nothing is invented.

![Managing accounts in the GNOME extension preferences](docs/screenshots/gnome-preferences.png)

## Security

- Credentials are handled only by `ocgo`: the OpenCode login is read from its local store in read-only mode; API keys live in the OS keyring (0600 file fallback) — never in logs, argv, or the usage cache.
- The GNOME and Cinnamon frontends never touch credentials: they read the usage cache and run the CLI.
- Requests go only to `opencode.ai`; the cache holds usage and credit numbers only.

## License

MIT — see [LICENSE](LICENSE).
