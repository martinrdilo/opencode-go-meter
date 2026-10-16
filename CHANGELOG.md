# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Reference documentation: the CLI reference, the frontends reference, and the
  testing guide under `docs/`.
- `make pack`, which builds the GNOME extension and Cinnamon applet release
  archives into the gitignored `dist/`.
- The versioning decision record (D11): SemVer, one source of truth for the
  version, annotated release tags, and a changelog.
- GitHub issue forms for bug reports and feature requests, plus a pull request
  template carrying the Chain Context section for stacked PRs.
- `CONTRIBUTING.md` (setup, checks, and conventions) and `SECURITY.md`
  (supported versions and the reporting channel), linked from the README.

## [0.1.0] - 2026-10-15

Initial release.

### Added

- GNOME Shell extension and Cinnamon applet showing OpenCode Go usage — the
  rolling 5-hour, weekly, and monthly windows — in the panel, color-coded by
  consumption.
- Popup with per-window reset countdowns, the subscription renewal date,
  manual refresh with the time of the last update, and account switching.
- Credits panel for OpenCode login accounts: the balance with its console
  states, the extra-usage switch, and the auto-recharge state.
- `ocgo` CLI: `refresh`, `status`, `auth show`, and account management, with
  `--json` and `--no-color` output, backed by an atomic local cache.
- Multi-account registry: multiple OpenCode Console logins as first-class
  accounts — auto (following the active OpenCode credential) or pinned to one
  stored login — plus API-key accounts, each with its own meters and credits.
- OpenCode credentials read read-only from the local OpenCode database and the
  legacy `auth.json` store.
- API keys stored in the OS keyring, with a 0600 file fallback when the
  keyring is unavailable.
- Installers (`make install`, `make install-cinnamon`) with a dependency check
  (`make deps`) that offers to install missing optional dependencies.
- Documentation: README, architecture overview, technical decision registry,
  `AGENTS.md`, and the project-conventions skill.

### Changed

- The Cinnamon applet supports Cinnamon 5.4 and newer (Linux Mint 21+), not
  only 6.4.

### Fixed

- Cinnamon login flow: the account dialog reopens reliably, the OpenCode
  binary is resolved inside the desktop session, and the login terminal
  reports failures honestly instead of a false success.
- First-run account setup when the OpenCode installation only has an API key.
- User-facing errors no longer leak the internal tool name, tool paths, or
  config paths.
- GNOME extension: a method/property name collision that broke enabling the
  extension.

[Unreleased]: https://github.com/martinrdilo/opencode-go-meter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/martinrdilo/opencode-go-meter/releases/tag/v0.1.0
