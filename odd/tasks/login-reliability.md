# Feature: login-reliability — fourth field-report round (Cinnamon: login terminal + credential detection)

**Status**: Code complete and independently verified (T1–T4 and T6–T7 PASS WITH FINDINGS; the MINOR findings fixed, NITs accepted); delivery open — **PR #8** against `main`, CI green 2026-10-15; stacked slice `feat/hide-plumbing` = **PR #9**; merge pending the user.
**Repo**: `opencode-go-meter`
**Branch**: `fix/login-reliability` (from `main` @ `171159a`)
**Created**: 2026-10-14

## Objective

Field report 4 (same Mint/Cinnamon user, right after PR #5 merged) — the OpenCode login path still fails on the field machine and the account dialog misleads:

1. "Log in with OpenCode…" opens a terminal that dies with `opencode: not found` (script line 2). The script runs bare `opencode` because `GLib.find_program_in_path('opencode')` fails in the desktop session (the opencode binary lives in `~/.opencode/bin` — reachable from the user's shell, not from the session). The terminal still prints "Login finished. You can close this window." (unconditional `printf`) — a false success.
2. The dialog says "No OpenCode login found on this machine." although the user is signed in with OpenCode on that machine. The applet/CLI only read the SQLite `credential` table; OpenCode's legacy store is `~/.local/share/opencode/auth.json` (OpenCode's own v2 migration `20260805200742_import_legacy_credentials` imports exactly that file). The message never names the store it checked, so the mismatch is not diagnosable from the UI.
3. "Use the selected login in OpenCode…" pressed with nothing selected opens a dense explainer (image 3); the user asked what the button is even for.
4. User verdict: adding the login "terminó siendo más complicado que dejarlo solo por API Key".
5. **Field report 4b (same session)**: adding an API key fails on the field machine with the raw CLI error `ocgo: secret-tool is not available — install libsecret-tools to use the keyring, or use the 'file' backend (--store file)`. The machine has no `libsecret-tools`, so the GUI's `--store auto` path dead-ends with a CLI-level instruction the user cannot act on from the dialog.

## Evidence

### Field report 4 (2026-10-14)

- Image 1: settings → "Add / replace key…" dialog; helper "No OpenCode login found on this machine. Log in below, or add an API-key account."; Type: "OpenCode login" (disabled) / "API key" (selected); status after clicking login: "Terminal opened — complete the login in your browser. If no window appeared, the command is on your clipboard."
- Image 2: terminal: `/run/user/1000/ocgo-opencode-login.sh: 2: opencode: not found` + `Login finished. You can close this window.`
- Image 3: "Use in OpenCode" explainer with "No account is selected above. …".
- Image 4 (report 4b): "Add / replace account key" dialog, API key type, empty key entry, red status `ocgo: secret-tool is not available — install libsecret-tools to use the keyring, or use the 'file' backend (--store file)`.
- Narrative: "estoy trabajando en una máquina en la cual ya estoy conectado con OpenCode" — the applet does not connect; the user does not understand the "not found" error nor the Use-in-OpenCode button; and adding an API key fails with the keyring error above.

### Code evidence (verified 2026-10-14, main @ 171159a; parent recon)

- `cinnamon/applet.js:1215-1218` — `const resolved = GLib.find_program_in_path('opencode');` then `command = resolved ? '<path>' : 'opencode'`: when the desktop-session PATH lacks the user's opencode dir, the script falls back to bare `opencode`.
- `cinnamon/applet.js:1219-1220` — the exit status of `auth login` is ignored; the wrapper always prints "Login finished.".
- `core/ocgo/creds.py` — DB-only store (`default_db_path`, `list_db_credentials`, `_resolve_db_credential`). No legacy `auth.json` support anywhere in the repo. `NO_CREDENTIAL_MESSAGE` names no path.
- Applet helper text (`applet.js:1285-1290`, `1364-1372`) — never names the store the CLI checked.
- `accounts.py` `store_secret(backend="auto")` errors with `_NO_SECRET_TOOL_MESSAGE` when `secret-tool` is absent (deliberate contract, pinned by `test_auto_without_keyring_raises`); both frontends pass `--store auto` (`cinnamon/applet.js` submit path, `gnome/prefs.js:678`). The opt-in file backend lives at `~/.config/ocgo/keys/<id>.key` (0600).
- Desktop-session reality (this box, verified): opencode at `~/.opencode/bin/opencode`, nothing in `/usr/bin`; the Cinnamon applet process inherits the session PATH (`/proc/<cinnamon>/environ`), which on a stock desktop misses `~/.opencode/bin`. The OpenCode desktop app installs to `/opt/OpenCode` with no CLI shim (`dpkg` package `opencode`).
- Image 1's exact helper text (the non-error variant) proves the CLI's `account discover` exited 0 with a zero-credential list — the database exists but holds no `integration_id='opencode'` row, which is the legacy-`auth.json` signature.

### Local harness (reusable for live checks)

- Nested Cinnamon 6.4 session alive on Xephyr `:19` (`cinnamon --x11 --sm-disable`), sandbox `HOME=/tmp/opencode/cinnamon-test/home` with `opencode.db` hardlinked to the real store, `XDG_RUNTIME_DIR=/tmp/opencode/cinnamon-test/runtime`, applet directory symlinked to the repo `cinnamon/`.
- Tools: `/tmp/opencode/cinnamon-test/eval.sh "js"` (gdbus Eval inside the session), `shot.sh /path/out.png` (screenshot), `logs/cinnamon.log`.
- Do NOT complete a real `opencode auth login` inside the harness (the store is hardlinked to the real one).

## Decisions (frozen contracts)

- **Login script binary resolution**, in order: session PATH → `~/.opencode/bin/opencode` → `~/.local/bin/opencode` → `~/bin/opencode` → `~/.bun/bin/opencode` → `~/.npm-global/bin/opencode` → `/usr/local/bin/opencode` → `/usr/bin/opencode` → `/snap/bin/opencode`. The script always prepends `$HOME/.opencode/bin:$HOME/.local/bin:$HOME/bin` to PATH and runs the resolved absolute path when found.
- **Login script honesty** (POSIX `sh`): `exit 0` → "Login finished. You can close this window."; `exit 127` → an "OpenCode was not found" line pointing at installing it or running the login where `opencode` works, then Refresh in the applet; any other status → "The OpenCode login did not finish (exit code N)."; always end with "Press Enter to close this window." + `read -r _` so the window stays open.
- **Unresolved binary in the applet**: do NOT open a terminal; keep the clipboard copy; status: OpenCode was not found + the manual escape hatch (run `opencode auth login` where it works, then press Refresh).
- **Legacy store support (core)**: `creds.py` gains `default_auth_json_path()` (same `XDG_DATA_HOME` rule as opencode) and a tolerant legacy reader: entry for integration `opencode` (trailing slashes trimmed, matching opencode's own migration) with `type == "oauth"` → token `access`, expires `expires`; `type == "api"` → token `key`. `resolve_credential(credential_id=None)`: DB first; on `CredentialError`, fall back to the legacy login. Pinned ids never fall back. `has_stored_login()` counts the legacy login too.
- **Discover JSON (additive; schema stays 1)**:
  ```json
  "store": {
    "db_path": "...", "db_exists": true,
    "auth_json_path": "...", "auth_json_exists": false,
    "auth_json_login": false, "has_login": true
  }
  ```
  The CLI's human-readable output names the checked path(s), including when the listing is empty.
- **Applet guided state**: parse `store` tolerantly (missing store → today's behavior). `store.has_login` allows the AUTO binding when the legacy login is the only one (empty credentials list). The no-login helper gains a second wrapped line naming the checked paths (`$HOME` shortened to `~`). On dialog open the applet reloads accounts/credentials and refreshes the guided state in place (no stale "no login found"; the login poll stays).
- **Keyring-less API-key storage (report 4b)**: the CLI contract stays as is (`auto` = keyring-or-error, `file` = explicit opt-in). The Cinnamon add dialog gains a two-step explicit fallback: when the CLI fails with the `secret-tool is not available` marker, the dialog keeps the key in the entry, explains the situation, relabels the confirm button to **Store in a local file**, and re-submits with `--store file` on the next click (the key goes to `~/.config/ocgo/keys/<id>.key`, 0600). Switching the type resets the offer. GNOME parity for both the login affordance and the keyring-less storage remains a documented follow-up.
- **Use in OpenCode copy**: keep the action; shorten the explainer to purpose + next step (two variants: nothing selected / selected-not-pinned). No behavior change.
- No new settings this round; the manual escape hatch is "run `opencode auth login` where it works, then Refresh".

## Tasks

- [x] **T1 — Recon** *(route: parent)*: done 2026-10-14. Diagnosis above; contracts frozen; harness located.
- [x] **T2 — Core: legacy store + discover `store` block** *(route: delegated writer; strict TDD, runner `make test`)*: DONE 2026-10-14, commit `2e7571b` (5 files, +687/−18). RED observed (`Ran 453 tests, failures=11, errors=13` pre-implementation; expiry-gate follow-up `Ran 459 tests, failures=4`), GREEN `Ran 459 tests — OK` (parent spot check re-ran `make test` OK). Legacy `auth.json` fallback for unpinned resolution with expiry gating (`EXPIRED_MESSAGE`), presence semantics unchanged, `store_status()` + discover JSON `store` block (schema 1 additive), missing database is now a state (exit 0) while a corrupt existing database still exits 1, CLI text output names the checked path(s).
- [x] **T3 — Cinnamon: script + guided-state truth + copy** *(route: delegated writer; checks `make check-cinnamon`, `node --check`, live `:19`)*: DONE 2026-10-14, commits `02303bb` + `95ad0f1` (applet.js +220/−56 total, README +2). Candidate-list binary resolution + PATH-prepending script with exit-status branches (0 / 127 / other) and Enter-to-close; unresolved binary no longer opens a doomed terminal; `store` parsing + `_storeHasLogin()` gating + "Looked in:" line + silent dialog-open reload + poll legacy detection; Use-in-OpenCode explainer rewritten. Live evidence: generated script content correct + `sh -n` OK; all three branches exercised with fake binaries; empty-store dialog shows "Looked in: ~/.local/share/opencode/opencode.db" (`T3B-empty-store.png`), auth.json variant names both paths (`T3B-empty-store-auth.png`), legacy-only state enables the login radio (`T3B-legacy-store.png`), explainer copy (`T3B-explainer.png`); sandbox restored; parent spot check re-ran `make check-cinnamon` + `node --check` OK.
- [x] **T4 — Verification** *(route: independent verifier + parent spot checks)*: DONE 2026-10-14. Fresh read-only verifier over `171159a..HEAD`: **PASS WITH FINDINGS** (all gates re-run green; core probes with temp HOMEs; live `:19` pass incl. legacy-only binding, poll detection both ways, unresolved-binary no-terminal path; sandbox restored). Findings: **F1 MINOR** — the README login note described the (now unreachable) terminal symptom instead of the in-applet status → fixed in the docs commit; **F2 NIT** — the fromDb backstop message can say "No OpenCode login found" in an unreachable forced state → accepted (wording-only, no user impact); **F3 NIT** — the generated script exits 1 at stdin EOF (no window exists there) and blocks under a real pty → accepted (cosmetic). Verdict saved to Engram (`verification/login-reliability`).
- [x] **T6 — Keyring-less API-key storage (report 4b)** *(route: delegated writer; live check with a fake ocgo)*: DONE 2026-10-14, commit `839a1fa` (+60/−6, `cinnamon/applet.js` only). Marker constant + stderr-first match; offer path keeps the key, relabels the confirm button `Store in a local file`, explains in plain language, no auto-close; retry sends `--store file` with identical args and the same key; radio switch resets the offer; other failures untouched. Live proof (fake ocgo, argv log): `auto` → offer → `--store file` → success → close; non-marker failure unchanged; sandbox restored.
- [x] **T7 — Independent verification of the T6 diff** *(route: fresh read-only verifier)*: DONE 2026-10-14. Verdict **PASS WITH FINDINGS** over `d17a920..HEAD` — scope clean (applet.js only; core/gnome untouched), CLI contract unchanged, offer/retry/reset paths live-proven, all gates green. Findings: **F1 MINOR** — a type switch cleared the flag and label but left the offer explanation on screen pointing at a hidden key field → fixed in `e3c48b1` (status cleared on the reset; re-checked live: status `''` + label `Add account` after the switch, and a fresh offer→retry round still ends in `--store file` + success + close); **F2 NIT** — Refresh replaces the offer explanation while the offer stays pending → accepted (button label carries the action); **F3 NIT** — programmatic double-click can double-submit → accepted (real input blocked by `reactive=false` + DialogLayout gating; pre-existing pattern). Disclosed by the verifier: one sandbox submit reached the real `ocgo` with a bogus key mid-restore; validation failed before any storage write (registry mtime and real `~/.config/ocgo` unchanged).
- [x] **T5 — Delivery** *(route: parent + user)*: pushed 2026-10-15; **PR #8** open against `main` (CI green); the stacked slice is **PR #9** (`feat/hide-plumbing`, base retargets to `main` after this merge). Merge remains the user's; the field retest then runs on Mint — the dialog names the store paths, so a remaining mismatch is diagnosable.

## Acceptance criteria

- Pressing "Log in with OpenCode…" on a machine where opencode exists only in the user's shell PATH opens a terminal that can run the login (no `opencode: not found`).
- The terminal never claims success on a failed login; exit 127 and other failures print distinct, actionable lines; the window stays open.
- On a machine with only a legacy `auth.json` login, the applet offers the OpenCode login binding and `ocgo` resolves the token; the dialog names the stores it checked.
- With no login at all, the dialog message names the checked store path(s) — `~/.local/share/opencode/opencode.db`, plus `auth.json` when the legacy file exists — so the state is self-diagnosable.
- "Use in OpenCode…" with nothing selected explains purpose + next step in two short sentences.
- On a machine without `libsecret-tools`, adding an API key from the dialog completes through the explicit "Store in a local file" fallback (no retyping of the key, no raw CLI instruction).
- Gates green: `make test`, `make check-cinnamon`, `make check-gnome`, `node --check`.

## Forecast

≈ 450–700 authored lines (core+tests ~200–300, applet ~180–300, README ~15; report 4b adds ~60–100). Single PR (repo precedent; size exception if needed).

## Progress log

- 2026-10-14 — Field report 4 triaged; recon complete (code + local desktop-session evidence + opencode storage semantics via the shipped v2 migration); contracts frozen; doc seeded.
- 2026-10-14 — T2 closed (core, `2e7571b`): legacy `auth.json` resolution with expiry gate, `store` block in `account discover --json`, missing database is a state; 459 tests OK; `review assess` over the committed range: high/unassessable (RDD off) → independent verifier required.
- 2026-10-14 — T3 closed (`02303bb`, `95ad0f1`): login script resolves opencode through a candidate list and reports every outcome honestly; store-aware guided state and copy; live `:19` pass with screenshots; sandbox restored. Harness note: reload after edits = `pkill -f 'cinnamo[n] --x11'` + `setsid python3 /tmp/opencode/cinnamon-test/launch.py` (see `launch.py`).
- 2026-10-14 — T4 closed: independent read-only verification over `171159a..HEAD` → PASS WITH FINDINGS. F1 (MINOR, README note keyed off the old terminal symptom) fixed in the docs commit; F2/F3 (NITs: unreachable forced-state wording; script EOF exit status) accepted with the verifier's rationale. Sandbox and real store untouched (inode check); all gates green.
- 2026-10-14 — Field report 4b folded (same user, API-key path): `--store auto` dead-ends without `libsecret-tools`; T6 (two-step file-store offer) + T7 (verification) added; CLI contract deliberately unchanged.
- 2026-10-14 — T6 closed (`839a1fa`): two-step `Store in a local file` offer in the add dialog; live fake-ocgo proof of both argv shapes; gates green. T7 closed: independent verification PASS WITH FINDINGS; F1 (stale offer status on type switch) fixed in `e3c48b1` and re-checked live; F2/F3 NITs accepted. Next: T5 delivery on the user's go-ahead.
- 2026-10-15 — Delivery opened: **PR #8** (`fix/login-reliability` → `main`) pushed with CI green; stacked **PR #9** (`feat/hide-plumbing`) follows. Merge pending the user; field retest on Mint after the merges.

---

Locator: odd/tasks/login-reliability.md (repo: opencode-go-meter)
