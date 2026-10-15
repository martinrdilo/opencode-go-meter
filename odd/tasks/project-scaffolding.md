# Feature: project-scaffolding — Round 1: architecture, conventions, and README

**Status**: Delivered for review — PR #6 (slice 1 → `main`) and PR #7 (slice 2, stacked on `docs/project-scaffolding`) are open; merge is the user's call.
**Repo**: `opencode-go-meter`
**Branch**: `docs/project-scaffolding` (from `main` @ `171159a`)
**Worktree**: `../opencode-go-meter-worktrees/project-scaffolding` (the main checkout is busy with `fix/login-reliability` work in progress)
**Created**: 2026-10-14

## Objective

Give the repository a written, enforced foundation before it grows further:

- **S1 — architecture and decisions**: `docs/01-architecture.md` (the pieces, hard invariants, folder rules, where new things go) and `docs/05-technical-decisions.md` (registry of decisions already taken + a lightweight ADR template).
- **S2 — agent/contributor surfaces and README**: `AGENTS.md` (always-loaded map, commands, non-negotiables, index), `skills/project-conventions/SKILL.md` (on-demand operational rules), and a full README rewrite (outcome-first, progressive disclosure).

## Why

User request (2026-10-14): lock a firm structure now so growth does not become disorder; rewrite the README (dense, unclear). Reference scaffolding: `github.com/martinrdilo/notification-management-system` — adopt the AGENTS.md + skills conventions pattern and numbered docs with technical decisions; skip what does not apply (Docker, Testcontainers, CircleCI, `.env`).

## Audit findings (2026-10-14, verified)

- Architecture decisions exist but are scattered across `odd/tasks/*.md` and session memory; no architecture doc in the repo (`docs/` holds only screenshots).
- Current layout (`core/`, `gnome/`, `cinnamon/`, `docs/`, `odd/`) is sound — formalize it, do not reorganize (moves would break Makefile/dconf symlinks for no gain).
- The README's old file-structure listing was already removed in `b25f578` (2026-10-10); the remaining problems are the wall-of-text Accounts section and a dense intro.
- Surfaces split (user-approved, 2026-10-14): `AGENTS.md` = discovery (always loaded); `skills/` = on-demand rules; `docs/` = humans; `odd/tasks/` = tracking. Anti-duplication rule: one source of truth per rule; AGENTS.md carries headlines and pointers only.
- Versions today: `core/ocgo/__init__.py` `__version__` 0.1.0; `gnome/metadata.json` version 13; `cinnamon/metadata.json` has no version field; no git tags/releases. (Out of scope for Round 1 — proposed for Round 3.)

## Tasks

- [x] **T1 — `docs/01-architecture.md`**: the four pieces (core CLI, GNOME, Cinnamon, contracts), mermaid diagram of data flow, hard invariants, folder map, "where new things go" decision table. Commit: `docs: add the architecture overview` — `3d2c4bf` (91 lines).
- [x] **T2 — `docs/05-technical-decisions.md`**: decision registry (stdlib-only core; read-only credentials, no OAuth implementation; keyring with 0600 fallback; cache JSON as versioned contract; CLI-as-port / thin frontends; percent calibration and color thresholds; account model auto/pinned + registry versioning; symlink-only installs; unittest + stdlib checkers; agent surfaces) + ADR-lite template. Commit: `docs: add the technical decision registry` — `7818778` (160 lines).
- [x] **T3 — `AGENTS.md` + `skills/project-conventions/SKILL.md`**: map + commands + non-negotiables + docs/skills index; skill in skill-creator format (Activation Contract / Hard Rules / Decision Gates / Execution Steps / Output Contract / References). Commit: `docs: add AGENTS.md and the project-conventions skill` — `5afe95b` (AGENTS.md 47 lines; skill 63 lines).
- [x] **T4 — README rewrite**: progressive disclosure; keep exact install commands and screenshots; no file-structure listing. Commit: `docs: rewrite the README with progressive disclosure` — `470579d` (111 lines).

## Delivery strategy

- Forecast: S1 ≈ 260 authored lines (T1+T2); S2 ≈ 300 (T3+T4); total ≈ 560 > 400 → chain strategy required; **user chose `stacked-to-main` (2026-10-14)**.
- Slices: **S1** = seed + T1 + T2 (PR 1); **S2** = T3 + T4 stacked on S1 (PR 2, retarget to `main` after PR 1 merges).
- Push/PR/merge remain user decisions.

## Constraints

- English artifacts; Conventional Commits; no AI attribution.
- Writer's allowed edit surfaces: `README.md`, `AGENTS.md`, `docs/01-architecture.md`, `docs/05-technical-decisions.md`, `skills/project-conventions/SKILL.md` (+ new `skills/project-conventions/` directory). Nothing else.
- Doc claims must be verified against the code; if the code contradicts the brief, the code wins and the discrepancy is reported.

## Acceptance criteria

- Three surfaces exist and are mutually consistent; no rule duplicated across them.
- `AGENTS.md` ≈ ≤60 lines; skill body 180–450 tokens (max 700); README leads with what/for-whom.
- Every relative link in the touched files resolves; `make test` stays green.
- All commits are work-unit commits on `docs/project-scaffolding`.

## Checks

- `make test` (expect the unchanged green suite).
- Link-integrity check over the five files.
- Parent structural readback + `gentle-ai review assess` tier check (RDD off).

## Progress log

- 2026-10-14 — Feature doc seeded. Audit closed; AGENTS-vs-skills split approved; delivery strategy cached (stacked-to-main); worktree isolation set up because the main checkout carries `fix/login-reliability` work in progress.
- 2026-10-14 — T1–T4 executed by the delegated writer: commits `3d2c4bf`, `7818778`, `5afe95b`, `470579d` (plus seed `bd9cea3`). Checks: `make test` 422 OK; file-relative link integrity `missing: []`; `gentle-ai review assess` over `171159a..HEAD` (committed-only): tier medium (`executable_change` — AGENTS.md loads as agent instructions), `review_due: slice_budget_reached`; RDD is off (global) → no native review started, ordinary policy applies.
- 2026-10-14 — Independent read-only verifier: PASS WITH FINDINGS. All factual claims match the code (commands, flags, paths, versions, thresholds, schemas, installs, CI). Three wording imprecisions found by the independent verifier are fixed in the delivered docs (folded into the commits; no separate correction commit); the headline-vs-skill duplication note is accepted as by-design layering.
- 2026-10-14 — Branch restructured for stacked delivery: `docs/project-scaffolding` = S1 (from `main`: seed + architecture + decisions); `docs/project-scaffolding-2` = S2 stacked on S1 (AGENTS + skill + README). The pre-restructure branch is kept locally as `docs/project-scaffolding-old`.
- 2026-10-14 — Delivered: both branches pushed; PR #6 (S1 → `main`) and PR #7 (S2 → `docs/project-scaffolding`) opened on GitHub with the `documentation` label; the `tests` workflow runs per push.
- Next step: user review + merge of PR #6; then PR #7 retargets to `main` (retarget manually, or let GitHub do it when the base branch is deleted). Main checkout remains untouched (`fix/login-reliability` session active).
