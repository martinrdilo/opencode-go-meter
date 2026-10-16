## Summary

<!-- What this PR changes and why, in a sentence or two. -->

## Type of change

- [ ] Core (`ocgo` CLI, `core/`)
- [ ] GNOME extension
- [ ] Cinnamon applet
- [ ] Docs
- [ ] Build and tooling (`Makefile`, `scripts/`)
- [ ] CI

## Checklist

- [ ] `make test` is green.
- [ ] `make check-gnome` and `make check-cinnamon` are green.
- [ ] Docs are updated when behavior changed (README or `docs/`).
- [ ] Artifacts are English; commits follow Conventional Commits, with no AI attribution.
- [ ] No secrets in the diff or logs.
- [ ] Tests were added or updated beside every behavior change.

## Chain Context

<!--
Fill this in for stacked or chained PRs. For a standalone PR, base it on `main`
and write "Not needed" / "None" where nothing applies.
-->

| Field | Value |
|-------|-------|
| Chain | <feature or stack name> |
| Tracker PR | <#NNN or "Not needed"> |
| Position | <N of total> |
| Base | `<target branch>` |
| Depends on | <PR / issue / link, or "None"> |
| Follow-up | <next PR, or "None"> |
| Review budget | <changed lines> / 400 |
| Starts at | <branch, PR, or state this builds on> |
| Ends with | <standalone result this PR delivers> |

### Chain Overview

```text
main
 └── #NNN Previous PR
      └── 📍 #NNN This PR
           └── #NNN Next PR
```

### Scope

- Includes: <the focused unit of this PR>
- Excludes: <work deferred to other PRs>

### Autonomy

- [ ] CI is expected to pass for this PR branch
- [ ] This PR has one deliverable scope
- [ ] This PR can be rolled back without unrelated changes
- [ ] Tests, docs, or manual verification cover this unit
