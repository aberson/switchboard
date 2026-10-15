# Switchboard Operator Surfaces

> **Toolkit program authority — 2026-09-24.** For units mapped from this document, the [toolkit program](../plan.md) owns selection, shared sequencing and current execution/status; the [source-unit ledger](../documentation/toolkit-program-units.md) identifies that mapped scope. Status and execution instructions retained below for transferred units are source history, not a second dispatch queue. Technical specifications, original IDs, acceptance criteria and evidence remain owned here. Update transferred-unit status in the program only; unmapped local work remains locally owned. Mapping does not complete, reopen or authorize a unit.

**Status:** APPROVED (2026-08-07)
**Concurrency:** `switchboard-endpoint-launcher` is an active worktree. Reconcile it before editing
scripts or switchboard documentation.

## 1. What This Feature Does

Provides an operator-readable routing/config/health report, promotes the deterministic bakeoff,
and resolves stale or one-time launcher buttons without changing fail-open routing semantics.

Proposal: [Utility Projects UAT proposal](utility-project-surfaces-proposal.html)

## 2. Existing Context

`switchboard/config.py` owns validated config and per-site model pins; `health.py` owns endpoint
reachability; `cli.py` exposes judge/config/bakeoff. dev-observatory already reads routing state.
Current CLAUDE.md names two scripts absent from this checkout; doctor reports both BROKEN. A separate
worktree may be implementing them, so deletion before reconciliation would be unsafe.

## 3. Scope

**In:** `inspect --json`, config + health + per-site effective model, stable bakeoff artifacts,
endpoint-launcher reconciliation, and observatory proof handoff. **Out:** making
local verdicts gates, auto-enabling sites, auto-starting WSL from a read-only view, or inventing
call-site evidence inside switchboard.

## 4. Impact Analysis

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `switchboard/cli.py` | extend | inspect command | judge/config/bakeoff dispatcher read directly |
| `switchboard/config.py` | reuse | effective model/site state | schema and lookup owner read directly |
| `switchboard/health.py` | reuse | endpoint/model availability | probe owner read directly |
| `switchboard/monitor.py`, `metrics.py` | inspect/reuse | recent in-process evidence if meaningful | modules exist |
| `switchboard/CLAUDE.md`, `README.md` | modify | remove stale setup claims or document shipped launcher | current stale commands inspected |
| `switchboard/scripts/` | reconcile | active worktree may add launcher scripts | current checkout contains only config JSON |
| `dev-observatory/switchboard_panel.py` | external consumer | caller/pin proof renderer | modified only by the dev-observatory plan |

## 5. New Components

- `python -m switchboard inspect --json`: config source, active state, endpoint reachability,
  configured/default/effective model per site, effort hints, and explicit limitations.
- `switchboard/observatory-contract.json`: versioned fixture carrying config fields/defaults and
  inspect output. dev-observatory joins it with mechanically found skill call sites and current
  source locators. Switchboard owns config truth; observatory owns workspace wiring proof.

## 6. Design Decisions

`run-bakeoff` is a main function because it demonstrates the safety threshold deterministically.
`config` remains useful but moves to all verbs; `inspect` is the readable main surface. `start` is
hidden if it is only a classifier artifact. The desktop-icon installer is one-time setup and is
never a dashboard button. `start-offload` survives only if the active launcher worktree lands and
doctor plus a real endpoint smoke prove it.

## 7. Build Steps

### Step 70: Reconcile the endpoint-launcher worktree
- **Status:** DONE (2026-08-09; retained launcher and installer prerequisite
  smokes pass without touching the service, endpoint, config, or Desktop)
- **Problem:** Inspect and merge/close the active `switchboard-endpoint-launcher` work before
  deciding whether `start-offload` exists; remove stale switchboard docs/scripts only if that work
  is abandoned. Registry changes remain owned by the dev-observatory plan.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code
