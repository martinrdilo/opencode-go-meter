# Frontends

Two thin desktop frontends render the same cache the core writes: a GNOME
Shell extension and a Cinnamon applet. Both read the cache JSON and run `ocgo`
for actions; neither touches credentials or the network (see the
[architecture](01-architecture.md)). Installation and uninstallation stay in
the [README](../README.md).

## Compatibility matrix

| | GNOME | Cinnamon |
|---|-------|----------|
| Uuid | `opencode-go-meter@martinrdilo` | `opencode-go-meter@martinrdilo` |
| Supported desktop | GNOME Shell 50 | Cinnamon 5.4+ (Linux Mint 21+) |
| Metadata | `shell-version: ["50"]`, `version: 13` | `cinnamon-version: ["5.4"]`, `max-instances: 1`, no version field |
| Modules | ESM `resource:///…` imports | legacy `imports.*` with a Cinnamon 5.4 allowlist |
| Settings storage | GSettings schema `org.gnome.shell.extensions.opencode-go-meter` | `settings-schema.json` applet settings |
| Settings UI | Adwaita preferences page (Extensions app or `gnome-extensions prefs`) | applet settings window |
| Popup footer | `Updated <ago>` and `Refresh` as separate rows | one `Updated <ago> · Refresh` row |
| Tooltip | none | yes, on the applet |

## What you see

Both frontends show the consumed percentage per window, colored green below
50%, amber 50–84%, and red at 85% and above (the thresholds are mirrored
constants of the core, see
[technical decisions](05-technical-decisions.md)).

**Panel.** `5h 42% · 7d 64% · 30d 88%`. Without a cache the GNOME extension
shows the explicit empty label `Go —`; the Cinnamon applet shows `—` when no
account is active and `5h — · 7d — · 30d —` with an account but no cache yet.

**Popup.** The header names the account and the subscription renewal date
(`OpenCode Go — Renews Nov 1`, or `OpenCode Go · Work — Renews Nov 1` for a
named account). Below it: a warning row when the last refresh failed
(`Last refresh failed: … · data from <ago>`), then one row per window —
`Rolling usage`, `Weekly usage`, `Monthly usage` — each with its percent and a
`Resets in …` countdown. When credits are enabled and present: `Credits`,
`Extra usage` (On/Off), and `Auto-recharge` rows; a low balance reads
`Running low` (amber), a zero balance `No credits left` (red), and a recorded
billing error `Unavailable`. An Account submenu switches accounts. The footer
shows when the cache was last updated and hosts the manual refresh.

The Cinnamon applet additionally mirrors the header, update age, and last error
into its panel tooltip, and its account dialog offers making a pinned login the
credential OpenCode itself uses.

## GNOME settings

Schema: `gnome/schemas/org.gnome.shell.extensions.opencode-go-meter.gschema.xml`
(compiled by `make install`).

| Key | Type | Default | Range / values | Preferences row |
|-----|------|---------|----------------|-----------------|
| `refresh-interval` | int | 300 | 60–86400 (seconds) | Refresh interval (seconds) |
| `panel-box` | string | `right` | `left`, `center`, `right` (unknown values fall back to `right`) | Panel → Zone |
| `panel-position` | int | 0 | -1–30; -1 appends last | Panel → Order in the zone |
| `show-credits` | bool | false | — | Popup → Show credits |

The preferences page also carries the Accounts group: the active account
picker, `Remove account`, `Make active in OpenCode`, and the add/replace form
(account id, label, type, OpenCode credential, API key).

## Cinnamon settings

Schema: `cinnamon/settings-schema.json`, applied through Cinnamon's applet
settings framework.

| Key | Type | Default | Range / values |
|-----|------|---------|----------------|
| `refresh-interval` | spinbutton | 300 | 30–3600, step 30 (seconds) |
| `show-credits` | checkbox | false | — |
| `active-account` | combobox | `""` (No accounts) | Options come from the CLI's account list |
| `accounts-apply-button` | button | — | Add / replace key… |
| `accounts-remove-button` | button | — | Remove account… |
| `accounts-activate-button` | button | — | Use the selected login in OpenCode… |

The buttons run dialog flows backed by `ocgo`; the applet stores no secrets in
its settings.

## Cinnamon 5.4 vs 6.4

The applet supports both the oldest release and current Cinnamon, so it carries
explicit compatibility measures:

- A local `MessageContent` component replaces `imports.ui.dialog`, which only
  exists from Cinnamon 6.4.
- Box spacing is set through the inner `Clutter.BoxLayout`, because
  `St.BoxLayout` exposes no `spacing` property on 5.4 or 6.4.
- On close, the dialog is destroyed explicitly when the 6.4 auto-destroy is not
  in play, so 5.4 (where `close()` only hides) does not leak the hidden actor.
- Dialog buttons carry both theme classes (`dialog-button` and
  `modal-dialog-button`).

`make check-cinnamon` guards the import allowlist; see [testing](04-testing.md).

## Troubleshooting

- **Enable or disable (GNOME).** `gnome-extensions enable
  opencode-go-meter@martinrdilo` / `gnome-extensions disable
  opencode-go-meter@martinrdilo`. On Wayland, log out and back in if the
  indicator does not appear (README).
- **Open the settings.** GNOME: `gnome-extensions prefs
  opencode-go-meter@martinrdilo`, or the Extensions app. Cinnamon:
  `xlet-settings applet opencode-go-meter@martinrdilo`, or the applet's
  settings entry in Cinnamon.
- **Dependencies.** `make deps` runs the dependency check alone; the installers
  run it first (`SKIP_DEPS=1` skips it).
- **Stale or empty values.** The frontends refresh through `ocgo`; to do it
  from a terminal run `ocgo refresh` ([CLI reference](02-cli-reference.md)).
  Popup and tooltip show the update age and the last error, and the panel keeps
  the last good values.
- **Meter stays empty.** Both frontends look for `ocgo` at `~/.local/bin/ocgo`
  first and then on `PATH`; when it is missing they log `ocgo not found` and
  keep the last values. Install it with `make install`.
- **Credits missing.** Credits need an OpenCode login account (API-key accounts
  have no billing access) and the `show-credits` setting enabled.

## Related

- [Architecture](01-architecture.md) — pieces, data flow, invariants.
- [CLI reference](02-cli-reference.md) — the command-line half of the story.
- [Testing](04-testing.md) — the static checks both frontends must pass.
