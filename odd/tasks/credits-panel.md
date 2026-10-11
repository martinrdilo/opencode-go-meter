# Feature: credits-panel — Credits balance, extra usage, and auto-recharge in the meter

**Status**: implementation complete + verified (2026-10-10); awaiting the user's relogin confirmation (GNOME code reload)
**Repo**: `opencode-go-meter`
**Branch**: `feat/credits-panel` (implementation)
**Created**: 2026-10-10

## Objective

Show the OpenCode Go console's credits block in the app: credit balance ("Running low" state), the extra-usage switch (use credits when a Go limit is reached), and the auto-recharge state. Read-only mirror of the console panel — no purchases, no toggles, no writes.

## Problem / Why

The user ran out of Go subscription limits and is now spending extra credits; the only place showing the balance is the console. The meter app should surface the same numbers next to the meters (user request, 2026-10-10, with a console screenshot: `$3.60` + "Running low" + Extra usage toggle + "Auto-recharge off").

## Data source (verified live, 2026-10-10 — user authorized the probe)

Console API (same origin/namespace as the existing endpoint):

- `GET https://opencode.ai/console/api/billing/status` — auth: same Bearer token as `go/status`.
- `GET https://opencode.ai/console/api/billing/auto-recharge` — same auth.
- `GET https://opencode.ai/console/api/go/status` — already used; now also read `useBalance` (extra-usage switch state).
- `GET https://opencode.ai/zen/go/v1/usage` (api-key accounts) — percent-only; **no credits data exists for API keys**.

Live probe results (real responses; ids redacted):

```json
// billing/status (OAuth login) — HTTP 200
{"billingMode":"prepaid","mode":"pay-as-you-go","balanceMicroCents":"312600514",
 "creditLimitMicroCents":null,"availableMicroCents":"312600514",
 "canPurchaseCredits":true,"canEnableAutoRecharge":true}

// billing/auto-recharge (OAuth login) — HTTP 200
{"enabled":false,"thresholdDollars":5,"rechargeAmountDollars":20,"pending":false,"failureReason":null}

// go/status (OAuth login) — HTTP 200, key fields only
{"product":"go","useBalance":true,"cancelAtPeriodEnd":false,"resumability":"renewing",
 "renewalPending":false,"access":{"endsAt":"2026-10-11T02:26:15.000Z","meters":{…}}}
```

**Account-kind matrix (probed):**

| Credential | billing/status | auto-recharge | go/status |
| --- | --- | --- | --- |
| API key (`oc_sk_…`, zen) | **403 Forbidden** | 403 | 403 |
| OAuth login (local DB) | 200 | 200 | 200 |

=> Credits are only available for OAuth/login accounts (`KIND_OPENCODE_DB`). API-key accounts keep the meters only. The console API rejects API keys with `{"_tag":"Forbidden"}`.

**Units**: microcents, 1e-8 USD (same as meters). Values arrive as JSON strings.