- **Files:** `switchboard/CLAUDE.md`, `switchboard/README.md`, `switchboard/scripts/`
- **Produces:** one authoritative launcher disposition
- **Done when:** CLAUDE/README/scripts agree and the retained launcher script passes its own smoke
- **Depends on:** none

### Step 71: Add inspect JSON
- **Status:** DONE (2026-08-09; fixture coverage distinguishes absent, invalid,
  inactive, active-offline, and active-online states)
- **Problem:** Combine validated config and bounded health into a stable report with effective model
  per site, source, enabled/disabled state, effort hint, endpoint status, and limitations.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Files:** `switchboard/switchboard/cli.py`, `switchboard/switchboard/config.py`,
  `switchboard/switchboard/health.py`, `switchboard/tests/test_cli.py`,
  `switchboard/tests/test_health.py`
- **Produces:** inspect CLI, typed report, tests
- **Done when:** absent, invalid, inactive, active-offline, and active-online configs are distinct
- **Depends on:** 70

### Step 72: Publish the complete observatory contract
- **Status:** DONE (2026-08-09; versioned contract/schema and drift tests are
  covered by the full Switchboard suite)
- **Problem:** Export a versioned fixture/schema covering every config field (including `effort`),
  config filename/precedence, defaults (`coder-30b`), validation, and inspect states. This closes the
  current drift where dev-observatory reads a different filename/default and omits `effort`.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Files:** `switchboard/switchboard/config.py`, `switchboard/switchboard/cli.py`,
  `switchboard/tests/test_config.py`, `switchboard/tests/test_cli.py`,
  `switchboard/docs/observatory-contract.json`, `switchboard/docs/observatory-contract.md`
- **Produces:** cross-package contract fixture and schema
- **Done when:** changing any field/default/path without updating the fixture fails switchboard tests
- **Depends on:** 71

### Step 73: Curate operator documentation and bakeoff output
- **Status:** DONE (2026-08-09; documented roles and stable bakeoff output
  verified by focused and full tests)
- **Problem:** Explain inspect versus config versus bakeoff, ensure bakeoff output is a stable
  artifact consumable by observatory, and document the Step-70 launcher disposition. Registry and
  main/all-verbs curation remain owned by the dev-observatory plan.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code
- **Files:** `switchboard/switchboard/bakeoff.py`, `switchboard/switchboard/cli.py`,
  `switchboard/tests/test_bakeoff.py`, `switchboard/README.md`, `switchboard/CLAUDE.md`
- **Produces:** stable report artifact and docs
- **Done when:** inspect/config/bakeoff roles and launcher disposition are unambiguous
- **Depends on:** 70, 72

### Step 74: Real routing UAT
- **Problem:** Inspect inert and enabled configs, check endpoint-down/up states, run the frozen
  bakeoff, and if retained, start/stop offload through the launcher.
- **Type:** operator
- **Issue:** #
- **Produces:** operator evidence only
- **Done when:** inspect distinguishes config, endpoint, and certification state; bakeoff runs; any
  retained launcher starts and tears down cleanly without claiming the local model owns a gate
- **Depends on:** 73

## 8. Risks and Open Questions

| Item | Risk | Mitigation |
|---|---|---|
| Active worktree collision | delete work that is about to land | Step 70 hard reconciliation |
| Health appears equivalent to correctness | reachable model is uncertified | separate endpoint, bakeoff, and live-cert states |
| Wiring scan drifts | false proof | resolve current locators and show missing explicitly |

## 9. Testing Strategy

Unit-test inspect state combinations, effective model resolution, and the exported cross-package
fixture; the dev-observatory plan owns consumer integration tests and doctor. Then perform
endpoint-down/up UAT without changing the fail-open default.

## Appendix: Decision Inventory

| ID | P/D | Choice | Status |
|---|---|---|---|
| P2 | P | Add show-switchboard and evaluate bakeoff as a main action | accepted |
| D3 | D | Switchboard owns config/health artifacts; dev-observatory owns caller/pin HTML | accepted |
| D7 | D | Reconcile the active endpoint-launcher worktree before keeping/removing start buttons | accepted |
