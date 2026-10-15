# Plan — Switchboard offload (optional): config-loader + live offload

## 1. What this is, and the honest framing

Switchboard Phase 1 shipped a built, tested local-offload core (`switchboard/` + `/offload-scan`) with six skills carrying INERT offload branches — but **there is no way to actually turn offload on**, and even if there were, no slice has been certified safe to run on a cheaper model in production. This plan covers both halves, deliberately framed as **optional and gated** rather than a default-on cost program:

- **Phase A — config-loader** (the on-switch + transparency). *Already planned and issue-minted* as Switchboard Phase 1.5: [`docs/switchboard-config-loader-plan.md`](archived-plans/switchboard-config-loader-plan.md) (branch `switchboard-config-loader`, issues **#216–221**). Build-ready.
- **Phase B — live offload enablement** (actually moving the first slice to a local/cheaper model, certified by a bake-off). New; deferred behind the gates in §2.

**Why optional, not a priority.** Per [`docs/investigations/token-usage-levers-consolidated-2026-06-22.md`](investigations/token-usage-levers-consolidated-2026-06-22.md), switchboard offload is **Lever 4 item 5** — the workspace's *smallest* token lever (subagents are 23% of usage; the offload slice within that is explicitly tagged *"strategic value > token value"*). The big, low-risk token wins (Lever 2 resident-content slimming, Lever 3 the 1M multiplier) live elsewhere and do **not** need this plan. So this is worth building for a **capability** reason, not a cost reason:

> Do this if — after the Lever-2/3 re-measurement — you still want more reduction **and** you want local-model offload as a capability: **privacy** (judge/grade prompts never leave the machine) or being **genuinely quota-constrained** on a paid local box. Otherwise it can sit, finished-but-off.

**Transparency is the part that's worth having even when offload stays OFF.** Phase A's `python -m switchboard config` pre-flight + the inert-by-default contract mean an operator can always answer "is offload on, for which slices, from which config?" — and the default (no config present) is byte-identical to today. The visibility has value independent of ever flipping the switch.

## 2. Gating conditions (when to actually build each phase)

| Phase | Gate |
|---|---|
| **A (config-loader)** | Buildable any time — it's pure plumbing + transparency, off-by-default, no quality risk. The only reason to wait is priority: it's behind Lever 2/3. Build it when you want the transparency or are about to do Phase B. |
| **B (live offload)** | ALL of: (a) Lever-2/3 re-measurement (`ctx_compose.py` on a post-Lever-2 build-phase window) shows you still want more reduction; (b) you want local offload for privacy/quota; (c) the bake-off (§4 Phase B Step B1) certifies a specific slice at agreement ≥ threshold; (d) a local endpoint exists + is operationally reliable (WSL2 llama-swap + keep-alive). Miss any → don't enable that slice. |

## 3. Existing context (verified reuse)

- **`switchboard/` package** — `local_judge` (defer-safe; short-circuits to `defer` with no network when offload not allowed), `run_shadow` (run candidate vs Claude reference, report agreement + quota saved, **auto-revert if disagreement > 0.20**), `config.py` (`SwitchboardConfig`, default-deny `offload_allowed`), `metrics.py`. Phase 1 shipped on branch `switchboard-phase-1` (87 tests, mypy --strict, ruff clean), UNMERGED.
- **`/offload-scan`** — generates an `offload-config.json` + the role taxonomy (ORCH/AUTHOR/PLAN/JUDGES/GATE/MECH/SOLO) and the one safety rule: *only a cheap fan-out array of judges/graders is downgrade-safe; authorship/planning/orchestration/gating stay on Claude.*
- **Bake-off rigs to generalize (don't build from scratch):** void_furnace's `benchmark` CLI (frozen seed suite × models × N-judge averaging + per-call cost/latency + JSONL) and switchboard's `run_shadow` (agreement vs reference + auto-revert). The OMR bake-off already proved the taxonomy empirically: cheap models win all non-coder judge/grade roles; coding is HELD.
- **Safety net (the keystone link to judging):** the judging-Phase-2 calibration harness (`_shared/calibrate_judge.py`) is the deterministic per-commit half; judging Phase 3's deferred live stochastic kappa sweep is the *same artifact* as the Phase-B bake-off (N-sample frozen-suite agreement vs a reference + a kill threshold). Building the bake-off once retires that Phase-3 debt too.

## 4. Phases & steps

### Phase A — config-loader (= the existing #216–221 plan; do not duplicate)

Build the existing [`switchboard-config-loader-plan.md`](archived-plans/switchboard-config-loader-plan.md) as-is (5 steps, #217–221 under umbrella #216): a defer-safe config loader (`load_config()` resolution `arg → $SWITCHBOARD_CONFIG → ~/.switchboard/config.json → inert defaults`), the `judge` hot-path wiring (broken config → `config_error` defer, never a crash), the loud `python -m switchboard config` pre-flight, the one-source-of-truth `ALLOWED_TOP_LEVEL_FIELDS`, docs, and an operator live smoke. It already embodies the off-by-default + transparency framing this plan wants.

**This plan's only change to Phase A:** re-label its umbrella as a sub-phase of this optional arc and add a one-line "build behind Lever 2/3" priority note — no scope change. Build via `/build-phase --plan docs/switchboard-config-loader-plan.md` from its worktree when ready.

### Phase B — live offload enablement (new; gated per §2)

#### Step B1: Slice bake-off harness (the validation engine)
- **Problem:** Generalize void_furnace's `benchmark` CLI + switchboard's `run_shadow` into one harness that scores a slice's candidate runners (Opus vs Sonnet vs Haiku vs local) on a **frozen suite of real slice prompts** by **agreement-with-Opus + cost + latency**, with the 0.20 disagreement kill criterion deciding pass/fail per slice. Reuse the rigs; do not rebuild. (This is also judging Phase 3's live sweep — same machinery, reference = Opus instead of gold.)
- **Type:** code · **Flags:** --reviewers code
- **Done when:** the harness runs a frozen slice suite across ≥2 candidate runners, emits per-slice {agreement, cost, latency, pass/fail at 0.20}; deterministic given recorded candidate outputs; one real run recorded for the chosen first slice.

#### Step B2: Certify + enable the first safe slice
- **Problem:** Run B1 on the **`review-deep-style` / `review-gauntlet-style`** slice (the only one whose Claude-final-judge precondition is structurally met today — Style advises, Claude gates). If it certifies (agreement ≥ threshold), enable it via the Phase-A config (a real `offload-config.json` installed to `~/.switchboard/config.json`), with `run_shadow` left on to auto-revert on live disagreement. **`build-step-style` stays OFF** (it gates directly — Decision 3).
- **Type:** code + operator (split per build-phase) · **Flags:** --reviewers code
- **Done when:** B1 certifies the slice (or explicitly does NOT — a "do not enable" result is a valid, shippable outcome); if certified, `python -m switchboard config` reports it ON and a live review-deep run uses the local model for Style only while Claude still gates; `run_shadow` auto-revert verified to fire on injected disagreement.

#### Step B3 (optional, orthogonal): effort-tier the judge slices
- **Problem:** Per the investigation, `effort: low` on judge/grade sub-agents may be a bigger, safer win than `model: haiku` (it sidesteps the model-downgrade quality cliff). Add `effort` as a first-class policy verb alongside `model`/`allow`/`deny`/`downgrade` in the config, and a bake-off arm comparing `effort:low` vs `model:haiku` on the judge slices.
- **Type:** code · **Flags:** --reviewers code
- **Done when:** the config supports an `effort` verb; the bake-off reports the effort-vs-model arm; recommendation recorded.

## 5. Out of scope / explicitly NOT building

- **Enabling offload by default** — every slice stays off until B1 certifies it AND the operator opts in. No-config = inert = today's behavior.
- **`build-step-style` offload** — build-step Step 7 IS the merge gate; a weak model never owns it (Decision 3). Stays `false`.
- **The Lever-2/3 token work** — separate (branch `token-levers-l2-l4a`); this plan is gated *behind* it.
- **Endpoint provisioning / WSL2 llama-swap keep-alive** — operational, not code; a prerequisite for B2's live run, deferrable (B1's recorded-output mode proves the harness without a live endpoint).

## 6. Relationship to the broader strategy

This is the **mechanism layer** of one program ("cheapen the pipeline without making it dumb"): the judging doctrine + calibration gate say *what* is safe to cheapen; the token levers prioritize the cost moves; this plan is the plumbing + certification for the offload subset. It is deliberately last and optional — the cheap wins (Lever 2/3) come first, and this only earns its place once they're measured and you want local offload as a capability.