**Console semantics (from the public console bundle, cross-checked with the user's screenshot):**

- Displayed amount: `availableMicroCents` (not `balanceMicroCents`).
- State (prepaid only): `available <= 0` → "No credits left"; `available < $5.00` and auto-recharge not healthy → "Running low"; else no suffix.
- Auto-recharge healthy = `enabled && failureReason == null`. The $5 threshold is a console constant (verified in the bundle: `5` dollars).
- Title is "Credits" when `billingMode == "prepaid"`.
- Amount format: USD, 2 decimals (`$3.13`); `0 < |amount| < $0.01` → `<$0.01`.
- Auto-recharge strings: "Off" / "Auto-recharge adds $X below $Y" / "Auto-recharging…" / "Auto-recharge failed".

## Scope

In scope:

- Core: fetch billing status + auto-recharge (OAuth accounts only, best-effort), map into the cache, show a credits line in `ocgo status`, extend the refresh summary.
- GNOME popup: Credits / Extra usage / Auto-recharge rows (hidden for API-key accounts).
- Cinnamon popup: same rows (parity).
- README + this doc.

Out of scope (explicit):

- Purchases ("Add credits"), toggling extra usage, changing auto-recharge (console-only; write endpoints exist but the app stays read-only).
- Panel-label changes (popup only for now).
- Credits for API-key accounts (impossible: console API returns 403; zen has no credits).
- Credit mode (`billingMode != "prepaid"`) rendering beyond the state rule above.

## Cache schema (additive to v1)

New optional keys; old frontends ignore them, new frontends tolerate their absence:

```json
{
  "schema": 1,
  "extra_usage": true,          // bool | null — go/status useBalance; null when unknown (zen)
  "credits": {                  // object | null — null = unavailable for this account kind
    "available_usd": 3.126,     // availableMicroCents as USD (round 4)
    "state": "low",             // "ok" | "low" | "empty" (console rule above)
    "billing_mode": "prepaid",
    "auto_recharge": {          // object | null — null = not fetched/available
      "enabled": false,
      "threshold_usd": 5.0,
      "amount_usd": 20.0,
      "pending": false,
      "failed": false
    }
  }
}
```

- OAuth account + billing fetch failure: `"credits": {"error": "<short message>"}` (usage refresh still succeeds).
- Zen accounts: `"credits": null, "extra_usage": null`.
- Billing/auto-recharge failures must never fail the usage refresh.

## Tasks

- [x] **T1 — Spike** *(route: parent, inline — credential-sensitive)*: bundle recon + live probe with the user's explicit authorization. Evidence: Data source above. Commits: none (docs only).
- [x] **T2 — Core: credits fetch, cache, CLI** *(route: delegated writer — 3 source + 3 test files)*: `fetch_billing_status` / `fetch_auto_recharge` (shared console-JSON helper), `credits_from_billing` mapping, `credits_state()` in `format.py`, `useBalance` → `extra_usage`, CLI refresh wiring (best-effort billing; failures → `credits: {"error": …}`, never fail the refresh), `ocgo status` credits row, refresh summary extension, tests. Evidence: commit `47baf9a`; `make test` 253 → 309 green; `check-gnome`/`check-cinnamon` green; live smoke (OAuth, 2026-10-10): `extra_usage: true`, credits `$2.96` `low`, auto-recharge off, summary `… · $2.96`; assess tier medium (`executable_change`).
- [x] **T3 — Frontends: credits section** *(route: delegated writer — 4 files; one writer for GNOME+Cinnamon parity)*: popup rows (Credits amount+state colored, Extra usage On/Off, Auto-recharge state), hidden rules, GNOME stylesheet + metadata bump (7 → 8). Evidence: commit `0f95de6`; `node --check` ×2 + `check-gnome`/`check-cinnamon` green (parent re-ran); assess medium (254 lines, under budget); writer render-harness 25 formatter + 19 cache shapes × 2 frontends.
- [~] **T4 — Verification** *(route: parent + per-action)*: `make test` 309 green (parent re-ran); `check-gnome`/`check-cinnamon` + `node --check` green (parent re-ran); live `ocgo refresh` smoke on both account kinds (`$2.68` on the OAuth account, `credits: null` on the API key, no regression); devkit shell: extension `state: ACTIVE`, `version: 8`, `error: ''`; render harness 44/44. **Pending: the user's visual confirmation after relogin** (GNOME module reload needs logout/login).
- [x] **T5 — Docs** *(route: parent)*: README "Credits" section (incl. the API-key limitation), Security line updated, this doc closed. Evidence: this docs commit.

## Acceptance criteria

- `ocgo refresh` on an OAuth account caches credits; on an API-key account it succeeds unchanged with `credits: null` (no new errors).
- Popup shows the credits block matching the console (amount, "Running low" state, extra usage, auto-recharge) and hides it entirely for API-key accounts.
- `make test` green; both static checks green.
- Live smoke: refreshed balance matches the console.

## Constraints / Decisions

- Core: Python 3 stdlib only; tests `unittest` via `make test`. TDD mode: OFF (no project/session config) — unit tests are ordinary verification.
- RDD (gentle-ai review): off (global) — ordinary repository policy.
- Artifacts in English. Frontends never touch credentials (unchanged).
- GNOME dev reload rule: bump `metadata.json` version on code changes; settings apply live.
- Delivery: `single-pr` — the feature ships as one PR; the maintainer accepted `size:exception` (2026-10-10; the core slice alone is ~970 authored lines and has no cohesive sub-400 split). Work-unit commits on `feat/credits-panel`; push/PR is the user's call.
- Writer routes: T2 delegated (multi-file core+tests), T3 delegated (multi-file frontends).

## Progress log

- 2026-10-10 — T1 done: console bundle recon (endpoints/types/strings) + live probe with user authorization; account-kind matrix established (API keys cannot read credits); branch `feat/credits-panel` created.
- 2026-10-10 — T2 done (delegated writer): core credits support shipped; suite 253 → 309 green; static checks green; live smoke OK (`$2.96`, Running low, extra usage on, auto-recharge off). Delivery strategy recorded: `single-pr` + `size:exception` accepted.
- 2026-10-10 — T3 done (delegated writer): credits section in both popups; syntax + static checks green; assess medium, under budget.
- 2026-10-10 — T4 (automated) + T5 done: full verification pass; OAuth account `default` re-added to the registry and activated (user-approved; registry backup kept); live refresh `$2.68` with the credits row; README + close-out. User relogin confirmation pending.
