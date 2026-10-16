# Feature: project-scaffolding — rounds 1–3

**Status**: Round 1 complete (PRs #6/#7 merged to `main`, `72e30c8`/`e9b5485`). Rounds 2–3: S3 complete (`docs/reference-docs`), S4 complete (`chore/versioning-pack`), S5 complete (`chore/community-files`); independent verification + delivery pending.
**Repo**: `opencode-go-meter`
**Branches**: Round 1: `docs/project-scaffolding`, `docs/project-scaffolding-2` (merged). Rounds 2–3: `docs/reference-docs` (S3) → `chore/versioning-pack` (S4, stacked) → `chore/community-files` (S5, stacked).
**Worktree**: rounds 2–3 run in `../opencode-go-meter-worktrees/project-scaffolding-r2r3` (isolated on 2026-10-15 after a parallel `feat/accounts-window` session went live in the main checkout mid-S4).
**Created**: 2026-10-14

## Objective

Give the repository a written, enforced foundation before it grows further:

- **R1 — architecture, conventions, README** (done): `docs/01-architecture.md`, `docs/05-technical-decisions.md` (D1–D10 + template), `AGENTS.md`, `skills/project-conventions/SKILL.md`, README rewrite.
- **R2 — reference docs**: `docs/02-cli-reference.md`, `docs/03-frontends.md` (compat matrix), `docs/04-testing.md`, wired into the doc surfaces.
- **R3 — release and community hygiene**: CHANGELOG.md + SemVer policy/tags + `make pack`; issue/PR templates; `CONTRIBUTING.md` and `SECURITY.md`.

## Why

User request (2026-10-14): lock a firm structure now so growth does not become disorder; rewrite the README (dense, unclear). Reference scaffolding: `github.com/martinrdilo/notification-management-system`.
User request (2026-10-15): continue with Rounds 2 and 3 — the remaining reference docs plus release hygiene so the repo is distributable and self-explanatory for contributors.

## Audit findings — Round 1 (2026-10-14, verified)

- Architecture decisions exist but are scattered across `odd/tasks/*.md` and session memory; no architecture doc in the repo (`docs/` held only screenshots).
- Current layout (`core/`, `gnome/`, `cinnamon/`, `docs/`, `odd/`) is sound — formalize it, do not reorganize (moves would break Makefile/dconf symlinks for no gain).
- The README's old file-structure listing was already removed in `b25f578` (2026-10-10); the remaining problems were the wall-of-text Accounts section and a dense intro.
- Surfaces split (user-approved, 2026-10-14): `AGENTS.md` = discovery (always loaded); `skills/` = on-demand rules; `docs/` = humans; `odd/tasks/` = tracking. Anti-duplication rule: one source of truth per rule; AGENTS.md carries headlines and pointers only.
- Versions today: `core/ocgo/__init__.py` `__version__` 0.1.0; `gnome/metadata.json` version 13; `cinnamon/metadata.json` has no version field; no git tags/releases.

## Audit findings — Rounds 2–3 (2026-10-15, verified)

- `docs/02`–`docs/04` are free, unclaimed numbers: no references anywhere; numbering rule is "next free number" (`docs/01:82`).
- CLI surface (verified in `core/ocgo/cli.py`): `refresh` (`--account`/`--all`), `status` (`--json`, `--no-color`, `--account`), `auth show` (`--account`), `account {add,set-key,list,discover,activate-in-opencode,use,remove}`; global `--version` prints `ocgo 0.1.0`; exit codes 0 ok / 1 handled failure / 2 argparse usage.
- Env: `OCGO_TOKEN`, `OCGO_DB`, `OCGO_TOKEN_<ID>`, `NO_COLOR`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`. Paths: cache `$XDG_CACHE_HOME/ocgo/status.json` (+ per-account), registry `$XDG_CONFIG_HOME/ocgo/accounts.json`, 0600 file secrets, keyring, OpenCode DB + legacy `auth.json`.
- Frontends: GNOME `shell-version: ["50"]` (ESM `resource:///`), version 13; Cinnamon `cinnamon-version: ["5.4"]`, no version field, 5.4-vs-6.4 compat shims commented in `applet.js`. Settings: GNOME `refresh-interval`/`panel-box`/`panel-position`/`show-credits`; Cinnamon `refresh-interval`/`show-credits`/`active-account`.
- Tests: 6 files under `core/tests/` (459 static `def test_`), env-isolated, never network; static checkers `gnome/scripts/check_collisions.py`, `cinnamon/scripts/check_applet.py`; CI `.github/workflows/test.yml` (name `tests`, push + PR, `make test` + both checkers).
- Packaging: `.gitignore` already ignores `dist/` and `*.shell-extension.zip` (added in the initial scaffold `2a543ac`); no pack/release scripts exist. Distribution layouts (verified against primary sources): GNOME extension zip is flat (files at archive root); Cinnamon spice zip nests a `UUID/` folder.
- Community: no CHANGELOG/CONTRIBUTING/SECURITY; `.github/` holds only `workflows/test.yml`. Repo keeps branches after merge (precedent); PRs use the `documentation` label and PR #5 structure + Chain Context.

## Tasks — Round 1 (complete)

- [x] **T1 — `docs/01-architecture.md`**: the four pieces (core CLI, GNOME, Cinnamon, contracts), mermaid diagram of data flow, hard invariants, folder map, "where new things go" decision table. Commit: `docs: add the architecture overview` — `2f179f5` (91 lines).
- [x] **T2 — `docs/05-technical-decisions.md`**: decision registry (D1–D10) + ADR-lite template. Commit: `docs: add the technical decision registry` — `42015f1` (160 lines).
- [x] **T3 — `AGENTS.md` + `skills/project-conventions/SKILL.md`**: map + commands + non-negotiables + docs/skills index; skill in skill-creator format. Commit: `docs: add AGENTS.md and the project-conventions skill` — `19e4238` (AGENTS.md 47 lines; skill 63 lines).
- [x] **T4 — README rewrite**: progressive disclosure; keep exact install commands and screenshots; no file-structure listing. Commit: `docs: rewrite the README with progressive disclosure` — `7a94471` (111 lines).

## Tasks — Round 2: reference docs (S3, branch `docs/reference-docs`)

- [x] **T5 — `docs/02-cli-reference.md`**: full `ocgo` reference verified against source — synopsis, global behavior (`--version`, `-h`, exit codes 0/1/2, colors + `NO_COLOR`), every command and flag (see audit findings), what default vs `--json` output shows, environment variables, file locations (cache, registry, key files, keyring, OpenCode DB + legacy `auth.json`), worked copy-paste examples. Must not duplicate README quick start or AGENTS headlines — link them. Link rules: file-relative, from `docs/`. Commit: `docs: add the CLI reference` — `c5aab8d` (207 lines).
- [x] **T6 — `docs/03-frontends.md`**: GNOME vs Cinnamon reference with a compat matrix (GNOME Shell 50 / ESM; Cinnamon 5.4+ and the 5.4-vs-6.4 shims), what you see (panel format `5h X% · 7d Y% · 30d Z%`, color thresholds 50/85 mirrored constants, empty states, popup rows, Cinnamon tooltip vs GNOME none), settings tables per frontend (exact keys/ranges/defaults from schema and settings-schema), install/uninstall points to README (no duplication), troubleshooting (enable/disable, prefs, `make deps`; external commands must be verified or omitted). Commit: `docs: add the frontends reference` — `058a54d` (123 lines).
- [x] **T7 — `docs/04-testing.md`**: how to run (`make test`, `make check-gnome`, `make check-cinnamon`, `make deps`), what each test file covers, test conventions (stdlib unittest, offline, env isolation, temp dirs, fake `secret-tool`), what the static checkers validate, CI workflow (triggers/steps), pre-PR checklist pointer. Commit: `docs: add the testing guide` — `e6cf855` (88 lines).
- [x] **T8 — doc-surface wiring**: `AGENTS.md` Docs section gains the three docs; `docs/01-architecture.md` Related section gains the three docs; `README.md` Development section gains one reference line (02/03/04). Commit: `docs: wire the new references into the doc surfaces` — `deba7de` (AGENTS.md +6, docs/01 +3, README +2).

Commits: `docs: add the CLI reference` (T5), `docs: add the frontends reference` (T6), `docs: add the testing guide` (T7), `docs: wire the new references into the doc surfaces` (T8).

## Tasks — Round 3a: versioning, changelog, pack (S4, branch `chore/versioning-pack`)

- [x] **T9 — versioning decision (D11) + tag**: append D11 to `docs/05-technical-decisions.md` (after D10, before `## Template`): project version is SemVer; `core/ocgo/__init__.py::__version__` is the single source of truth (surfaced by `ocgo --version`); annotated git tags `vX.Y.Z` on `main` mark released states; GNOME metadata `version` stays an independent packaging integer (extensions.gnome.org contract, bumped deliberately); Cinnamon metadata stays versionless; release artifacts build with `make pack` into gitignored `dist/`; `CHANGELOG.md` follows Keep a Changelog. Create annotated tag `v0.1.0` on `8f9fab5` (local only, no push). Commit: `docs: add the versioning decision` — `7f26df0`; annotated tag `v0.1.0` → `8f9fab5` (local, unpushed).
- [x] **T10 — `CHANGELOG.md`**: Keep a Changelog 1.1.0 format. `[Unreleased]` lists what Rounds 2–3 add up to this slice (docs 02–04, pack tooling, the versioning decision). `[0.1.0] - 2026-10-15` reconstructs the initial release honestly from `git log` + merged PRs #1–#9 + `odd/tasks/*.md` (meter, multi-account, OAuth login via OpenCode DB + legacy `auth.json`, API keys with keyring/0600 fallback, credits, dependency check, sanitized UI errors, docs). Link refs to the GitHub compare/tag URLs. Commit: `docs: add the changelog` — `2f51d49`.
- [x] **T11 — `make pack`**: new `scripts/pack.py` (stdlib `zipfile` only) + `pack` target in `Makefile` (+ `.PHONY`). Builds into `dist/`: `opencode-go-meter@martinrdilo.shell-extension.zip` — flat archive: `metadata.json`, `extension.js`, `prefs.js`, `stylesheet.css`, `schemas/*.gschema.xml` (exclude `scripts/`, compiled schemas); `opencode-go-meter@martinrdilo.zip` — nested `opencode-go-meter@martinrdilo/` folder: `metadata.json`, `applet.js`, `settings-schema.json`, `stylesheet.css`. Fail fast if a required file is missing; validate uuid from metadata; print artifact paths and sizes. Writer verifies with a zip listing. Commit: `build: add make pack for release artifacts` — `f9d31e4`.

## Tasks — Round 3b: community surfaces (S5, branch `chore/community-files`)

- [x] **T12 — `.github` templates**: `ISSUE_TEMPLATE/bug_report.yml` (frontend selector core/GNOME/Cinnamon, what happened, expected, steps, `ocgo --version` + desktop/OS versions, optional `ocgo status` output, optional logs, "never paste tokens" note), `ISSUE_TEMPLATE/feature_request.yml` (problem, proposal, scope, alternatives), `ISSUE_TEMPLATE/config.yml` (blank issues stay enabled), `pull_request_template.md` (summary, type, checklist: checks green / docs updated / English / Conventional Commits / no secrets; Chain Context section per the chained-PR convention). YAML must parse. Commit: `chore: add the issue and pull request templates` — `51a30a4` (4 files, +159).
- [x] **T13 — `CONTRIBUTING.md` + `SECURITY.md` + wiring**: CONTRIBUTING (setup, run checks, conventions — core stdlib-only, thin frontends, English artifacts, Conventional Commits, no AI attribution —, work-unit commits, PR flow with template + Chain Context for stacked PRs, release/versioning pointers). SECURITY (supported: latest `main`; private reporting via GitHub's Security tab; scope: credential handling/leaks, cache integrity; out of scope: the upstream OpenCode app/service). README: Security section links SECURITY.md, Development links CONTRIBUTING.md; append the S5 items to CHANGELOG `[Unreleased]`. Commit: `docs: add CONTRIBUTING and SECURITY` — `1324bba` (4 files, +123).

## Delivery strategy

- Round 1 (done): `stacked-to-main` (user chose 2026-10-14); S1 = PR #6, S2 = PR #7.
- Rounds 2–3: reuse the cached strategy **`stacked-to-main`**. Forecast: S3 ≈ 450, S4 ≈ 350, S5 ≈ 400 authored lines → three slices, one PR each. S3 ← `main`; S4 ← S3 branch; S5 ← S4 branch. Retarget to `main` as predecessors merge (repo keeps branches on merge, so retarget manually).
- Push, PR creation, tag push, and merge remain user decisions.

## Constraints

- English artifacts; Conventional Commits; no AI attribution.
- Writers only touch their slice's allowed edit surfaces (below); nothing else per slice.
- Doc claims must be verified against the code; if the code contradicts the brief, the code wins and the discrepancy is reported.
- No runtime code changes: `core/ocgo/*`, `gnome/extension.js`, `gnome/prefs.js`, `cinnamon/applet.js` stay untouched.

### Allowed edit surfaces

- **S3**: `docs/02-cli-reference.md`, `docs/03-frontends.md`, `docs/04-testing.md` (new); `AGENTS.md` (Docs section), `docs/01-architecture.md` (Related section), `README.md` (Development section).
- **S4**: `CHANGELOG.md`, `scripts/pack.py` (new); `Makefile` (pack target), `docs/05-technical-decisions.md` (D11), `README.md` (Development section link).
- **S5**: `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `.github/pull_request_template.md`, `CONTRIBUTING.md`, `SECURITY.md` (new); `README.md` (Security + Development sections), `CHANGELOG.md` (Unreleased entries).

## Acceptance criteria

Rounds 2–3:

- Every CLI, frontend, and testing claim in the new docs matches the source; link integrity holds across touched files (file-relative resolution).
- No rule duplicated across surfaces (README keeps install steps; docs reference them); AGENTS.md ≤ 60 lines.
- D11 present before the template; CHANGELOG follows Keep a Changelog 1.1.0 with working link refs; tag `v0.1.0` (annotated) points at `8f9fab5` locally.
- `make pack` builds both artifacts with the verified layouts; `dist/` stays gitignored; required-file assertions fail fast.
- Issue templates parse as YAML; CONTRIBUTING/SECURITY describe only repo-real process (no invented steps).
- `make test`, `make check-gnome`, `make check-cinnamon` stay green; all commits are work-unit commits on their slice branch.

## Checks

- `make test` (expect green suite), `make check-gnome`, `make check-cinnamon`.
- Link-integrity check over touched files (file-relative from each file's directory).
- S4: `make pack` + archive listing inspection (`unzip -l` or `python3 -m zipfile -l`).
- S5: YAML parse of issue templates if PyYAML is available; otherwise structural readback.
- Parent structural readback per slice + `gentle-ai review assess --cwd . --committed-only --json` (RDD off) for the record; independent read-only verifier pass over the three slices before delivery.

## Progress log

- 2026-10-14 — Feature doc seeded. Audit closed; AGENTS-vs-skills split approved; delivery strategy cached (stacked-to-main); worktree isolation set up because the main checkout carried `fix/login-reliability` work in progress.
- 2026-10-14 — T1–T4 executed by the delegated writer: commits `2f179f5`, `42015f1`, `19e4238`, `7a94471` (plus seed `22d52bc`). Checks: `make test` 422 OK; file-relative link integrity `missing: []`; `gentle-ai review assess` over `171159a..HEAD` (committed-only): tier medium (`executable_change` — AGENTS.md loads as agent instructions), `review_due: slice_budget_reached`; RDD is off (global) → no native review started, ordinary policy applies.
- 2026-10-14 — Independent read-only verifier: PASS WITH FINDINGS. All factual claims match the code (commands, flags, paths, versions, thresholds, schemas, installs, CI). Three wording imprecisions found by the independent verifier are fixed in the delivered docs (folded into the commits; no separate correction commit); the headline-vs-skill duplication note is accepted as by-design layering.
- 2026-10-14 — Branch restructured for stacked delivery: `docs/project-scaffolding` = S1 (from `main`: seed + architecture + decisions); `docs/project-scaffolding-2` = S2 stacked on S1 (AGENTS + skill + README). The pre-restructure branch is kept locally as `docs/project-scaffolding-old`.
- 2026-10-14 — Delivered: both branches pushed; PR #6 (S1 → `main`) and PR #7 (S2 → `docs/project-scaffolding`) opened on GitHub with the `documentation` label; the `tests` workflow runs per push.
- 2026-10-15 — Rebased onto `main` after PRs #8/#9 merged: README reconciled with the new Dependencies section and the *OpenCode was not found* login note; D2/D8 updated for the legacy credential store and the dependency check (`ac6c9a9`).
- 2026-10-15 — PR #6 and PR #7 merged to `main` (`72e30c8`, `e9b5485`); Round 1 complete.
- 2026-10-15 — Rounds 2–3 planned: recon verified the CLI surface, frontend metadata/settings, test inventory + CI, versioning state, and the distribution layouts (GNOME flat; Cinnamon `UUID/` folder). Delivery strategy reloaded (`stacked-to-main`), slices S3/S4/S5 defined, RDD off (global) re-confirmed.
- 2026-10-15 — S3 executed by the delegated writer: commits `c5aab8d` (CLI reference, 207 lines), `058a54d` (frontends, 123), `e6cf855` (testing, 88), `deba7de` (wiring). Checks: `make test` 459 OK; `make check-gnome`/`check-cinnamon` OK; link integrity `missing: []` (39 relative links). Parent spot check: diff limited to the allowed surfaces; `make test` re-run OK. `gentle-ai review assess` over `8f9fab5..HEAD` (committed-only): tier medium (`executable_change` — AGENTS.md), `review_due: slice_budget_reached`; RDD off (global) → recorded, no native review started.
- 2026-10-15 — S3 notes: file-secret root verified as `$XDG_CONFIG_HOME/ocgo/keys/<id>.key` (0600, dir 0700); `--store keyring` exists only in the accounts API docstring, not the parser (docs cover `auto|file`); docs/02 is 207 lines (soft cap ≈200; trimmed once, full coverage kept).
- 2026-10-15 — S4 executed by the delegated writer (in the main checkout, before isolation): `7f26df0` (D11 versioning decision), `2f51d49` (CHANGELOG + README link), `f9d31e4` (`make pack`: `scripts/pack.py` + Makefile target); annotated tag `v0.1.0` created locally at `8f9fab5`. Checks: `make test` 459 OK (twice, with the parallel session's edits present); both checkers OK; `make pack` → byte-identical archives across runs and CWDs (GNOME flat, 5 entries; Cinnamon nested `UUID/`, 4 entries); fail-fast paths demonstrated (missing file, bad uuid, no schemas); link check `missing: []`; `dist/` ignored. Notes: PR-only reconstruction would undercount 0.1.0 (core/applets also landed via direct commits), so the changelog uses `git log` + `odd/tasks/`; Keep a Changelog has no Documentation section, so docs sit under Added.
- 2026-10-15 — Checkout collision caught mid-S4: a parallel session created `feat/accounts-window` **from this feature's S3 tip** (21:57:59; its own doc claims "from main @ 907199c" — actually `docs/reference-docs` @ `3a9e15e`) and its writer switched the shared HEAD twice. Mitigation: the main checkout was returned to `feat/accounts-window` with the parallel session's uncommitted edits intact (`cinnamon/applet.js`, `cinnamon/scripts/check_applet.py`, `scripts/install-deps.sh`, untracked `odd/tasks/accounts-window.md` — never committed by this feature), and rounds 2–3 moved to the isolated worktree `../opencode-go-meter-worktrees/project-scaffolding-r2r3`. Flag for the user: `feat/accounts-window` carries this feature's S3 commits; it needs a rebase onto `main` before its PR.
- 2026-10-15 — S5 executed by the delegated writer in the isolated worktree: `51a30a4` (issue forms + PR template with Chain Context), `1324bba` (CONTRIBUTING, SECURITY, README links, CHANGELOG `[Unreleased]`). Checks: `make test` 459 OK; both checkers OK; all three issue forms parse with PyYAML (`/usr/bin/python3` 6.0.3 — PATH `python3` lacks it; nothing added); link check 17 links, `missing: []`. Parent spot check: diff limited to the 8 allowed files; `make test` and the YAML parse re-run OK. Notes: private vulnerability reporting is DISABLED on the repo (`gh api` → `enabled: false`) — SECURITY.md uses the generic Security-tab phrasing; enabling it is a one-click user action. Issue forms carry no auto-labels; `[Bug]:`/`[Feature]:` title prefixes are the GitHub convention.
- 2026-10-15 — Independent read-only verifier over `main..HEAD`: PASS WITH FINDINGS (no blockers). ≥20 CLI claims live-probed and matched; frontends/settings/tests/CI/changelog/D11/pack/templates/links all verified; surface check clean (17 files, no runtime code). Finding fixed: the "no third-party packages" note in `docs/04-testing.md` and `CONTRIBUTING.md` now names Node as required for `make check-cinnamon` (`docs: qualify the dependency note for the Cinnamon check`). Left as documented nits: `docs/03` "Cinnamon 5.4+ (Linux Mint 21+)" is evidence-backed but live-verified only on Cinnamon 6.4; SECURITY.md's primary channel (Security tab) requires enabling private vulnerability reporting (currently disabled on the repo).
- Next step: delivery — push `docs/reference-docs`, `chore/versioning-pack`, `chore/community-files` and open the three stacked PRs (plus push tag `v0.1.0`) — pending user decision.
