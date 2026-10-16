# Security policy

## Supported versions

The latest `main` is the supported line, and fixes land there. There are no
published releases yet; `v0.1.0` (the first release tag) will follow the same
policy once published.

## Reporting a vulnerability

Use the repository's **Security** tab to open a private report. If private
reporting is unavailable, contact the maintainers without including any
sensitive details until a private channel is agreed.

Never paste secrets — tokens, API keys, or credential JSON — into a report,
and redact them from logs and command output first.

## Scope

In scope:

- Credential handling: leakage of OpenCode logins or API keys through logs,
  argv, the usage cache, or the user interface.
- File permissions of the local stores: the `0600` API-key file fallback and
  the keyring usage.
- Cache and registry integrity: tampering or corruption that reaches the
  frontends.
- Sanitization: failures that surface internal tool names, paths, or secrets
  in user-facing messages.

Out of scope:

- The upstream OpenCode application and service, and the OpenCode Go
  subscription itself (https://opencode.ai).
