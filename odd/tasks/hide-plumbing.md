# Feature: hide-plumbing — no tool paths or tool errors in the UI; the installer resolves dependencies

**Status**: In progress — T1 done.
**Repo**: `opencode-go-meter`
**Branch**: `feat/hide-plumbing` (stacked on `fix/login-reliability` @ `acc6677`)
**Created**: 2026-10-15

## Objective

User request (2026-10-15, right after the keyring field report): nothing about the internal tool should ever reach the UI — no path field, no tool name, no raw tool errors — and the tool must be found at its default install path automatically. The installer must also resolve the project's dependencies instead of only creating symlinks.

1. The Cinnamon settings show an "ocgo command" field; the GNOME preferences show the same row.
2. User-visible strings name the internal CLI across both frontends: dialog description ("The key is sent to the ocgo CLI…"), helper errors ("ocgo not found…"), statuses ("ocgo account discover failed (exit 1)"), popup tooltips ("Accounts unavailable: ocgo not found"), the keyring offer (`~/.config/ocgo/keys`), tooltips ("with 'ocgo refresh'", "runs 'ocgo account use'"), and the login script filename (`ocgo-opencode-login.sh`) that appears in the terminal when a login fails.
3. `make install` / `make install-cinnamon` create symlinks and compile schemas but never check that python3 (required), the keyring tool (optional), the OpenCode CLI (optional, login flow) or `glib-compile-schemas` are available.

## Evidence

- Cinnamon — `settings-schema.json`: `ocgo-path` entry + tooltips at lines 14, 20, 39, 45. `applet.js` inventory: `492` settings bind, `944-945` errorMessage `'ocgo not found'`, `978` command label, `1302` script filename, `1375`/`1853` description copy, `1805` keyring offer path, `2077` helper-missing string, `2090` start failure, `2130-2137` `_ocgoPath()` (configured → local → PATH); popup tooltip lines `583-584`, `600-601`.
- GNOME — gschema `ocgo-path` key + refresh-interval description; `prefs.js` `18` resolver, `177-181` entry row + bind, `525`/`816` feedback strings, `809` `_failureMessage`; `extension.js` `926-932` resolver, `735`/`852`/`947` logError (diagnostics, stays).
- Makefile: `install` / `install-cinnamon` only symlink + `glib-compile-schemas`; CI runs `make test` and `make check-gnome check-cinnamon`.
- Internal/log-only mentions that stay: comments, `_ocgoCleanups`, the `ocgo-helper-buttons` style class, `CACHE_DIR = 'ocgo'`, `logError`/`console.error` diagnostics.

## Decisions (frozen)

- **Resolution, no setting (both frontends)**: `~/.local/bin/ocgo` first (the installer's standard target), then PATH. Remove the `ocgo-path` key from the Cinnamon schema and from the GNOME gschema (orphaned dconf values are harmless) and the GNOME preferences row + bind.
- **User-visible copy — the token "ocgo" never appears; no raw tool errors**:
  - API-key description: "The key is validated locally and is never stored by the applet."
  - Missing tool (dialog status, `_runAccountCommand` failure, the accounts/credentials errorMessage and popup tooltip lines): plain language + next step, e.g. "The meter's helper is not installed — re-run the installer, then restart Cinnamon." (GNOME: "…then restart GNOME Shell.")
  - Command-failure labels drop the binary prefix (e.g. `account discover failed (exit 1)`); "could not start the meter helper".
  - `_failureMessage` (both frontends) strips a leading `ocgo: ` from CLI details before mapping (the keyring marker is already handled by the two-step offer; the no-credential message keeps its mapping).
  - Keyring offer: drop the literal path → "…to keep the key in a private file that only your user can read —".
  - Login script filename → `opencode-login.sh`.
  - Tooltips reworded without tool commands (Cinnamon schema + GNOME gschema).
- **Installer resolves dependencies**: new `scripts/install-deps.sh` + `make deps`, a prerequisite of `install` and `install-cinnamon` (skippable with `SKIP_DEPS=1`):
  - python3 ≥ 3.10 — required; fail with guidance otherwise.
  - `secret-tool` / libsecret-tools — recommended; when missing and `apt-get` exists on an interactive tty, offer to install it (sudo); otherwise advise. Non-fatal: the app falls back to the local file store.
  - OpenCode CLI — optional (the applet's login button); resolve via PATH + the same candidate list the applet uses; advise only, never auto-install (third-party tool).
  - `glib-compile-schemas` — required for the GNOME install (libglib2.0-bin); check + advise.
  - `--check` mode: read-only report, never installs or prompts; exit 1 only when python3 is missing/old.
- README: a short Dependencies note in the install sections (required vs optional, and that the installer checks/resolves them). The CLI reference in the README stays (developer documentation, not the app UI).
- Out of scope: renaming the internal tool, `CACHE_DIR`, CSS classes, or log messages.

## Tasks

- [x] **T1 — Recon** *(route: parent)*: inventory above; contracts frozen.
- [ ] **T2 — Frontends: remove the path setting + neutralize user-visible strings** *(route: delegated writer; checks `make check-cinnamon`, `make check-gnome`, `node --check`, `make test`, live `:19` spot check)*: surfaces `cinnamon/applet.js`, `cinnamon/settings-schema.json`, `gnome/prefs.js`, `gnome/extension.js`, `gnome/schemas/org.gnome.shell.extensions.opencode-go-meter.gschema.xml`.
- [ ] **T3 — Installer: dependencies** *(route: delegated writer; checks `bash -n`, `--check` run on this box, simulated missing-tool paths, Makefile wiring review)*: surfaces `scripts/install-deps.sh` (new), `Makefile`, `README.md`.
- [ ] **T4 — Independent verification** *(route: fresh read-only verifier)*: the whole `feat/hide-plumbing` delta; grep-proof no user-visible string contains the tool token; live `:19` checks.
- [ ] **T5 — Delivery** *(route: parent + user)*: shared decision with `login-reliability` T5 (single PR vs sliced; push authorization pending).

## Acceptance criteria

- No settings surface asks for a tool path (Cinnamon + GNOME); resolution works via `~/.local/bin/ocgo` → PATH.
- No user-visible string in either frontend contains the tool name or a raw tool error; known failures map to plain-language messages.
- `make install` / `make install-cinnamon` report the dependency state and resolve what they can (libsecret-tools with consent), and never hang when non-interactive.
- Gates green: `make test`, `make check-cinnamon`, `make check-gnome`, `node --check`; live spot checks on the nested session.

## Forecast

≈ 250–400 authored lines (frontends ~100–180 including the gschema, installer ~120–200, README ~20). Same delivery vehicle as `login-reliability` (stacked branch).

## Progress log

- 2026-10-15 — User request (hide the plumbing; installer resolves dependencies); recon complete; branch `feat/hide-plumbing` from `acc6677`; contracts frozen.

---

Locator: odd/tasks/hide-plumbing.md (repo: opencode-go-meter)
