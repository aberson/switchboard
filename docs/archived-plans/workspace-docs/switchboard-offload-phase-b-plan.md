# Plan — Switchboard offload Phase B (live offload enablement)

> **Toolkit program authority — 2026-09-24.** For units mapped from this document, the [toolkit program](../plan.md) owns selection, shared sequencing and current execution/status; the [source-unit ledger](../documentation/toolkit-program-units.md) identifies that mapped scope. Status and execution instructions retained below for transferred units are source history, not a second dispatch queue. Technical specifications, original IDs, acceptance criteria and evidence remain owned here. Update transferred-unit status in the program only; unmapped local work remains locally owned. Mapping does not complete, reopen or authorize a unit.

> Feature plan seeded from §4 "Phase B" of [`switchboard-offload-plan.md`](switchboard-offload-plan.md).
> Pipeline: this doc → `/plan-review` → `/plan-wrap` → `/repo-sync` → `/build-phase`.
> Run `/plan-expedite --plan docs/switchboard-offload-phase-b-plan.md` to chain the middle stages.

## 1. What This Feature Does

Phase 1 shipped a built, tested local-offload core (`switchboard/`) with six skills carrying
**inert** offload branches, and Phase A (config-loader, PR #233) shipped the operator on-switch
+ transparency. **Phase B actually turns the first slice on** — but only after a bake-off
certifies it safe. It delivers:

- **B1 — a slice bake-off harness**: scores a slice's candidate runners (Opus-reference vs
  local, extensible) on a frozen suite of real slice prompts by *agreement-with-reference +
  cost + latency*, with the 0.20-disagreement kill criterion deciding pass/fail. Deterministic
  in a recorded-output mode (needs no live endpoint, no PR #233 merge). This harness **is** the
  same machinery judging-Phase-3's deferred live stochastic-kappa sweep needs — building it once
  retires that debt too (reference = Opus instead of a gold label).
- **B2 — certify + enable the `review-deep-style` slice**: run B1 on the only slice whose
  Claude-final-judge precondition is structurally met today (Style advises, Claude still gates).
  If it certifies, flip it on via the Phase-A config, with `run_shadow` left on to surface a
  live-disagreement kill signal. A "do not enable" result is an equally valid, shippable outcome.
- **B3 (optional, orthogonal)** — add an `effort` policy dimension and a bake-off arm comparing
  `effort:low` vs `model:haiku` on the judge slices. Recommendation-only this phase.

**Why build this** — capability, not cost. Per the token-levers investigation, offload is the
*smallest* token lever; the value here is **privacy** (judge prompts never leave the machine)
and **local-quota** capability, plus retiring the judging-Phase-3 live-sweep debt. It is
deliberately optional and gated.

## 2. Existing Context

A fresh-context model should know these load-bearing facts (all verified against producing
files this session, not docs):

- **switchboard is zero-dependency by design.** `switchboard/pyproject.toml` line 7:
  `dependencies = []`; `client.py` is stdlib-only (`urllib`, no network deps). **Any new code in
  switchboard must preserve this.** (This is why B1 ports a *shape*, not a package — see
  Design Decision 1.)
- **`run_shadow` is the agreement+kill engine** — [`switchboard/switchboard/harness.py`](../switchboard/switchboard/harness.py):
  `run_shadow(cases, *, config, kill_threshold=0.20, task_class, metrics) -> ShadowReport`.
  Each `ShadowCase` carries an `expected` (reference/Claude) verdict supplied as a label (NOT
  computed). A **defer is not a disagreement** — it's excluded from the agreement denominator.
  `ShadowReport` already computes `agreement_rate`, `disagreement_rate`, `quota_saved`, and
  `kill` (revert when `disagreement_rate > kill_threshold`). What it lacks vs a bake-off: a
  multi-*runner* matrix, per-runner cost/latency, a frozen-suite loader, and JSONL output.
- **void_furnace's benchmark is the report-shape reference** (not a dependency) —
  [`void_furnace/src/void_furnace/benchmark/`](../void_furnace/src/void_furnace/benchmark/):
  `runner.py` (`BenchmarkRow`/`BenchmarkReport`: matrix × N-judge averaging × cost+latency),
  `report.py` (`render` markdown + `render_jsonl`), `cli.py` (`void_furnace benchmark --role
  --models --judges --suite`). It is **heavily coupled** to `void_furnace.harness`,
  `void_furnace.models.factory.get_client`, `void_furnace.cost`, and role prompts — so it is a
  proven design to mirror, never imported.
- **The skill→judge wiring already exists.** A wired SKILL.md invokes the judge via
  `python -m switchboard judge --site <task_class> --prompt-file <path>` (one JSON object,
  always exit 0; defers with no network when off). [`review-deep/SKILL.md`](../.claude/skills/review-deep/SKILL.md)
  lines 251–265 already dispatch `--site review-deep-style` with full defer-fallback. **B2 adds
  no skill wiring** — it certifies and enables.
- **The enable config + installers already exist** — `switchboard/scripts/offload-config.template.json`
  (the 6 live slices, `build-step-style: false`), `scripts/start-offload.ps1`,
  `scripts/install-offload-icon.ps1`. The README §"Turning offload ON" documents the operator switch.
- **`review-deep-style` is the canonical slice name** (used across `cli.py`, the template,
  README line 74, and `test_cli.py`). The `style-lens` string in `run_shadow_live.py` and
  `test_harness.py` is a generic *test placeholder*, not a competing production slice.
- **Phase A (PR #233) config surface that B2/B3 build on** —
  [`config.py`](../switchboard/switchboard/config.py) on branch `switchboard-config-loader`:
  `SwitchboardConfig(less_token_mode, enabled_call_sites: dict[task_class, bool|str], base_url,
  model, cold/warm_timeout_s, max_tokens)`; `from_mapping()` rejecting unknown keys against
  `ALLOWED_TOP_LEVEL_FIELDS` (auto-derived from `fields(SwitchboardConfig)` — single source of
  truth); `load_config(path) -> (config, source_label)` with 4-tier resolution
  (arg → `$SWITCHBOARD_CONFIG` → `~/.switchboard/config.json` → inert defaults).
- **Phase A renamed the default config path** `~/.switchboard/offload-config.json` →
  `~/.switchboard/config.json`. The main-repo README + installer scripts still reference the old
  name (9 references found) — B2a reconciles them.

## 3. Scope

**In scope:**
- A switchboard-native multi-runner bake-off harness (B1) — zero new runtime deps; JSON frozen
  suite; recorded-output deterministic mode + a real live recording captured in B2b.
- A hand-authored `review-deep-style` frozen suite (~6–10 cases) with reference verdicts.
- Certification of `review-deep-style` and, if it passes, enabling it via the Phase-A config
  (`~/.switchboard/config.json`) with the kill signal left on (B2).
- Reconciling the config-path drift Phase A introduced (B2a).
- (Optional) an `effort` config dimension + an effort-vs-model bake-off arm + recommendation (B3).

**Explicitly out of scope:**
- Enabling any slice **by default** — every slice stays off until B1 certifies it AND the
  operator opts in. No-config = inert = today.
- **`build-step-style` offload** — build-step Step 7 is the merge gate; a weak model never owns
  it (Decision 3). Stays `false`.
- Cross-importing `void_furnace.benchmark` into switchboard (would break the zero-dep contract).
- Extracting a shared bake-off package (viable long-term per the operator, but a void_furnace
  refactor beyond Phase B — noted in Design Decision 1).
- Endpoint provisioning / WSL2 llama-swap keep-alive (operational prerequisite for B2b, not code).
- The Lever-2/3 token re-measurement that gate (a) calls for — **consciously waived** (see below).

**Gate (a) waiver (carried from the offload-plan §2 gating table).** Phase B is gated behind
*(a)* a Lever-2/3 re-measurement showing more reduction is still wanted, *(b)* wanting local
offload for privacy/quota, *(c)* a bake-off certifying a slice, *(d)* a reliable local endpoint.
Gate (a)'s re-measurement was **not performed** (the RIDER cherry-pick `bcd59c6` conflicted on
diverged SKILL.md files). The operator consciously elected to pursue Phase B anyway on the
**capability/privacy** rationale (b), with (c) and (d) satisfied inside this plan (B1/B2). This
waiver is deliberate and recorded; it is not an oversight.

## 4. Impact Analysis

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `switchboard/switchboard/harness.py` | reuse (no edit expected) | B1 calls `run_shadow` per-runner as the agreement+kill engine | Read: `run_shadow(cases, *, config, kill_threshold, task_class, metrics)` — per-runner call needs no signature change |
| `switchboard/pyproject.toml` | modify | B1 may register `suites/` as package data + add test paths; **must keep `dependencies = []`** | Read: line 7 `dependencies = []`; `[tool.hatch.build.targets.wheel] packages = ["switchboard"]` |
| `switchboard/switchboard/config.py` (post-#233) | modify (B3 only) | B3 adds an `effort` dimension; `ALLOWED_TOP_LEVEL_FIELDS` auto-widens from `fields()` | Read (worktree): `from_mapping` checks `ALLOWED_TOP_LEVEL_FIELDS` (line 139); allow-list derived line 181 |
| `switchboard/README.md` | modify (B2a) | reconcile config path (`offload-config.json`→`config.json`); document the bake-off + cert | grep: `offload-config.json` referenced (README §"Turning offload ON", lines 64/70/73) |
| `switchboard/scripts/start-offload.ps1` | modify (B2a) | installer writes the old path name | grep: writes `~/.switchboard/offload-config.json` |
| `switchboard/scripts/install-offload-icon.ps1` | modify (B2a, verify) | desktop-icon launcher may reference old path | glob: file exists; grep B2a confirms before edit |
| `switchboard/scripts/offload-config.template.json` | modify (B2a, verify) | template filename + README "Manual" copy-target reference the old path | Read: template content is the 6-slice map; filename referenced by README |
| `switchboard/tests/conftest.py` + `tests/test_config_loader.py` | modify (B2a, if path changes) | path fixtures pin the config filename | grep: both reference the config path |
| `.claude/skills/tier-offload/test_sample_config_loads.py` | modify (B3 only) | round-trip test imports `ALLOWED_TOP_LEVEL_FIELDS`; adding `effort` widens it | glob: file exists; it is the producer↔consumer round-trip guard for the config schema |
| `.claude/skills/tier-offload/sample-offload-config.json` + `sample-inventory.md` + `SKILL.md` | modify (B3 only) | sample config + inventory must show the new `effort` verb | glob: all three exist under tier-offload |
| `.claude/skills/review-deep/SKILL.md` | **no change** | Style-lens local-judge dispatch already wired + defer-safe | Read: lines 251–265 already call `python -m switchboard judge --site review-deep-style` |

## 5. New Components

- **`switchboard/switchboard/bakeoff.py`** (B1) — the multi-runner bake-off harness. Drives
  `run_shadow` once per candidate runner over the frozen suite, collects per-runner
  `{agreement_rate, disagreement_rate, cost, latency, pass/fail@0.20}`, and renders a report.
  Ports void_furnace's `BenchmarkRow`/`BenchmarkReport` *shape* and a `render` + `render_jsonl`
  pair (stdlib `json` only). A **recorded-output mode** reads candidate verdicts/cost/latency
  from committed JSON fixtures so the whole harness is deterministic with no endpoint.
- **`switchboard/suites/review-deep-style.json`** (B1) — hand-authored frozen suite (~6–10
  representative review-deep Style-lens cases: real prompt shape, hand-labelled reference
  verdicts, short labels). Modeled on `run_shadow_live.py`'s 4-case pattern, scaled up.
- **`switchboard/suites/recorded/review-deep-style-*.json`** (B1) — recorded candidate-runner
  outputs feeding the deterministic mode; the live recording from B2b updates the real one.
- **`switchboard/tests/test_bakeoff.py`** (B1) — golden/deterministic tests: suite loading,
  per-runner aggregation, the 0.20 pass/fail boundary, markdown + JSONL rendering.
- **A `python -m switchboard bakeoff` subcommand** (B1) — mirrors void_furnace's CLI shape
  (`--suite`, `--runners`, `--recorded/--live`, `--output-dir`); writes `report.md` +
  `scores.jsonl`, prints one grep-able summary line.
- **A certification helper** (B2a) — turns a `bakeoff` report into a shippable
  PASS / "do-not-enable" verdict for `review-deep-style`, plus the staged enable config.

## 6. Design Decisions

1. **B1 ports void_furnace's report shape into switchboard; it does not import void_furnace.**
   *Rationale (operator-confirmed):* switchboard is intentionally zero-dependency, and
   void_furnace's benchmark module is heavily coupled to `void_furnace.harness` /
   `models.factory` / `cost` / role prompts and pulls in `pyyaml`. Importing it would shatter
   switchboard's stdlib-only contract and couple two repos across separate Windows venvs. The
   operator's intent in citing void_furnace was "useful code to reference," not to break the
   zero-dep goal. *Alternatives:* (a) cross-import — **rejected** (breaks zero-dep). (b) extract a
   shared standalone `bakeoff-core` package both repos depend on — viable long-term but requires
   refactoring void_furnace's shipped, tested benchmark module (large blast radius); **deferred**
   beyond Phase B. The frozen suite is **JSON, not YAML**, for the same zero-dep reason.

2. **Reference runner = Opus; the kill criterion is agreement-with-reference > 0.20 disagreement.**
   This reuses `run_shadow`'s existing semantics verbatim (reference supplied as the `expected`
   label, defers excluded from the denominator) and makes B1 byte-for-byte the artifact
   judging-Phase-3's live stochastic-kappa sweep needs. Minimum matrix is **≥2 runners**
   (Opus-reference + local); Sonnet/Haiku arms are optional extensions.

3. **B2 splits into a code step (B2a) and an operator step (B2b)** per the build-phase rule that
   `Type: operator` steps must not produce code and `Type: code` steps must not gate on operator
   review. B2a is all the deterministic plumbing (cert helper, config reconciliation, an
   injected-disagreement auto-revert test). B2b is the live observation (endpoint up, config
   installed, real review-deep run, kill-signal-fires check). The seed's "record one real run for
   the chosen first slice" is satisfied in **B2b** (which has the endpoint), keeping B1 endpoint-free.

4. **The kill signal auto-disables the offending slice** *(revised 2026-07-06, issue #261;
   originally advise-only)*. `run_shadow` *computes* `kill=True` on excess disagreement; the
   `switchboard.monitor` consumer (`disable_slice_on_kill` / `monitor_deployed_slice`) then flips
   `enabled_call_sites[task_class]` to `False` in the deployed config — reverting JUST that slice
   to defer-to-Claude, byte-for-value-preserving every other field, and degrading safely on a
   malformed/missing/unwritable config. The original advise-only stance (operator deletes the file)
   was reversed so a confident-but-wrong local judge stops costing verdict quality the moment its
   disagreement trips the threshold. The consumer is built + crash-safe-tested but **not yet wired
   to a standing invocation** (no `monitor` CLI subcommand / scheduler exists); that wiring lands
   with B2b (#237). This resolves the §8 open question in favour of auto-disable.

5. **`review-deep-style` only; `build-step-style` stays off.** Style advises while the
   review-deep aggregator (Claude) still owns the pass/fail decision — the one slice whose
   Claude-final-judge precondition holds today. build-step Step 7 *is* the merge gate, so it never
   offloads (Decision 3).

6. **B3 is honest about its consumer gap.** `effort:low` / `model:haiku` are *Claude-side
   sub-agent dispatch* knobs (Workflow/Agent opts), distinct from switchboard's local-endpoint
   `local_judge` (which talks to one local model and has no effort knob). B3 therefore adds the
   config *dimension* + a measurement arm + a recommendation, but **wiring a consumer that acts on
   `effort` is out of scope** this phase. B3 stays optional/deferrable.

## 7. Build Steps

<!-- autofix-applied: 2026-06-23 -->
### Step 1: B1 — Slice bake-off harness
- **Problem:** Build a switchboard-native multi-runner bake-off harness that scores a slice's
  candidate runners on a frozen JSON suite by agreement-with-reference + cost + latency, with the
  0.20 disagreement kill criterion deciding pass/fail per runner. Reuse `run_shadow` as the
  agreement+kill engine and **port** void_furnace's `BenchmarkReport`/`render_jsonl` shape (do not
  import void_furnace; keep `dependencies = []`). Ship a recorded-output deterministic mode and a
  hand-authored `review-deep-style` seed suite (~6–10 real-shaped cases). This harness is also the
  judging-Phase-3 live-sweep artifact.
- **Type:** code
- **Issue:** #235
- **Flags:** --reviewers code
- **Produces:** `switchboard/switchboard/bakeoff.py`, `switchboard/suites/review-deep-style.json`,
  `switchboard/suites/recorded/*.json`, `switchboard/tests/test_bakeoff.py`, a
  `python -m switchboard bakeoff` subcommand (writes `report.md` + `scores.jsonl`).
- **Done when:** the harness runs the frozen suite across ≥2 candidate runners and emits per-runner
  `{agreement, cost, latency, pass/fail@0.20}`; it is deterministic given recorded candidate
  outputs (a committed golden test passes with no endpoint and no PR #233 merge); `mypy --strict`
  + `ruff` clean; `dependencies = []` unchanged.
- **Depends on:** none
- **Status:** DONE (2026-06-24)

<!-- autofix-applied: 2026-06-23 -->
### Step 2: B2a — Certify review-deep-style + enablement plumbing
- **Problem:** Add a certification helper that turns a B1 `bakeoff` report for `review-deep-style`
  into a shippable PASS / "do-not-enable" verdict, stage the enable config at the Phase-A canonical
  path (`~/.switchboard/config.json`), reconcile the stale `offload-config.json` references the
  Phase-A rename left in the README + installer scripts, and add an automated test proving the
  `run_shadow` kill signal fires on injected disagreement (`disagreement_rate > 0.20 → kill=True`).
- **Type:** code
- **Issue:** #236
- **Flags:** --reviewers code
- **Produces:** certification helper + staged enable config (`review-deep-style: true`); updated
  `switchboard/README.md` + `scripts/start-offload.ps1` (+ `install-offload-icon.ps1` /
  `offload-config.template.json` / test fixtures as the grep requires); a new injected-disagreement
  auto-revert test.
- **Done when:** the cert helper emits a deterministic PASS/do-not-enable verdict from a B1 report;
  the injected-disagreement test asserts `kill=True`; `grep -ri offload-config.json switchboard/`
  returns only intentional/historical references (all live paths reconciled to `config.json`);
  `load_config()` round-trips the staged config; quality gates green.
- **Depends on:** Step 1 (B1); **PR #233 merged to master** (B2a installs a config the Phase-A loader reads).
- **Status:** DONE (2026-06-24)

<!-- autofix-applied: 2026-06-23 -->
### Step 3: B2b — Live certify-and-enable smoke (operator)
- **Problem:** With the local endpoint up, run the bake-off live for `review-deep-style`, record the
  real candidate outputs back into B1's fixtures, then either enable the slice (if certified) or
  record a shippable "do not enable" result. Confirm the live offload behaves: Style runs local
  while Claude still gates, and the kill signal fires on injected disagreement.
- **Type:** operator
- **Issue:** #237
- **Done when (operator confirms each):**
  1. WSL2 llama-swap `general-35b` is up on `localhost:8080` with the keep-alive holding the relay;
     `python -m switchboard` live smoke reaches it.
  2. `python -m switchboard bakeoff --suite review-deep-style --live` produces a report; the real
     candidate outputs are committed as the recorded fixture.
  3. If certified: the enable config is installed at `~/.switchboard/config.json` and
     `python -m switchboard config` reports `review-deep-style` **ON** (effect-based check, not the
     file's mere presence).
  4. A real `review-deep` run over a sample diff uses the **local** model for the Style lens only
     (a `verdict`, not a `defer`) while the aggregator's pass/fail stays a Claude judgment.
  5. `run_shadow` auto-revert kill signal **fires** on an injected-disagreement run (`kill=True`).
  6. A "do not enable" certification is recorded as a valid shippable outcome if the slice fails.
- **Depends on:** Step 2 (B2a); a reliable local endpoint (gate (d)). *(Set `max_tokens` ≥ 2000 in the live
  config — general-35b is a reasoning model; the 800 default truncates. This is the one always-on/
  event-driven surface in Phase B; this step is its end-to-end observation gate.)*

<!-- autofix-applied: 2026-06-23 -->
### Step 4: B3 — Effort-tier the judge slices (optional, orthogonal)
- **Problem:** Add an `effort` policy dimension to the offload config (a first-class verb alongside
  the existing `enabled_call_sites`), and a B1 bake-off arm comparing `effort:low` vs `model:haiku`
  on the judge slices. Per code-quality one-source-of-truth + grep-all-consumers discipline, adding
  a config field auto-widens `ALLOWED_TOP_LEVEL_FIELDS` (derived from `fields()`) — so the
  tier-offload producer, its sample config, and the round-trip test must move in lockstep. Honest
  scope: `effort` is consumed by Claude-side sub-agent dispatch, not switchboard's local client, so
  this step delivers the dimension + measurement + a recommendation, not a live consumer.
- **Type:** code
- **Issue:** #238
- **Flags:** --reviewers code
- **Produces:** an `effort` field on `SwitchboardConfig`; updated `tier-offload` sample config +
  inventory + `test_sample_config_loads.py` round-trip; a bake-off effort-vs-model arm in the B1
  report; a recorded recommendation.
- **Done when:** the config accepts and round-trips an `effort` verb (with `ALLOWED_TOP_LEVEL_FIELDS`
  asserted to include it via the auto-derivation, not a hardcoded list); the tier-offload round-trip
  test passes with the new field; the bake-off reports the effort-vs-model arm; a recommendation is
  recorded; quality gates green.
- **Depends on:** Step 1 (B1); Step 2 (B2a) (config surface). *Optional — may be deferred without blocking Steps 1–3 (B1/B2); run `/build-phase ... --steps 1,2,3` to exclude it from the default build range.*
- **Status:** DONE (2026-06-24)

## 8. Risks and Open Questions

| Item | Risk | Mitigation |
|---|---|---|
| Gate (a) waived (no Lever-2/3 re-measurement) | Building capability not strictly cost-justified | Conscious operator waiver on the privacy/quota rationale (§3); offload stays optional + off-by-default |
| B2 depends on PR #233 merge + live endpoint | B2 blocked if either slips | B1 is endpoint-free + merge-free (build first); B2a gates on the merge; B2b gates on the endpoint |
| Config-path drift (`offload-config.json` vs `config.json`) | Offload silently inert if installer writes the path the loader no longer reads | B2a reconciles all 9 references; B2b confirms ON via `python -m switchboard config` (effect-based, not file-presence) |
| Kill signal must actually revert, not just report | A confident-but-wrong local judge keeps costing verdict quality until a human notices | RESOLVED (#261): `switchboard.monitor.disable_slice_on_kill` auto-flips the tripped slice to `False` on `kill=True` (byte-for-value-safe, defer-safe on bad config). Consumer built + tested; standing invocation (CLI/scheduler) wired in B2b (#237) |
| Hand-authored suite may not match real Style-lens distribution | Certification on unrepresentative cases | Use real prompt *shape*; B2b records a real live run; `run_shadow` stays on in production as the live tripwire |
| B3 `effort` verb has no consumer in switchboard's local client | Building a config dimension nothing acts on | B3 explicitly recommendation-only + measurement; marked optional/deferrable; honest-scope note in Design Decision 6 |
| ~~**Open:** does production need an automatic config-disable on `kill=True`?~~ **RESOLVED 2026-07-06 (#261): yes** | — | Auto-disable via `switchboard.monitor` (Design Decision 4). Consumer built + tested; standing invocation wired in B2b (#237) |
| **Open:** which candidate runners beyond Opus-reference + local for B1's matrix? | — | Default ≥2 (Opus-reference + local); Sonnet/Haiku optional arms; confirm at B1 build time |

## 9. Testing Strategy

- **B1 (deterministic, no endpoint):** golden test over committed recorded fixtures — suite
  loading, per-runner aggregation (agreement/cost/latency), the 0.20 pass/fail boundary, and
  markdown + JSONL rendering. Assert `dependencies = []` is preserved (no new imports). This is the
  primary gate that the bake-off works without a live model.
- **B2a:** cert-helper unit test (both PASS and do-not-enable are shippable verdicts); an
  injected-disagreement test asserting `run_shadow` returns `kill=True`; a `load_config()`
  round-trip over the staged enable config; a grep assertion that no live path still says
  `offload-config.json`.
- **B2b (operator live smoke — the end-to-end observation / data-pipeline gate):** one real cycle
  with real components wired — endpoint reachable, config installed, `python -m switchboard config`
  reports the slice ON, a real review-deep run routes Style local while Claude gates, and the kill
  signal fires on injected disagreement. This is the deliberate "run it for real and watch it" step
  the offload's event-driven behavior requires (unit tests mock the endpoint boundary).
- **B3:** config round-trip with the `effort` field (asserting `ALLOWED_TOP_LEVEL_FIELDS` picks it
  up via auto-derivation, not a hardcoded membership list); the tier-offload round-trip test green
  with the new field; the bake-off effort-vs-model arm renders.
- **Existing tests that may break:** B2a's path rename touches `tests/conftest.py` /
  `test_config_loader.py` path fixtures; B3's field addition touches
  `tier-offload/test_sample_config_loads.py` and any test asserting an exact
  `ALLOWED_TOP_LEVEL_FIELDS` membership. Both are expected, in-scope updates — review the diffs for
  the codifying-a-regression anti-pattern (a storage/shape change that quietly rewrites assertions).
