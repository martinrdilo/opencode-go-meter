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

The applet supports Cinnamon 5.4 and newer (Linux Mint 21 and up).

If the applet reports **OpenCode was not found** when you press *Log in with OpenCode…*, the desktop session cannot see your OpenCode install. Install OpenCode for that user, or run `opencode auth login` in a terminal where `opencode` works, then press Refresh in the applet.

### Dependencies

Both installers run a dependency check first:

- **python3 3.10+** — required.
- **libsecret-tools** — optional (the OS keyring). Without it the app stores API keys in a private local file that only your user can read. When it is missing, the check offers to install it with your consent; that is the only step that may ask for sudo.
- **OpenCode CLI** — optional; only the *Log in with OpenCode…* button needs it. Install from https://opencode.ai.
- **glib-compile-schemas** (`libglib2.0-bin` on Mint/Ubuntu) — needed by `make install` to compile the GNOME schema.

Run the check alone with `make deps`, or skip it with `SKIP_DEPS=1 make install-cinnamon`. The installers only create symlinks, are safe to re-run, and uninstall with `make uninstall` / `make uninstall-cinnamon` — they remove only links pointing into this repo.

## Usage

- Panel colors: green < 50%, amber 50–84%, red ≥ 85%.
- Terminal: `ocgo status` for the same view, `ocgo refresh` to update now.

## Credits

When the active account is the OpenCode login, the popup also mirrors the console's credits panel: the balance with its console state (`Running low` under $5, `No credits left` at zero), the extra-usage switch, and the auto-recharge state. `ocgo status` adds the same `Credits` row.

API-key accounts show the meters only — the console API rejects API keys for billing (HTTP 403) and the zen endpoint has no credits data. To see credits, keep an OpenCode login as the shown account (`ocgo account use <login-id>`). Show or hide the section from the settings (GNOME: Preferences → Popup → Show credits; Cinnamon: applet settings → Show credits).

## Accounts

A fresh install starts from what OpenCode already has: when a login is stored locally, the seeded `default` account uses it (read **read-only**); with API keys only, the meter starts empty (`No accounts configured`), and adding one from the settings registers the key account under any free id, including `default`. The add flow offers both kinds: OpenCode logins — one per credential stored by `opencode auth login` (`ocgo account discover` lists them) — and API-key accounts from the OpenCode console (`oc_sk_…`). A login is either **auto** (follows the credential OpenCode marks active via `opencode auth switch`) or **pinned** to one stored credential; every login shows its own meters and credits, independent of which credential OpenCode is using. `--from-db` registers the stored login and fails when there is none; for an API key omit it and pass the id and label directly: `ocgo account add <id> --label "<label>"`. Switch between accounts or replace keys:

```bash
ocgo account discover                              # list the OpenCode logins stored locally
ocgo account add personal --from-db                # register the auto login (follows opencode auth switch)
ocgo account add work --from-db --credential Work  # pin a specific stored login
ocgo account add temp --label "Temp"               # API key: prompted hidden, validated against the API
ocgo account activate-in-opencode work             # make a pinned login OpenCode's active account
ocgo account use work                              # switch the account shown by the app
ocgo account set-key temp                          # replace / rotate a key, or convert a login to an API key
ocgo account remove temp                           # remove an account
ocgo refresh --all                                 # refresh every account
```

Stored logins stay valid for about a month; one that OpenCode has not used for that long shows as expired until it is used again — make it active (`ocgo account activate-in-opencode`) and use OpenCode once. Token refresh stays OpenCode's job: the app never implements OAuth.

With no accounts configured the panel shows a dash and the popup explains — nothing is invented.

![Managing accounts in the GNOME extension preferences](docs/screenshots/gnome-preferences.png)

## Security

- Credentials are handled only by `ocgo`: the OpenCode login is read from its local store in read-only mode; API keys live in the OS keyring (0600 file fallback) — never in logs, argv, or the usage cache.
- The GNOME and Cinnamon frontends never touch credentials: they read the usage cache and run the CLI.
- Requests go only to `opencode.ai`; the cache holds usage and credit numbers only.

## License

MIT — see [LICENSE](LICENSE).
