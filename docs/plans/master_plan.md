# Switchboard master plan

Source-scoped IDs B1-B4 = original Phase B Steps 1-4; O70-O74 = operator surfaces; P1-P7 = <friend-project> Phase 2; T1-T10 = proposed switchboard-tune sibling. Internal step references inside a track retain that source track namespace.

Proposal: [reconciliation](../plan-reconciliation/proposal.html). Original source bytes: [move map](../plan-reconciliation/source-map.md).

## Vision

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

Provides an operator-readable routing/config/health report, promotes the deterministic bakeoff,
and resolves stale or one-time launcher buttons without changing fail-open routing semantics.

Proposal: [Utility Projects UAT proposal](../../../docs/utility-project-surfaces-proposal.html)

## Principles

Stdlib-only Switchboard remains inert without config; local judges are advisory, fail-safe to Claude and never a merge/correctness gate. `build-step-style` remains disabled. A failed certification never enables a slice. Deleting config restores disabled state. The Toolkit [program](../../../plan.md) and [unit ledger](../../../documentation/toolkit-program-units.md) retain execution/status ownership of mapped units. This consolidation changes no status or external-project authorization.

| Phase | Gate |
|---|---|
| **A (config-loader)** | Buildable any time — it's pure plumbing + transparency, off-by-default, no quality risk. The only reason to wait is priority: it's behind Lever 2/3. Build it when you want the transparency or are about to do Phase B. |
| **B (live offload)** | ALL of: (a) Lever-2/3 re-measurement (`ctx_compose.py` on a post-Lever-2 build-phase window) shows you still want more reduction; (b) you want local offload for privacy/quota; (c) the bake-off (§4 Phase B Step B1) certifies a specific slice at agreement ≥ threshold; (d) a local endpoint exists + is operationally reliable (WSL2 llama-swap + keep-alive). Miss any → don't enable that slice. |

## Glossary



| Term | Meaning |
|---|---|
| **LoRA** | Low-Rank Adaptation — trains small adapter matrices alongside frozen base weights instead of updating all parameters. |
| **QLoRA** | LoRA applied on top of a 4-bit-quantized frozen base, cutting VRAM enough to fine-tune on a laptop GPU. |
| **SFT** | Supervised fine-tuning — training on (prompt, desired-output) pairs. Here the desired output is Claude's verdict JSON. |
| **DPO** | Direct Preference Optimization — trains on (chosen, rejected) response pairs rather than single targets. The optional Step 10. |
| **GGUF** | The on-disk model format llama.cpp loads. Produced from HF weights by `convert_hf_to_gguf.py`. |
| **llama.cpp / llama-server** | The C++ inference engine and its OpenAI-compatible HTTP server. |
| **llama-swap** | The WSL2 service on `localhost:8080` that fronts llama.cpp and swaps models on demand. Installed by void_furnace, shared with switchboard. |
| **slice** | switchboard's unit of offload routing: a `task_class` string key in `enabled_call_sites`. This project targets exactly one, `review-deep-style`. |
| **defer** | switchboard's fail-safe outcome — a dict carrying `"defer": True`, meaning the caller routes the judgment to Claude instead. Never an exception. |
| **bake-off / certify** | `python -m switchboard bakeoff` scores runners against a suite; `certify_slice` turns that report into a pass/fail under the kill threshold. |
| **kill rule** | A slice is disabled when its disagreement rate is **strictly greater than** 0.20, with defers excluded from the denominator. |
| **Jaccard similarity** | Intersection-over-union on token sets; used in Step 2 at a 0.9 threshold to catch near-duplicate hunks spanning train and test. |
| **golden set** | The frozen, hash-pinned test split. Frozen before training so it cannot be tuned against. |

---

## How to read this plan

The shared offload client/config/bakeoff substrate is the spine. Operator surfaces extend it. The <friend-project> contribution is a separate external-repository track; tune is a proposed sibling repository not yet present. Neither external track is an active Switchboard implementation queue. Historical default `general-35b` references explain earlier evidence; current documented default is non-reasoning `coder-30b`, 800 default/600 minimum tokens. Verify actual deployed config at execution. Source step numbers and P/D decisions remain source-scoped. Code paths beginning `switchboard/`, `switchboard-tune/`, or `<friend-project>/` are workspace-relative; other relative code paths follow their named repository. Markdown references are rebased.

## Execution mode

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

Unit-test inspect state combinations, effective model resolution, and the exported cross-package
fixture; the dev-observatory plan owns consumer integration tests and doctor. Then perform
endpoint-down/up UAT without changing the fail-open default.

Completed gates are historical evidence. Manual acceptance remains manual; no live endpoint is contacted by this cleanup. Before B3 operator acceptance, resolve its standing monitor-invocation readiness gap through the owning implementation workflow; do not ask the operator to write missing code.

## Track structure

A completed config-loader Phase A and accepted core supply the shared substrate. B1/B2/B4 and O70-O73 have recorded DONE status. B3 and O74 remain distinct live acceptances. P1-P6 record completion on external feature branches, with visual smoke still owed in P7. T1-T10 remain proposed; T10 is conditional. Original umbrella B1/B2/B3 descriptions are subsumed by concrete B1-B4, not additional work.

## Decision graph

```text
completed config-loader -> B1 -> B2 -> B3 live certification
                         B4 orthogonal effort dimension (DONE)
O70 -> O71 -> O72 -> O73 -> O74 real routing UAT
P1 -> P2 -> P3 -> P4; P5 -> P6; P4 + P6 -> P7 external UAT/PRs
T1 -> T2 -> T3 -> T4 real substrate smoke -> T5 baseline -> T6 SFT
 -> T7 honest comparison -> T8 certify/report -> T9 operator decision
T7 -> T10 only if declared disagreement predicate passes
```

## Baseline

A fresh-context model should know these load-bearing facts (all verified against producing
files this session, not docs):

- **switchboard is zero-dependency by design.** `switchboard/pyproject.toml` line 7:
  `dependencies = []`; `client.py` is stdlib-only (`urllib`, no network deps). **Any new code in
  switchboard must preserve this.** (This is why B1 ports a *shape*, not a package — see
  Design Decision 1.)
- **`run_shadow` is the agreement+kill engine** — [`switchboard/switchboard/harness.py`](../../switchboard/harness.py):
  `run_shadow(cases, *, config, kill_threshold=0.20, task_class, metrics) -> ShadowReport`.
  Each `ShadowCase` carries an `expected` (reference/Claude) verdict supplied as a label (NOT
  computed). A **defer is not a disagreement** — it's excluded from the agreement denominator.
  `ShadowReport` already computes `agreement_rate`, `disagreement_rate`, `quota_saved`, and
  `kill` (revert when `disagreement_rate > kill_threshold`). What it lacks vs a bake-off: a
  multi-*runner* matrix, per-runner cost/latency, a frozen-suite loader, and JSONL output.
- **void_furnace's benchmark is the report-shape reference** (not a dependency) —
  [`void_furnace/src/void_furnace/benchmark/`](../../../void_furnace/src/void_furnace/benchmark):
  `runner.py` (`BenchmarkRow`/`BenchmarkReport`: matrix × N-judge averaging × cost+latency),
  `report.py` (`render` markdown + `render_jsonl`), `cli.py` (`void_furnace benchmark --role
  --models --judges --suite`). It is **heavily coupled** to `void_furnace.harness`,
  `void_furnace.models.factory.get_client`, `void_furnace.cost`, and role prompts — so it is a
  proven design to mirror, never imported.
- **The skill→judge wiring already exists.** A wired SKILL.md invokes the judge via
  `python -m switchboard judge --site <task_class> --prompt-file <path>` (one JSON object,
  always exit 0; defers with no network when off). [`review-deep/SKILL.md`](../../../.claude/skills/review-deep/SKILL.md)
  lines 251–265 already dispatch `--site review-deep-style` with full defer-fallback. **B2 adds
  no skill wiring** — it certifies and enables.
- **The enable config + installers already exist** — `switchboard/scripts/offload-config.template.json`
  (the 6 live slices, `build-step-style: false`), `scripts/start-offload.ps1`,
  `scripts/install-offload-icon.ps1`. The README §"Turning offload ON" documents the operator switch.
- **`review-deep-style` is the canonical slice name** (used across `cli.py`, the template,
  README line 74, and `test_cli.py`). The `style-lens` string in `run_shadow_live.py` and
  `test_harness.py` is a generic *test placeholder*, not a competing production slice.
- **Phase A (PR #233) config surface that B2/B3 build on** —
  [`config.py`](../../switchboard/config.py) on branch `switchboard-config-loader`:
  `SwitchboardConfig(less_token_mode, enabled_call_sites: dict[task_class, bool|str], base_url,
  model, cold/warm_timeout_s, max_tokens)`; `from_mapping()` rejecting unknown keys against
  `ALLOWED_TOP_LEVEL_FIELDS` (auto-derived from `fields(SwitchboardConfig)` — single source of
  truth); `load_config(path) -> (config, source_label)` with 4-tier resolution
  (arg → `$SWITCHBOARD_CONFIG` → `~/.switchboard/config.json` → inert defaults).
- **Phase A renamed the default config path** `~/.switchboard/offload-config.json` →
  `~/.switchboard/config.json`. The main-repo README + installer scripts still reference the old
  name (9 references found) — B2a reconciles them.

`switchboard/config.py` owns validated config and per-site model pins; `health.py` owns endpoint
reachability; `cli.py` exposes judge/config/bakeoff. dev-observatory already reads routing state.
Current CLAUDE.md names two scripts absent from this checkout; doctor reports both BROKEN. A separate
worktree may be implementing them, so deletion before reconciliation would be unsafe.

The earlier umbrella config-loader duplicate is removed from executable scope. Existing `monitor.py` consumer does not establish that a standing invocation is wired. This remains an explicit readiness gap for B3; historical completion of enablement plumbing does not close it.

## Phases

### Shared offload contract

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

<!-- autofix-applied: 2026-06-23 -->
### Step B1: B1 — Slice bake-off harness
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
### Step B2: B2a — Certify review-deep-style + enablement plumbing
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
### Step B3: B2b — Live certify-and-enable smoke (operator)
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
### Step B4: B3 — Effort-tier the judge slices (optional, orthogonal)
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

### Operator surfaces on that same substrate

**In:** `inspect --json`, config + health + per-site effective model, stable bakeoff artifacts,
endpoint-launcher reconciliation, and observatory proof handoff. **Out:** making
local verdicts gates, auto-enabling sites, auto-starting WSL from a read-only view, or inventing
call-site evidence inside switchboard.

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `switchboard/cli.py` | extend | inspect command | judge/config/bakeoff dispatcher read directly |
| `switchboard/config.py` | reuse | effective model/site state | schema and lookup owner read directly |
| `switchboard/health.py` | reuse | endpoint/model availability | probe owner read directly |
| `switchboard/monitor.py`, `metrics.py` | inspect/reuse | recent in-process evidence if meaningful | modules exist |
| `switchboard/CLAUDE.md`, `README.md` | modify | remove stale setup claims or document shipped launcher | current stale commands inspected |
| `switchboard/scripts/` | reconcile | active worktree may add launcher scripts | current checkout contains only config JSON |
| `dev-observatory/switchboard_panel.py` | external consumer | caller/pin proof renderer | modified only by the dev-observatory plan |

- `python -m switchboard inspect --json`: config source, active state, endpoint reachability,
  configured/default/effective model per site, effort hints, and explicit limitations.
- `switchboard/observatory-contract.json`: versioned fixture carrying config fields/defaults and
  inspect output. dev-observatory joins it with mechanically found skill call sites and current
  source locators. Switchboard owns config truth; observatory owns workspace wiring proof.

`run-bakeoff` is a main function because it demonstrates the safety threshold deterministically.
`config` remains useful but moves to all verbs; `inspect` is the readable main surface. `start` is
hidden if it is only a classifier artifact. The desktop-icon installer is one-time setup and is
never a dashboard button. `start-offload` survives only if the active launcher worktree lands and
doctor plus a real endpoint smoke prove it.

### Step O70: Reconcile the endpoint-launcher worktree
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

### Step O71: Add inspect JSON
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

### Step O72: Publish the complete observatory contract
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

### Step O73: Curate operator documentation and bakeoff output
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

### Step O74: Real routing UAT
- **Problem:** Inspect inert and enabled configs, check endpoint-down/up states, run the frozen
  bakeoff, and if retained, start/stop offload through the launcher.
- **Type:** operator
- **Issue:** #
- **Produces:** operator evidence only
- **Done when:** inspect distinguishes config, endpoint, and certification state; bakeoff runs; any
  retained launcher starts and tears down cleanly without claiming the local model owns a gate
- **Depends on:** 73

### External <friend-project> contribution (held separate ownership)

Two contributions to <friend-project> that complete the Switchboard vision (Phase 1 shipped the offload core
in `coding-root`):

- **(A) A model-attribution VIEWER** — a bundled <friend-project> plugin that answers *"what model is each
  session / sub-agent using, and what's it costing?"* across the canvas. Reuses <friend-project>'s existing
  `cc-quota` (rate limits + context window) and `telemetry:hud` (cost-by-model) and adds the missing
  piece: **per-session model attribution**. Read-only, additive, degrades gracefully where there's
  no local model / no `nvidia-smi`. Ships independently of (B).
- **(B) A per-session model/token OVERRIDE** — a <friend-project> *core* extension letting a session (or a
  spawned "hand") declare its own model and/or auth token instead of inheriting the global CLI
  template + global secrets. This is the convergence point: it unlocks both per-hand local-model
  routing AND the parked multi-token quota-spreading idea. Higher risk (touches session launch) —
  paired with a startup validation guard.

Triggering context: Phase 1's offload is invisible without the viewer ("I don't know what's firing
under the hood"), and per-hand routing needs the override. Both were specced as prose in
`docs/switchboard-plan.md` § Phase 2; this promotes them to a buildable plan grounded in <friend-project>'s
actual code.

**In:**
- (A) `src/plugins/model-attribution/` bundled plugin + its two registrations; a small server-side
  addition to **expose per-session model** (surface what `context-usage` already extracts); the
  viewer reads sessions + per-session model + cc-quota + `telemetry:hud`; optional GPU/loaded-model
  panel (degrades on no-`nvidia-smi`).
- (B) per-session `model` + `token` override on the create + spawn endpoints → `Session` type →
  `buildAgentCommand` (`--model` override) + per-session secret injection; a **startup validation
  guard** (allowed-model list / token validation at launch).
- A spike step (1) to settle Tier-A vs Tier-B attribution before building the viewer.

**Out:**
- Any push/merge to <friend-project> `main` (PR only). Forking (we branch directly, per access).
- The offload core itself (Phase 1, shipped in coding-root — the viewer only *observes*; it does not
  route).
- Multi-token quota-spreading *mechanics* (the override *enables* it; actually wiring/validating
  multi-account spreading + its ToS check stays parked, per `docs/switchboard-plan.md`).
- New wiki pages / broad <friend-project> refactors.

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `src/plugins/model-attribution/` | create | the viewer bundled plugin (package.json + src/index.tsx + widget) | pattern confirmed: `src/plugins/nats-traffic/`, `src/plugins/browser/` |
| `src/core/pluginHost/bundled.ts` | modify | register the plugin in `BUNDLED_PLUGINS` | `bundled-howto.md:96-108`; file read |
| `src/server/api/builtinPluginManifests.ts` | modify | register in `BUILTIN_PLUGIN_PKGS` | `bundled-howto.md:120-125` |
| `src/server/sessions/context-usage.ts` | extend | already extracts `ContextData.model` (l.19/139) — expose it per-session | read: model extracted, not surfaced |
| `src/server/api/routes.ts` | extend | (A) add a per-session-model read path; (B) add `model`/`token` to spawn body (l.3149) + `CreateSessionParams` (l.368) | grep'd: spawn body + create params enumerated, neither has model/token |
| `src/server/sessions/session.ts` | modify | (B) add optional `model`/`token` to `Session` + `CreateSessionOpts` | spawn/create resolve the Session here |
| `src/server/sessions/backends/tmux.ts` | modify | (B) `buildAgentCommand` accept a runtime `--model` override; per-session secret in the `set-environment` loop (l.377-383) | read: model baked in template, secrets-loop global |
| `src/server/sessions/config.ts` | modify | (B) `loadSecrets` optional per-session overlay + the validation guard home | read: `loadSecrets` global (l.279-295) |

- **`src/plugins/model-attribution/`** — `package.json` (`<friend-project>` manifest, `apiVersion: "5"`,
  one widget `model-attribution`), `src/index.tsx` (`activate(api)` → `api.widgets.register`), and a
  `ModelAttributionWidget.tsx` that subscribes to `telemetry:hud` + polls `/api/state` +
  per-session model + cc-quota and renders the attribution view. Degrades: no GPU panel when
  `nvidia-smi` is absent.
- **Per-session-model server surface** — the minimal addition that exposes the model
  `context-usage` already extracts (an endpoint and/or a field in the session snapshot the plugin reads).
- **Per-session override** — optional `model`/`token` on create+spawn, threaded to
  `buildAgentCommand` + per-session secret, gated by a launch validator.

1. **Bundled plugin, not external.** It's a first-party contribution that ships in the <friend-project> repo
   (reviewable, no separate distribution), matching the existing bundled widgets. (Alternative:
   external plugin in `coding-root` — rejected; the goal is an upstream contribution.)
2. **Per-session model = expose, not re-derive.** `context-usage.ts` already has the model; the
   viewer's Tier-A attribution is a thin server surface over that, not new transcript parsing. Tier-B
   (per-sub-agent) is the spike's call (Step 1) — likely transcript-parse, possibly deferred.
3. **Viewer ships before the override.** (A) is additive + low-risk (read-only plugin); (B) touches
   session launch. Structure as two PRs so the friend can accept the viewer without the riskier core
   change. (A) = Steps 1–4; (B) = Steps 5–6.
4. **Pair the override with a startup guard (security rule).** A per-session *token* is unsafe config;
   it must be validated at launch (allowed-model list, token shape/he-presence), not just documented —
   a startup invariant with a stable error, per `.claude/rules/security.md`.
5. **Degrade, don't assume the operator's box.** No `nvidia-smi` (Mac) → no GPU panel; no local model
   → the viewer still shows Claude models + quota. The override is inert unless a session sets it.
6. **Autonomous-behavior trigger does NOT fire.** The viewer is an operator-invoked UI widget that
   reads/subscribes (no background daemon accumulating state); the override is launch-time config. So
   no soak phase — a UI smoke (Step 4) + the operator UAT (Step 7) are the right gates.

> Track A (viewer) = Steps 1–4, a standalone PR. Track B (override) = Steps 5–6, a second PR. Step 7
> is the operator UAT + PR open. All steps run in a **<friend-project> feature branch**; gates are <friend-project>'s
> TS toolchain (`tsc -p tsconfig.app.json`, vitest `--exclude='e2e/**'`, eslint).

### Step P1: Spike — per-session + sub-agent model attribution feasibility (D6 Tier A/B)
- **Problem:** Confirm the cheapest correct source for the viewer's model data. (a) Verify
  `context-usage.ts` `ContextData.model` gives the live per-session model and decide how to surface it
  (endpoint vs session-snapshot field) — **Tier A**. (b) Determine whether sub-agent transcripts
  (`agent-*.jsonl`, or the main `<conversationId>.jsonl` assistant turns) record model per-turn so a
  plugin/server can attribute **per-sub-agent** model — **Tier B** — or whether that's deferred.
  Capture real transcript shapes (substrate-test discipline). Output: a findings doc pinning what the
  viewer surfaces in Phase 2 vs later.
- **Type:** code
- **Issue:** #209
- **Flags:** --reviewers code
- **Produces:** `docs/investigations/switchboard-<friend-project>-attribution.md` (in coding-root) + any throwaway probe
- **Done when:** Tier A's surface is decided with evidence (model is/ isn't reliably in context-usage);
  Tier B is decided (transcript model-per-turn confirmed → in scope, or deferred with the reason)
- **Depends on:** none
- **Status:** DONE (2026-06-19) — Tier A IN SCOPE (use transcript `message.model`, cheaper than the context-usage sidecar); Tier B DEFERRED (no `agent-*.jsonl`, no `isSidechain` records — per-sub-agent model not recoverable). See `docs/investigations/switchboard-<friend-project>-attribution.md`.

### Step P2: Server — expose per-session model (Tier A)
- **Problem:** Surface the model `context-usage` already extracts so a plugin can read per-session
  model. Per Step 1's decision: add it to the session snapshot the plugin reads and/or a
  `GET /api/sessions/:name/model` (reuse existing context-usage plumbing; don't re-parse). Keep it
  read-only and cheap.
- **Type:** code
- **Issue:** #210
- **Flags:** --reviewers code
- **Produces:** the server surface + a vitest unit test (mock the context-usage source)
- **Done when:** a plugin-reachable read returns the current per-session model; `tsc` + vitest green
- **Depends on:** 1
- **Status:** DONE (2026-06-19) — <friend-project> `switchboard-viewer` @ 72720cf4. Sourced from transcript `message.model` (per Step 1, cheaper than context-usage): `readLatestModel` in transcript-parser.ts + `model` on `/api/state` + `GET /api/sessions/:name/model`. tsc app clean, 23 new/related vitest pass (22 full-suite fails are pre-existing Windows-env, verified by baseline stash).

### Step P3: Viewer bundled plugin — the model-attribution widget
- **Problem:** Build `src/plugins/model-attribution/` (manifest + `activate` + widget). The widget
  reads `/api/state` (sessions + conversation ids), the Step-2 per-session model, `/api/cc-quota`
  (rate limits), and subscribes to `telemetry:hud` (`cost.byModel`), rendering a per-session
  model/cost/quota view. Optional GPU/loaded-model panel that **degrades** when `nvidia-smi`/ollama
  are absent. Follow <friend-project> conventions (`apiFetch`/`api.http`, no bare `fetch`).
- **Type:** code
- **Issue:** #211
- **Flags:** --reviewers code
- **Produces:** the plugin package (package.json + index.tsx + widget component) + a vitest component test
- **Done when:** the widget renders sessions with their model + quota from real API shapes (test with
  stubbed responses); `tsc` + eslint + vitest green
- **Depends on:** 2
- **Status:** DONE (2026-06-19) — <friend-project> `switchboard-viewer` @ c571c4af. `src/plugins/model-attribution/` bundled plugin (manifest + activate + ModelAttributionWidget): per-session model list (null→"—"), cc-quota 5h/7d headroom, fleet `byModel` chips, GPU-degraded placeholder. tsc clean, eslint 0/0 (in-scope), 2 component tests pass. Not yet registered (Step 4).

### Step P4: Register + UI smoke gate
- **Problem:** Register the plugin in `src/core/pluginHost/bundled.ts` (`BUNDLED_PLUGINS`) +
  `src/server/api/builtinPluginManifests.ts` (`BUILTIN_PLUGIN_PKGS`). Then a **smoke gate**: start
  <friend-project> with `<friend-project>_FAST_SIM=1` (mock data), drop the widget on the canvas, and confirm it
  renders the mocked sessions/models without error (Playwright screenshot or a manual check). This is
  the producer→consumer gate (server data → plugin render) that unit tests can't see.
- **Type:** code
- **Issue:** #212
- **Flags:** --reviewers code
- **Produces:** the two registrations + a Playwright/e2e smoke (or a documented manual smoke) under <friend-project>'s `e2e/`
- **Done when:** with `<friend-project>_FAST_SIM=1` the widget appears in the palette, drops on canvas, and
  renders mock sessions+models with no console error; <friend-project>'s full typecheck/lint/test green.
  **(End of Track A — this is a shippable PR.)**
- **Depends on:** 3
- **Status:** DONE (2026-06-19) — <friend-project> `switchboard-viewer` @ 9315c3bc. Registered in `bundled.ts` + `builtinPluginManifests.ts`; no-browser integrity test + the pre-existing `integration.test.ts` (full plugin pipeline) both pass with the new entry → it loads. Playwright e2e spec written for CI/operator; **visual render smoke deferred to Step 7** (<friend-project> e2e `spawn npx ENOENT` on this Windows box — env, not code). tsc clean, pluginHost vitest 52/52. **Track A done → PR 1 ready (opened in Step 7).**

### Step P5: Server — per-session model/token override (core change)
- **Problem:** Add optional `model` and `token` to the create endpoint (`CreateSessionParams`,
  `routes.ts:368`) and the spawn body (`routes.ts:3149`); thread them onto the `Session` type
  (`session.ts`); make `buildAgentCommand` accept a runtime `--model` override (replacing/augmenting
  the template's baked `--model`); and overlay a per-session secret (e.g. a session-scoped
  `CLAUDE_CODE_OAUTH_TOKEN`) on top of the global `loadSecrets` map in the `set-environment` loop
  (`tmux.ts:377`). Inert when unset (behaves exactly as today).
- **Type:** code
- **Issue:** #213
- **Flags:** --reviewers code
- **Produces:** the threaded override + vitest tests (override applied when set; identical to current when unset)
- **Done when:** a session created/spawned with `model`/`token` launches with that model + that token
  in its env; unset = byte-identical to current behavior; `tsc` + vitest green
- **Depends on:** none (independent of Track A; can run parallel to 1–4)
- **Status:** DONE (2026-06-19) — <friend-project> `switchboard-override` @ 10a92a47 (branched off main, independent of Track A). `model` → persisted `Session.modelOverride`, appended as `--model` in `buildAgentCommand` (last-wins, re-applied on restart). `token` → `applyTokenOverride()` overlays `CLAUDE_CODE_OAUTH_TOKEN` at spawn time only — never persisted/returned/logged (the quota-isolation case). Wired into BOTH `POST /api/sessions` and `POST /api/sessions/:name/spawn`. **Keystone "inert when unset" proven:** `buildAgentCommand` byte-identical when null; `applyTokenOverride` returns the SAME secrets ref when unset. 9 new vitest tests; full `typecheck` (app+e2e+test) clean; sessions/api/observability 98/98.

### Step P6: Startup validation guard for the override (security invariant)
- **Problem:** Pair the unsafe per-session-token/model config with a launch-time invariant: validate
  the override before `createTmuxSession` sends the command — an allowed-model list and a token
  shape/presence check, failing closed with a stable error code (not a silent fallback). Per
  `.claude/rules/security.md` "pair unsafe configs with startup safety checks". Never log token bytes.
- **Type:** code
- **Issue:** #214
- **Flags:** --reviewers code
- **Produces:** the validator + tests (rejects a disallowed model / malformed token; no token bytes logged)
- **Done when:** a bad override is rejected at launch with a stable error; a valid one passes; no token
  bytes appear in logs; gates green. **(End of Track B — second PR.)**
- **Depends on:** 5
- **Status:** DONE (2026-06-19) — <friend-project> `switchboard-override` @ 74be2a7c. `validateSessionOverride()` runs in BOTH create + spawn paths BEFORE session-dir creation / tmux send. Fail-closed with 4 stable, typed `ErrorCode`s (`OVERRIDE_MODEL_NOT_CONFIGURED|MODEL_NOT_ALLOWED|TOKEN_DISABLED|TOKEN_MALFORMED`; added to the union + HTTP_STATUS, 403/400). New `switchboard.{allowedModels[],allowTokenOverride}` config block defaults empty/false → override rejected unless explicitly enabled; no-override launches pass immediately (inert). Token shape check is **value-free** — never inspects/returns/logs the bytes; no log statement touches the token. Full `typecheck` clean; vitest sessions **106/106** (8 new guard tests incl. "rejection message never contains the token"). **Track B complete → PR 2 ready (opened in Step 7).**

### Step P7: Operator UAT + open the PR(s)
- **Problem:** Run <friend-project> locally (`npm run dev`, and `<friend-project>_FAST_SIM=1` for the viewer), confirm:
  the viewer shows real per-session models + quota and degrades cleanly with no local model; a session
  with a per-session `model`/`token` override launches correctly and an invalid one is rejected. Then
  open the PR(s) on the <friend-project> feature branch for `<friend-owner>` to review — **viewer PR first**, then
  the override PR. Confirm no push to `main`.
- **Type:** operator
- **Issue:** #215
- **Produces:** a UAT note (what was observed) + the opened PR link(s)
- **Done when:** operator confirms viewer + override behave on a real <friend-project> run, and the PR(s) are
  open for the owner's review (nothing merged)
- **Depends on:** 4, 6

- **Step 1 spike** pins the data source with real transcript/context-usage shapes (substrate-test).
- **Steps 2/5/6** are unit-tested (vitest) at the server boundary with stubbed Claude-Code sources;
  the override's "byte-identical when unset" test is the keystone (the core-change safety net).
- **Step 3** tests the widget against stubbed API shapes (no live <friend-project>).
- **Step 4 smoke gate** is the producer→consumer check the unit tests can't see — real plugin host +
  `<friend-project>_FAST_SIM` mock data → widget renders. Run under <friend-project>'s `e2e/` (Playwright).
- **Step 7 operator UAT** is the only thing that proves it on a real <friend-project> + real Claude Code
  sessions (viewer shows real models; override launches a real session correctly) before the PR.
- The autonomous-behavior trigger does NOT fire (operator-invoked UI + launch-time config, no
  background daemon) — so no soak phase; the UI smoke + operator UAT are the right end-to-end gates.

### Proposed switchboard-tune sibling (not an active local queue)

**Proposal:** https://claude.ai/code/artifact/b9d47fc6-e134-4854-9b38-de2d205506c7 (operator-facing view of this plan; see the Decision Inventory appendix for the P/D handles it exposes)

Fine-tunes a small open-weight model (QLoRA on Qwen2.5-1.5B-Instruct) to serve as the local judge that
switchboard already routes `review-deep-style` calls to, distilled from Claude verdicts, and measures
honestly whether fine-tuning beat prompting at that scale.

It is being built to close a specific, named gap — "have integrated and fine-tuned LLMs" appears in two
target job descriptions — with a small, verifiable artifact rather than a tutorial. The shape matters:
switchboard is a real system that already routes judge calls to a local model and already has a
kill-switch that disables a slice when it disagrees with the reference too often. Making the local judge
*better* is that system's natural next phase, so every number this project produces (dataset size,
golden-set size, before/after agreement rates) is grounded in a deployed pipeline rather than a notebook.

**The deliverable is an honest eval delta, not a win.** "Prompting beat fine-tuning at this scale, and
here is the eval that shows it" is an accepted, publishable outcome of this plan. No step is allowed to
be written or reworked in order to produce a positive number.

---

### In scope

- A new sibling project `switchboard-tune/` with its own `pyproject.toml` carrying the training stack.
- Mining realistic judge inputs from real workspace git history.
- Minting teacher labels with Claude via the `claude -p` subprocess seam.
- Freezing a hash-pinned golden set **before** any training run.
- An eval harness that imports switchboard's production prompt and parser, with calibration anchors.
- A prompted baseline measurement of the untuned student.
- A QLoRA SFT run with prompt-loss masking and dev-split checkpoint selection.
- A post-training eval and a written comparison, including the negative-result path.
- Merge → GGUF → llama-swap → certify through `python -m switchboard bakeoff` against the real endpoint.
- An optional DPO stretch, gated on whether usable preference pairs actually materialize.

### Explicitly out of scope

- **Any change to switchboard's runtime dependencies.** `dependencies = []` in
  `switchboard/pyproject.toml` is invariant. Phase B states it as: "switchboard is zero-dependency by
  design... Any new code in switchboard must preserve this." torch, transformers, peft, trl, and datasets
  never enter that file, in any extra.
- **Relaxing Decision 3.** The master plan states "The local model is NEVER on the correctness gate...
  Local = advisory pre-filter only; Claude makes every gate/merge decision." A better-tuned judge does not
  change this. `build-step-style` stays `false`.
- **Enabling any slice by default.** No-config remains inert.
- Frontier scale, RLHF, multi-GPU, training from scratch, vLLM serving, quantization research.
- Closing issue #237. This plan *feeds* it — Step 2 produces the labeled corpus a live-capture suite can
  draw from — but #237 needs a live `coder-30b` capture run, which is its own operator step. Reference, do
  not duplicate.
- Wiring `monitor.py` into a daemon. It stays unwired here.
- Replacing `coder-30b` as the deployed judge. The tuned 1.5B is evaluated as a *candidate*; it ships only
  if it clears the existing kill rule, and even then only for `review-deep-style`.

---

The headline: **this feature adds zero lines to the `switchboard/` package.** switchboard is imported and
read; it is not modified. That is what protects the zero-dependency invariant.

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `switchboard/switchboard/client.py` | **read-only import** | `switchboard-tune` imports `SYSTEM_PROMPT` and the verdict parser so the dataset and eval use the production prompt verbatim | grep `SYSTEM_PROMPT` across `switchboard/` → exactly 2 sites, both in `client.py` (def line 28, use line 202). No other consumer exists; this project becomes the first external one. |
| `switchboard/switchboard/harness.py` | **read-only import** | reuse `ShadowCase` + `aggregate_agreement` rather than re-deriving the "defers excluded from denominator, strict `>` kill" rule | read: `run_shadow` + `aggregate_agreement` signatures confirmed; `_verdict_of` is the defer-discrimination idiom to copy |
| `switchboard/switchboard/config.py` | **read-only import** | eval harness loads real config via `load_config()` rather than hand-building a base_url | read: field list + `load_config` resolution order confirmed (arg → env → home → defaults) |
| `switchboard/pyproject.toml` | **unchanged (asserted)** | `dependencies = []` must stay empty; Step 3 adds a test that fails if it ever isn't | read line 7: `dependencies = []`; optional-deps currently only `dev = [pytest, ruff, mypy]` |
| `switchboard/suites/review-deep-style.json` | **modify (Step 8 only)** | its `recorded` block is a hand-authored fixture; a live capture may add a `student-tuned` runner column | read: top-level keys `note`/`slice`/`reference_runner`/`kill_threshold`/`cases`/`recorded`; runners currently `opus`/`local`/`weak`; loader requires runner labels to cover case labels exactly |
| `switchboard/tests/*` | **unchanged (regression guard)** | all 183 tests must still pass untouched; a diff here is a smell | counted: 11 test files + conftest, 183 collected |
| `~/.switchboard/config.json` | **deployment artifact, Step 8** | slice enablement is a deployed-config edit, not a repo edit | verified on disk: exists, 179 bytes, config-only, no metrics/log dir |
| `dev/.claude/observatory/registry.toml` | **extend** | register `switchboard-tune` as an owned project so observatory can see it | read: `switchboard` present with `slug`/`path`/`owned=true`; unregistered projects default to `owned=false` and are write-blocked |
| `docs/switchboard-offload-phase-b-plan.md` | **annotate** | its Step 3 says `general-35b`; add a one-line correction pointing here | recon-confirmed drift vs README/CLAUDE.md `coder-30b` |
| `docs/switchboard-config-loader-plan.md` | **annotate** | same `general-35b` drift at its Step 5 | recon-confirmed |

**Shared-constant call-site audit** (per the grep-all-downstream rule). Two shared values cross a producer/
consumer boundary in this work:

1. `SYSTEM_PROMPT` — 2 sites, both in `client.py`. `switchboard-tune` must `from switchboard.client import
   SYSTEM_PROMPT`. Step 3 adds a test asserting **identity** (`is`), not equality, so a future copy-paste
   duplication fails CI.
2. The slice name `"review-deep-style"` — appears in `switchboard/bakeoff.py`, `cli.py`, `harness.py`,
   `monitor.py`, `suites/review-deep-style.json`, `README.md`, six test files, plus
   `.claude/observatory/registry.toml`, three skill cores, and `offload-scan-out/offload-config.json`. This
   plan **reads** that string and never redefines it; the suite file remains its on-disk anchor.

---

All new code lives in a **new sibling project**, `<coding-root>\switchboard-tune\`.

| Path | What it is |
|---|---|
| `switchboard-tune/pyproject.toml` | uv project, `requires-python = ">=3.12"`, deps: torch (CUDA), transformers, peft, trl, datasets, accelerate, bitsandbytes. Installs `switchboard` as an editable path dep for prompt/parser reuse. |
| `switchboard-tune/tune/mine_inputs.py` | Walks real git history across `dev/` repos, extracts small diff hunks, renders each through the production prompt shape, dedups, writes `data/inputs.jsonl` with source repo + sha provenance. |
| `switchboard-tune/tune/label.py` | Batch teacher-labeling via the `claude -p` subprocess seam. Writes `data/labeled.jsonl`. Resumable, idempotent, one row per input. |
| `switchboard-tune/tune/freeze.py` | Deterministic 80/10/10 split + SHA256 manifest. Writes `data/golden/{train,dev,test}.jsonl` + `data/golden/MANIFEST.sha256`. Refuses to overwrite an existing frozen manifest. |
| `switchboard-tune/tune/evalharness.py` | Scores any runner against the frozen test split. Imports `SYSTEM_PROMPT` and the verdict parser from switchboard. Runners: `claude`, `always-pass`, `student-prompted`, `student-tuned`, `coder-30b`. |
| `switchboard-tune/tune/train_sft.py` | QLoRA SFT via `trl.SFTTrainer` with prompt-loss masking, dev-split checkpoint selection, bounded `max_steps`. |
| `switchboard-tune/tune/export.py` | Merge adapter into base, convert to GGUF via llama.cpp's `convert_hf_to_gguf.py`, quantize. |
| `switchboard-tune/tune/ship.py` | Place the GGUF into llama-swap's model dir + config, then invoke `python -m switchboard bakeoff` and surface the certify verdict. |
| `switchboard-tune/tune/dpo.py` | Optional. Builds preference pairs from student-wrong cases and runs a DPO pass. |
| `switchboard-tune/results/` | `baseline.json`, `tuned.json`, `comparison.md` — the honest write-up. |
| `switchboard-tune/README.md` | Reproduction instructions, including that this runs in WSL2 and why. |

### Toolchain and first-run

`switchboard-tune` runs **inside WSL2 Ubuntu**, not on Windows, because training needs CUDA. All commands
below are given in the PowerShell-runnable `wsl -- bash -lc` form, since the operator is always at a
PowerShell prompt. Step 1 must establish every one of these and record them in the project's `CLAUDE.md`
under a scrapable `## Commands` block, so dev-observatory derives launch verbs rather than needing them
hand-curated.

| Verb | Command |
|---|---|
| install | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv sync --extra cuda"` |
| test | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run pytest -q"` |
| lint | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run ruff check ."` |
| typecheck | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run mypy tune"` |
| smoke | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run python -m tune.smoke"` |

**System prerequisites**, all verified present on this machine except where noted:

- WSL2 Ubuntu with CUDA passthrough — verified (`nvidia-smi` resolves inside WSL and reports the 4070).
- Python 3.12.3 and `uv` at `~/.local/bin/uv` inside WSL — verified.
- `llama-swap.service` active — verified.
- **llama.cpp checkout with `convert_hf_to_gguf.py` — NOT yet verified.** Step 4's smoke gate must locate
  it and record the path and revision in the README, or clone and pin one. This is the most likely
  first-run blocker.
- Claude CLI authenticated for the `claude -p` seam. Prefer `CLAUDE_CODE_OAUTH_TOKEN` (subscription OAuth)
  over an API key. Step 2 must fail loudly with a clear message if the seam is unauthenticated rather than
  silently producing zero labels — an empty label batch that exits 0 would poison every downstream step.
- No secret is read, written, or logged by any step in this plan. The teacher seam authenticates from the
  operator's existing environment; no key material enters the repo or the dataset.

---

**D1 — Student is `Qwen/Qwen2.5-1.5B-Instruct` (exact Hugging Face repo id, ungated — no HF token
required), trained with QLoRA (4-bit), not LoRA.** 8188 MiB of VRAM is the
binding constraint. A 4-bit 1.5B base leaves comfortable headroom for optimizer state, activations, and a
1024-token sequence length on a laptop GPU that is also driving a display. A 3B would fit but leave no room
for the eval loop to run alongside; a 7B risks OOM given only 15.5 GB of system RAM to spill into.
*Alternative considered:* full LoRA in fp16 on a 1.5B — fits, but QLoRA is the technique worth being able
to speak to, and the memory headroom buys a larger effective batch via gradient accumulation.

**D2 — The comparison is student-versus-itself, and this is the honesty anchor.** Baseline is
Qwen2.5-1.5B-Instruct *prompted* with the production `SYSTEM_PROMPT`. Treatment is the same model after
QLoRA SFT. Both are scored on the identical frozen test split. The deployed `coder-30b` is reported as a
**reference column only** — a 1.5B beating a 30B MoE would be a surprising result, and beating it is
explicitly not the claim. Conflating "tuned 1.5B vs 30B" with "tuning helped" is the exact measurement
error this decision exists to prevent.

**Pre-registered claim, fixed before any number is produced:** *On a frozen golden set of
`review-deep-style` judgments labeled by Claude, does QLoRA SFT raise Qwen2.5-1.5B-Instruct's **strict**
agreement-with-Claude (per D10 — agreements over all cases, a defer counting as a miss) above its own
prompted baseline measured on the same runtime and quantization, and by how many percentage points?* Scope
of the claim is exactly that slice, that model, that golden set — it is not a claim about fine-tuning in
general.

**D3 — Teacher labels come from Claude via the `claude -p` subprocess seam.** That is the established
workspace pattern and needs no API key (a consumer subscription is not API access). The seam is hardened
per known workspace failure modes: pass `--model` explicitly so the subprocess does not inherit a
power-user global config; disable tools; parse tolerantly; pass long prompts via **stdin** rather than argv
(argv over 32K raises WinError 206 on Windows); and decode with `encoding="utf-8", errors="replace"` (a
non-cp1252 byte otherwise raises inside the reader thread, silently yielding `stdout=None`).
*Alternative considered:* the Anthropic API — cleaner batching, but requires a key this machine has not
been verified to hold.

**D4 — Inputs are mined from real workspace git history, not synthesized.** The judge's real input
distribution is small code-style diff hunks, and `dev/` contains years of them across many repos. Mining
gives 1,000+ realistic inputs cheaply and grounds the eval in the distribution the deployed judge actually
sees. *Alternative considered and rejected:* having Claude synthesize the inputs as well as the labels.
That collapses the distribution toward what the teacher finds easy to imagine and inflates measured
agreement — the student would be scored on the teacher's own imagination rather than on real diffs.

**D5 — Training code lives in a new sibling project, never inside `switchboard/`.** Two independent reasons,
either of which is sufficient. First, the zero-dependency invariant: torch and friends can never appear in
`switchboard/pyproject.toml`, and putting them behind an optional extra still invites an accidental import
into the shipped package. Second, the environments genuinely differ — training needs CUDA and therefore
runs in WSL2, while switchboard is developed and tested on Windows. `switchboard-tune` installs switchboard
as an editable path dependency so it reuses the production prompt and parser rather than re-implementing
them.

**D6 — The golden set is frozen before any training, with calibration anchors.** `freeze.py` writes a
SHA256 manifest and refuses to overwrite it; the eval harness verifies the manifest on every run and
**aborts** on mismatch rather than warning. Before any student number is trusted, the harness must clear a
calibration gate: a known-good runner (Claude re-scoring the test set) and a known-garbage runner (a
constant `always-pass`) must bracket the metric by a wide margin. A metric that cannot separate those two
is not measuring what it claims. The harness also aborts — never silently falls back — if the production
prompt or config cannot be loaded.

**D7 — Shipping is certification, not assertion.** A tuned model reaches the router only by clearing
`python -m switchboard bakeoff` against the real endpoint under the existing 0.20 strict-greater-than
disagreement kill rule, with defers excluded from the denominator. If it does not clear, it does not ship,
and the write-up says so. The slice stays `review-deep-style` only.

**D8 — DPO is genuinely optional and predicate-gated.** It runs only if SFT leaves enough
student-wrong-versus-Claude-right cases to build meaningful preference pairs. A `Type: conditional` step
with a real shell predicate keeps `/build-phase` from running a training pass over an empty pair set.

**D9 — Negative results ship.** If the tuned model loses to the prompted baseline, Step 7 still produces
`comparison.md` with the real numbers and the interpretation. No step may be rerun with different settings
in order to find a better number; if settings change, that is a new run recorded alongside the first, not a
replacement for it.

**D10 — Every score is three numbers, never one.** This is the correction that keeps D2 honest, and it
exists because switchboard's native metric has a denominator that moves. `run_shadow` excludes defers from
the denominator — correct for its purpose (a defer costs quota, not correctness), but actively misleading
here. A 1.5B model prompted with a system prompt written for a 30B model will often fail to emit parseable
JSON at all, so the *baseline* would be scored over a small, self-selected subsample of cases it happened
to answer, while the *tuned* model — which learns the output format almost immediately — is scored over
nearly all of them. Comparing those two agreement percentages compares two different test sets and can
manufacture either a fake win or a fake loss.

Every runner therefore reports the following, where **total** = the number of rows in the frozen test
split, **verdicted** = rows where `local_judge` returned a `Verdict` (i.e. `result.get("defer") is not
True`), and **agreements** = verdicted rows whose `verdict` field equals the frozen Claude label:

- **agreement** = agreements / verdicted — switchboard's native rule, kept for continuity with the kill
  threshold and the bake-off. Undefined when `verdicted == 0`; report `null`, never 0.0.
- **coverage** = verdicted / total — the share of cases the model answered at all. This is where format
  compliance shows up.
- **strict** = agreements / total — a defer counts as a miss. This is the number the headline claim uses,
  because it is the only one whose denominator is fixed by the frozen golden set.

All three are reported as floats in `[0, 1]` alongside their raw integer counts, so any of them can be
recomputed from the JSON without trusting the arithmetic.

The headline delta in `comparison.md` is the **strict** delta. Agreement and coverage are reported
alongside so the write-up can separate "the fine-tune taught the model to emit JSON" from "the fine-tune
taught the model to judge code" — at 1.5B, the former is the likelier effect, and calling it the latter
would be the exact dishonesty this project exists to avoid.

---

**Sequencing clarification:** T1 creates the shared `SYSTEM_PROMPT` and `build_messages` helper before T2 imports it; T3 validates the single helper identity and scorer, not a second prompt implementation. The Step 8 evaluation-suite addition is the only named exception to the source statement that the sibling adds zero Switchboard lines.

### Step T1: Scaffold `switchboard-tune` and mine real judge inputs
- **Problem:** Create the sibling uv project (WSL2/CUDA-targeted, switchboard as an editable path dep, registered in the observatory registry as owned) and implement `tune/mine_inputs.py`, which walks git history across `dev/` repos, extracts small code-style diff hunks, renders each through the **mined-case prompt shape defined in Appendix A.2** (diff plus the JSON instruction, and deliberately **no editorial summary sentence** — see the label-leak note there, which is load-bearing), dedups near-identical hunks, and writes `data/inputs.jsonl` per the Appendix A.1 schema. Mining bounds: hunks of 2-30 changed lines from `.py`/`.ts`/`.tsx`/`.js`/`.ps1` files, at most 40 hunks per source repo so no single repo dominates, skipping vendored, generated, and lockfile paths.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `switchboard-tune/pyproject.toml`, `tune/mine_inputs.py`, `data/inputs.jsonl`, `README.md`, `CLAUDE.md` (with scrapable `## Stack` + `## Commands` blocks per the descriptor contract), and a `[[project]]` entry in `dev/.claude/observatory/registry.toml` with `slug = "switchboard-tune"`, `path = "switchboard-tune"`, `owned = true`
- **Done when:** `uv run python -m tune.mine_inputs --limit 1200` writes at least 1,000 deduped rows; every row carries provenance; re-running is deterministic given the same repo state; the mined prompt text is built from `switchboard.client.SYSTEM_PROMPT`, not a local string
- **Depends on:** none

<!-- autofix-applied: 2026-07-28 -->
### Step T2: Mint teacher labels with Claude and freeze the golden set
- **Problem:** Implement `tune/label.py` (batch `claude -p` labeling, hardened per D3: explicit `--model`, no tools, stdin for the prompt, `encoding="utf-8", errors="replace"`, resumable so a crash mid-batch does not restart from zero) and `tune/freeze.py` (deterministic 80/10/10 split, SHA256 manifest, refuses to overwrite an existing manifest). Label 500-2,000 mined inputs. **Near-duplicate leakage across splits is the failure mode to design against** — exact-match dedup in Step 1 does not catch a hunk that differs by a variable name, and a near-dupe spanning train and test silently inflates the tuned score.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** `tune/label.py`, `tune/freeze.py`, `data/labeled.jsonl`, `data/golden/{train,dev,test}.jsonl`, `data/golden/MANIFEST.sha256`, `data/golden/leakage-report.json`
- **Done when:** at least 500 labeled rows exist with the `pass`/`flag` distribution reported in the run log; the frozen splits are written; `freeze.py` exits non-zero when asked to overwrite an existing manifest; a deliberate one-byte edit to `test.jsonl` makes manifest verification fail; **and `leakage-report.json` shows zero test-split rows whose normalized-token Jaccard similarity against any train-split row exceeds 0.9** (the check runs inside `freeze.py`, before the manifest is written, and a violation is a hard non-zero exit rather than a warning)
- **Depends on:** 1

<!-- autofix-applied: 2026-07-28 -->
### Step T3: Eval harness with calibration anchors and the zero-dep guard
- **Problem:** Implement `tune/evalharness.py`, scoring any named runner against the frozen test split. It must import `SYSTEM_PROMPT` and the verdict-parsing path from `switchboard.client` (never re-implement them), expose **one** `build_messages(case) -> list[dict]` helper that every consumer (miner, labeler, trainer, evaluator) calls so the message assembly has a single source of truth, reuse `harness.aggregate_agreement`'s rule that defers are excluded from the denominator, verify the golden manifest on every run, and **abort** rather than warn on manifest mismatch or on any fallback prompt/config path. Report the **three-number metric block** defined in D10 (agreement, coverage, strict) rather than a single agreement figure. Add the calibration anchors (`claude`, `always-pass`) and a regression test asserting `evalharness` uses switchboard's `SYSTEM_PROMPT` object **identity** (`is`), plus a test asserting `switchboard/pyproject.toml` still declares `dependencies = []`.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** `tune/evalharness.py`, `tune/messages.py`, `tests/test_evalharness.py`, `tests/test_switchboard_invariants.py`
- **Done when:** the calibration gate passes — `score(claude) > score(always-pass)` by a wide, recorded margin on the frozen test set; **Claude's self-agreement against its own frozen labels is recorded as the practical ceiling** (the student is not expected to exceed it, and a ceiling far below 1.0 means the task itself is ambiguous and the write-up must say so); every runner report carries all three of agreement / coverage / strict; the `is`-identity test fails if `SYSTEM_PROMPT` is copied instead of imported; the zero-dep test fails if any dependency is added to `switchboard/pyproject.toml`; a corrupted manifest causes a non-zero exit, not a warning
- **Depends on:** 2

<!-- autofix-applied: 2026-07-28 -->
### Step T4: End-to-end smoke gate — 20 rows, 10 steps, one real verdict
- **Problem:** Prove the whole pipeline can complete one real cycle before spending an hour on a full run, and before any number is measured. Implement `tune/train_sft.py` and `tune/export.py` far enough to train 10 optimizer steps on 20 rows, merge the adapter, convert to GGUF via llama.cpp's `convert_hf_to_gguf.py`, load it into llama.cpp, and send exactly one judge prompt through switchboard's own `local_judge`. Judgment quality is explicitly out of scope; the deliverable is "the producer/consumer chain does not crash, the prompt survives the round trip unchanged, and trained weights actually reach the served model."
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `tune/train_sft.py` (smoke-capable), `tune/export.py`, `tests/test_chat_template_parity.py`, a smoke run log
- **Done when:** all three gates pass — (a) one command runs train(10 steps)→merge→GGUF→llama.cpp→`local_judge` and the returned dict satisfies `result.get("defer") is not True` and carries a `verdict` in `{"pass","flag"}` with a non-empty `reason`; (b) **chat-template parity** — `tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)` from the HF side is compared against llama-server's `/apply-template` response for the identical `msgs`, and the two strings are equal after normalizing trailing whitespace only; if llama-server in the installed revision does not expose `/apply-template`, fall back to reading the `tokenizer.chat_template` string embedded in the GGUF metadata via `gguf-dump` and asserting it equals the HF template source. A mismatch trains one format and serves another and is invisible to every other test in this plan, so this gate blocks; (c) **weights-moved sentinel** — the 20 smoke rows are labeled with a sentinel reason string the base model would never emit (use the fixed literal `ZZ-SMOKE-SENTINEL-7f3a`), and the exported GGUF reproduces that sentinel in `choices[0].message.content` for a smoke-set prompt, proving the merge→GGUF→llama.cpp path carries trained weights rather than silently serving the base model. Total wall clock under ~10 minutes.
- **Depends on:** 3

<!-- autofix-applied: 2026-07-28 -->
### Step T5: Baseline — score the untuned student through the shipped runtime
- **Problem:** Score Qwen2.5-1.5B-Instruct, prompted with the production `SYSTEM_PROMPT` and untouched by training, against the frozen test split. **The baseline must be measured through the same runtime and the same quantization the tuned model will be served on** — convert the untuned base to GGUF at the identical quant level and score it through `local_judge`, exactly as Step 7 will score the tuned model. Measuring the baseline in fp16 transformers and the treatment in quantized llama.cpp would confound the training effect with a runtime and precision change. Also record the `coder-30b` reference column from the live endpoint.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `results/baseline.json` (the D10 three-number block, per-case outcomes, model id, quant level, runtime, git sha, golden-set hash), a short note in `results/comparison.md`
- **Done when:** `baseline.json` records agreement, coverage, and strict scores on the frozen test set with the golden-set SHA and the quant level embedded; the run is reproducible to the same numbers twice at temperature 0 **for the local student runners** (the `claude` runner is explicitly exempt from this reproducibility claim); `baseline.json` and the eventual `tuned.json` agree on `runtime` and `quant` fields, and the harness refuses to emit a delta if they do not; the `coder-30b` reference column is present and labeled as reference, not as a competitor
- **Depends on:** 4

<!-- autofix-applied: 2026-07-28 -->
### Step T6: Full QLoRA SFT run
- **Problem:** Complete `tune/train_sft.py` for the real run: 4-bit base, LoRA rank/alpha recorded, **loss masked on the prompt so only the verdict tokens train**, checkpoint selection on the dev split, temperature-0 eval, and a bounded `max_steps` so the run cannot exceed roughly 90 minutes. Record every hyperparameter alongside the adapter.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** the trained adapter, `results/train_run.json` (hyperparameters, loss curve, chosen checkpoint + why, wall clock, peak VRAM)
- **Done when:** training completes within the step budget without OOM; the selected checkpoint is chosen by dev-split metric and the choice is recorded; prompt-loss masking is demonstrated by a test asserting label tensors are `-100` across the prompt span
- **Depends on:** 5

<!-- autofix-applied: 2026-07-28 -->
### Step T7: Eval the tuned student and write the honest comparison
- **Problem:** Re-score the tuned student on the same frozen test split with the same harness, same runtime, and same quant level, then write `results/comparison.md`: baseline versus tuned across all three D10 numbers, the delta with its direction stated plainly, the `coder-30b` reference column, the Claude self-agreement ceiling, and an interpretation section that separates **format-compliance gains from judgment gains** (a coverage jump with a flat strict score means the fine-tune taught JSON formatting, not code review — say so). If tuning lost, the write-up says tuning lost and explores why. No re-running to chase a better number; a settings change produces a second recorded run, not a replacement. Emit `results/disagreements.jsonl` — one row per case where the tuned student disagreed with Claude — which is both an error-analysis artifact and the input Step 10's predicate tests.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `results/tuned.json`, `results/comparison.md`, `results/disagreements.jsonl`
- **Done when:** `comparison.md` states the delta in percentage points for agreement, coverage, and strict, with the golden-set hash and both model ids; the format-versus-judgment interpretation is present; the numbers in the doc are copy-verifiable from the two JSON files; `disagreements.jsonl` exists (possibly empty) and matches the Appendix A.1 schema. **If the strict delta is zero or negative, the write-up must additionally contain all four of:** (i) the delta stated plainly in the opening sentence, without hedging; (ii) the three most common disagreement patterns, quoted from `disagreements.jsonl` with their case labels; (iii) an explicit list of the candidate explanations considered — too few labels, model too small, teacher labels too noisy (compare against the Claude self-agreement ceiling from Step 3), prompt-loss masking wrong, quantization damage — each marked supported or ruled out **by a number already in hand**, not by speculation; (iv) the one experiment that would most cheaply discriminate between the remaining explanations, written as a concrete next step rather than a vague "more data would help"
- **Note:** a losing result does not block Step 8 or Step 9. The ship script still runs and the certify verdict is still recorded; a tuned model that fails the 0.20 kill rule simply does not get enabled, and that outcome is itself the reportable finding
- **Depends on:** 6

<!-- autofix-applied: 2026-07-28 -->
### Step T8: Ship script — place, certify, and report
- **Problem:** Implement `tune/ship.py`: copy the quantized GGUF into llama-swap's model directory, add the model entry to llama-swap config, invoke `python -m switchboard bakeoff --suite <suite>` against the real endpoint, and surface the `certify_slice` verdict against the existing 0.20 kill threshold. The script only reports — it must not enable a slice on its own.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `tune/ship.py`, a suite file for the tuned runner
- **Done when:** `ship.py --dry-run` prints every action without performing it; the certify verdict is computed with switchboard's own `certify_slice`, not a local reimplementation; the script exits non-zero if the endpoint is unreachable rather than reporting a false pass
- **Depends on:** 7

### Step T9: Live certify and enable decision (operator)
- **Problem:** Run `tune/ship.py` against the live WSL2 endpoint, review the bake-off report, and decide whether the tuned model earns the `review-deep-style` slice. Related to issue #237 (live capture) — this run produces real captured verdicts for the tuned runner, but does not close #237, which needs its own `coder-30b` live capture.
- **Type:** operator
- **Issue:** #
- **Done when (operator confirms each):**
  1. `llama-swap` serves the tuned GGUF and `python -m switchboard config` reports the expected endpoint.
  2. `python -m switchboard bakeoff` produces a report with real captured verdicts (not fixture values).
  3. The disagreement rate is read against the 0.20 strict-greater-than kill rule, with defers excluded.
  4. A written enable/do-not-enable decision is recorded in `results/comparison.md`.
  5. If enabling: `~/.switchboard/config.json` sets `enabled_call_sites["review-deep-style"]` and nothing else; `build-step-style` remains absent or `false`.
- **Depends on:** 8

<!-- autofix-applied: 2026-07-28 -->
### Step T10: Optional DPO stretch
- **Problem:** Build preference pairs from cases where the tuned student disagreed with Claude (Claude verdict = chosen, student verdict = rejected) and run a DPO pass, then re-score on the frozen test split with the same harness, same runtime, and same quant level.
- **Type:** conditional
- **Condition:** `f="$(git rev-parse --show-toplevel)/switchboard-tune/results/disagreements.jsonl"; test -s "$f" && test "$(wc -l < "$f")" -ge 100`
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `tune/dpo.py`, `results/dpo.json`, a comparison section appended to `results/comparison.md`
- **Done when:** DPO completes within VRAM budget and the post-DPO score is recorded against the same frozen test split under the same runtime/quant fields the harness enforces; if the pair-count predicate is false the step skips cleanly and Step 7's write-up notes why
- **Depends on:** 9

---

**Autonomous-behavior classification.** The training and eval pipeline is a set of **one-shot CLI
invocations** that complete and return — it is not a daemon, scheduled job, soak loop, or always-on
watcher. The autonomous-behavior trigger therefore **does not fire** for Steps 1-8 and 10, and reviewers
should confirm that classification rather than looking for a soak step. The one genuinely
observation-shaped unit is Step 9, which watches a real endpoint under live bake-off and is marked
`Type: operator` for exactly that reason.

**Data-pipeline smoke gate.** This feature is a long producer→consumer chain — mined hunk → production
prompt → teacher label → frozen split → tokenizer → trainer → merged weights → GGUF → llama.cpp →
switchboard client → parsed verdict. Every arrow is a place where mocked unit tests pass while the real
chain is broken. **Step 4 is the mandatory smoke gate**, and it deliberately precedes both the baseline
measurement (Step 5) and the expensive training run (Step 6): 20 rows, 10 optimizer steps, one real
verdict through `local_judge`, no mocks anywhere in the chain. Its three gates map to the three arrows
most likely to break silently — the client boundary (a real `Verdict`, not a `Defer`), the template
boundary (train-time and serve-time prompt strings byte-identical), and the weights boundary (a sentinel
the base model cannot produce, proving the merge actually took).

**New tests.**
- `test_evalharness.py` — golden-manifest verification aborts on mismatch; the three D10 numbers are
  computed with the denominators they claim; the calibration anchors bracket the metric;
  `SYSTEM_PROMPT` identity (`is`, not `==`); the harness refuses to emit a delta across mismatched
  `runtime`/`quant` fields.
- `test_switchboard_invariants.py` — `switchboard/pyproject.toml` still declares `dependencies = []`.
  This is the guard that makes D5 mechanical rather than aspirational.
- `test_freeze.py` — split determinism; refusal to overwrite an existing manifest; a one-byte edit breaks
  verification; a planted near-duplicate spanning train and test trips the leakage gate.
- `test_chat_template_parity.py` — the HF-rendered training prompt and the llama.cpp-rendered inference
  prompt are byte-identical for the same case.
- `test_train_sft.py` — label tensors are `-100` across the prompt span (prompt-loss masking actually on).
- `test_label.py` — the `claude -p` seam is invoked with an explicit `--model`, tools disabled, prompt via
  stdin, and `errors="replace"` decoding; a non-UTF-8 byte in a diff does not crash the batch; an
  unauthenticated seam fails loudly rather than emitting zero labels and exiting 0.

**Mined content is data, never instructions.** Step 1 mines diff hunks from real repositories and Step 2
sends them to Claude. A mined hunk could contain text shaped like an instruction — a `<system-reminder>`
block, "ignore previous instructions", or fake tool output — either incidentally (this workspace's own
docs discuss prompt injection) or adversarially. `label.py` must wrap every mined hunk in an explicit
data delimiter, instruct the teacher to treat the payload as the artifact under review rather than as
direction, and discard any response that does not parse to the strict verdict schema. A hunk that
repeatedly fails to yield a schema-valid verdict is dropped from the dataset with its label recorded, not
retried into compliance.

**Existing tests that must not change.** All 183 switchboard tests must pass untouched. A diff to
`switchboard/tests/` in any step of this plan is a signal that scope leaked into the package and should be
challenged in review rather than accepted.

**End-to-end verification.** The feature is verified end-to-end when Step 9's operator run shows a real
bake-off report — captured verdicts, not fixture values — with the disagreement rate evaluated against the
0.20 strict-greater-than rule, and `results/comparison.md` states the baseline-versus-tuned strict delta
with the golden-set hash embedded so the number can be re-derived later.

---

---

Everything a fresh builder needs that is not derivable from the switchboard source.

### A.1 On-disk schemas

Every file below is JSON Lines (one JSON object per line, UTF-8, LF). Field names are exact.

`data/inputs.jsonl` — produced by Step 1, consumed by Step 2:

| field | type | note |
|---|---|---|
| `label` | str | unique case id, format defined in A.3 |
| `diff` | str | the raw hunk text, `+`/`-` prefixed lines, newline-joined |
| `repo` | str | source repo directory name, e.g. `Alpha4Gate` |
| `sha` | str | 40-char commit sha the hunk came from |
| `path` | str | repo-relative file path |
| `lang` | str | one of `py`, `ts`, `tsx`, `js`, `ps1` |

`data/labeled.jsonl` — Step 2 output; every `inputs.jsonl` field plus:

| field | type | note |
|---|---|---|
| `expected` | str | `"pass"` or `"flag"` — the frozen Claude label |
| `reason` | str | Claude's one-line rationale, non-empty |
| `teacher_model` | str | exact model id string passed to `claude -p` |

`data/golden/{train,dev,test}.jsonl` — same schema as `labeled.jsonl`. `data/golden/MANIFEST.sha256`
holds one `<sha256>  <filename>` line per split file, in `sha256sum` format.

`results/baseline.json` and `results/tuned.json` — identical schema:

| field | type | note |
|---|---|---|
| `runner` | str | e.g. `student-prompted`, `student-tuned`, `claude`, `always-pass`, `coder-30b` |
| `model_id` | str | HF repo id or served model name |
| `runtime` | str | `llama.cpp` — the harness refuses a delta across differing values |
| `quant` | str | e.g. `Q4_K_M` — likewise |
| `golden_sha256` | str | manifest hash of the test split scored |
| `total`, `verdicted`, `agreements` | int | raw counts |
| `agreement`, `coverage`, `strict` | float\|null | the D10 numbers; `agreement` is `null` when `verdicted == 0` |
| `defers_by_reason_class` | obj | `{reason_class: count}` using switchboard's `RC_*` strings |
| `cases` | list | per-case `{label, expected, got, deferred, reason_class}` |

`results/disagreements.jsonl` — Step 7 output, Step 10 input: `{label, diff, expected, got, teacher_reason, student_reason}`.

### A.2 The mined-case prompt shape (load-bearing)

A mined case is rendered into exactly two chat messages, assembled by the single `build_messages()`
helper from Step 3:

- **system** — `switchboard.client.SYSTEM_PROMPT`, imported, never retyped.
- **user** — `"Code-style diff under review:\n" + diff + "\n\nRespond with ONLY JSON: {\"verdict\":\"pass\"|\"flag\",\"reason\":\"<short>\"}"`

**Do not copy the hand-authored fixture shape.** The eight cases in
`switchboard/suites/review-deep-style.json` insert an editorial summary sentence between the diff and the
JSON instruction, and those sentences telegraph the answer. The `bare-except` case reads *"Wraps a parse
in a BARE except that swallows every exception including KeyboardInterrupt, hiding real failures"* and is
labeled `flag`; `whitespace-cleanup` reads *"purely cosmetic cleanup"* and is labeled `pass`. A model
could score near-perfectly on those fixtures by reading only the summary and ignoring the diff entirely.

Two consequences make this a hard rule rather than a preference. First, **label leakage**: training on
summary-bearing prompts teaches the student to read the summary, not the code. Second, **train/serve
skew**: mined hunks have no summary and neither does anything the deployed judge sees in production, so a
summary-trained student would face a systematically different input at inference. Mined prompts therefore
carry the diff only. The existing fixtures stay untouched — they are the bake-off's calibration
instrument, not training data.

### A.3 Case-label format

`label` is `<repo>-<sha7>-<n>` — source repo directory name, first 7 sha characters, and a zero-based
per-commit hunk index. Example: `Alpha4Gate-3ac5769-0`. Generated by `mine_inputs.py`; consumed by
`label.py`, `freeze.py`, `evalharness.py`, and any suite file Step 8 writes.

Uniqueness is not cosmetic: `switchboard/bakeoff.py`'s suite loader requires a runner's recorded labels to
cover the suite's case labels **exactly** — no missing, unknown, or duplicate entries — so a duplicate
label surfaces as a suite-load failure at Step 8 rather than as a silently dropped case.

### A.4 Wiring switchboard into switchboard-tune from WSL

`switchboard-tune` declares switchboard as an editable path dependency in its own `pyproject.toml`, which
is how `SYSTEM_PROMPT` and the verdict parser are reused rather than copied:

```toml
[tool.uv.sources]
switchboard = { path = "../switchboard", editable = true }
```

The relative path resolves identically from Windows (`<coding-root>\switchboard`) and from WSL
(`<coding-root>/switchboard`), so no per-platform branch is needed. switchboard is pure-stdlib,
so it imports cleanly under WSL's Python 3.12.3 with nothing else installed.

**Keep large artifacts off `/mnt/c`.** The Windows drive is mounted through the 9P filesystem and is slow
enough to dominate training wall-clock. The repo itself stays on `/mnt/c` so Windows tooling can see it,
but set `HF_HOME=~/.cache/huggingface` and write checkpoints, merged weights, and GGUFs to a native WSL
path such as `~/switchboard-tune-work/`, copying only the final GGUF and the `results/*.json` files back
into the repo.



## Compute target

Existing local endpoint via WSL2; training only in the proposed sibling with its separate CUDA dependencies. Historical July hardware measurements in the archived tune context are observations, not present readiness proof. Keep large training artifacts on native WSL storage. Switchboard itself remains zero-dependency.

## Time budget

[Estimates](build-estimates.md) separate worker effort, operator attention and unknown waiting. Proposed/held external work is excluded from ready-work totals; training runtime bounds and live call budgets inside source units remain binding.

## What's NOT in this plan

- **Enabling offload by default** — every slice stays off until B1 certifies it AND the operator opts in. No-config = inert = today's behavior.
- **`build-step-style` offload** — build-step Step 7 IS the merge gate; a weak model never owns it (Decision 3). Stays `false`.
- **The Lever-2/3 token work** — separate (branch `token-levers-l2-l4a`); this plan is gated *behind* it.
- **Endpoint provisioning / WSL2 llama-swap keep-alive** — operational, not code; a prerequisite for B2's live run, deferrable (B1's recorded-output mode proves the harness without a live endpoint).

No <friend-project> main-branch mutation, automatic PR merge, automatic enablement, new runtime dependency in Switchboard, or inference that a completed test certifies a deployed model.

## Tracking

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

| Item | Risk | Mitigation |
|---|---|---|
| Active worktree collision | delete work that is about to land | Step 70 hard reconciliation |
| Health appears equivalent to correctness | reachable model is uncertified | separate endpoint, bakeoff, and live-cert states |
| Wiring scan drifts | false proof | resolve current locators and show missing explicitly |

| Item | Risk | Mitigation |
|---|---|---|
| Per-sub-agent model (Tier B) may not be in transcripts | the viewer can't show sub-agent models | Step 1 spike decides; ship Tier A (per-session) regardless, defer Tier B if absent |
| Override touches session launch | a bug breaks how ALL <friend-project> sessions start | inert-when-unset (byte-identical default), vitest "unchanged when unset" test, Step 6 guard, separate PR |
| Per-session token is auth-sensitive | a leaked/mis-scoped token | startup validator (Step 6); never log token bytes (security.md); metadata-only |
| New TS/Node toolchain for this workspace | gate/build friction | follow <friend-project>'s CLAUDE.md (the exact `tsc -p tsconfig.app.json` / vitest `--exclude='e2e/**'` traps) |
| It's a friend's repo | an unwanted/large change | branch + PR only, owner reviews/accepts; viewer-first (small, additive); no push to main |
| cc-quota has no model | viewer can't get model from cc-quota | use context-usage's extraction (Step 2), not cc-quota, for model |

| Item | Risk | Mitigation |
|---|---|---|
| **Defer-inflated baseline** | A 1.5B often fails to emit parseable JSON, so switchboard's native agreement metric scores the baseline over a small self-selected subsample and the tuned model over nearly all cases — comparing two different test sets and manufacturing a fake delta | **D10**: every runner reports agreement + coverage + strict; the headline claim uses **strict**, whose denominator is fixed by the frozen golden set. This is the single most important correction in this plan. |
| **Chat-template drift** | The HF tokenizer's training-time template and llama.cpp's serve-time template differ, so the model is trained on one format and served another — invisible to every unit test and to the eval itself, which would simply report a bad score with no explanation | Step 4 gate (b) asserts byte-for-byte parity and fails the smoke before any expensive run |
| **Silent no-op merge** | The adapter fails to merge, or GGUF conversion drops it, and llama.cpp serves the base model while every step reports success — producing a "tuned" score that is really a second baseline run | Step 4 gate (c): the smoke rows carry a sentinel reason string the base model cannot emit; the exported GGUF must reproduce it |
| **Runtime confound** | Baseline measured in fp16 transformers, treatment measured in quantized llama.cpp — the delta then mixes the training effect with a precision and runtime change | Step 5 converts the *untuned* base to GGUF at the identical quant level and scores it through `local_judge`; the harness refuses to emit a delta when `runtime`/`quant` fields disagree |
| **Train/test leakage via near-duplicates** | Exact-match dedup misses hunks differing only by a variable name; one spanning train and test inflates the tuned score | Step 2's `freeze.py` runs a Jaccard-similarity gate at 0.9 before writing the manifest and hard-exits on a violation |
| 8 GB VRAM ceiling | QLoRA OOM at 1.5B if sequence length or batch is set naively | D1 pins 4-bit + 1024 tokens; Step 4's smoke gate surfaces OOM in 10 minutes rather than 90; peak VRAM recorded in Step 6 |
| 15.5 GB system RAM, and WSL2 defaults to roughly half of it | GGUF conversion or dataset processing gets OOM-killed inside WSL | Verify WSL memory during Step 4; if short, raise it via `.wslconfig` — a documented one-line operator fix, recorded in the README |
| Injected instructions inside mined diffs | A mined hunk contains `<system-reminder>`-shaped text or "ignore previous instructions" and steers the teacher, poisoning labels | Step 2 wraps every hunk in an explicit data delimiter and discards responses that do not parse to the strict verdict schema (Testing Strategy § "Mined content is data") |
| Unauthenticated `claude -p` seam | The batch emits zero labels and exits 0, poisoning every downstream step with an empty dataset | Step 2 fails loudly on an unauthenticated seam; the toolchain section names `CLAUDE_CODE_OAUTH_TOKEN` as the prerequisite |
| Teacher labels are Claude's opinion, not ground truth | The whole eval measures agreement-with-Claude, not correctness | Stated explicitly in `comparison.md`: the metric is *agreement with the teacher*, which is exactly what switchboard's kill rule already measures. Scope of claim pre-registered in D2. |
| Class imbalance in mined inputs | Real diffs may be overwhelmingly `pass`, so a constant-`pass` student scores well | The `always-pass` calibration anchor in Step 3 measures this directly; Step 2's run log reports the label distribution; report balanced accuracy alongside raw agreement if skew exceeds roughly 70/30 |
| `claude -p` batch cost and wall clock | Labeling 2,000 inputs is slow or expensive | Start at 500 (the floor that satisfies the plan); `label.py` is resumable, so the batch can grow incrementally |
| llama.cpp conversion script drift | `convert_hf_to_gguf.py` may not support the chosen architecture in the installed llama.cpp revision, or may not be present at all | Presence is **not yet verified** — Step 4's smoke gate locates and pins it before the expensive run; fallback is to clone and pin a known-good llama.cpp revision, recorded in the README |
| A 1.5B may simply be too small for the task | Both baseline and tuned score near chance, making the delta meaningless | This is a legitimate finding, not a failure — D9 ships it. The `coder-30b` reference column quantifies the capability gap. |
| Stale plan siblings say `general-35b` | A fresh model follows the wrong model name and wrong `max_tokens` | This plan names `coder-30b` throughout and annotates both stale files (Impact Analysis rows) |
| Scope creep into switchboard | A convenient helper lands in `switchboard/` and drags in a dependency | Step 3's `dependencies = []` regression test fails CI if it ever happens |

**Open question OQ1 (tracked in Appendix B, surfaced in the proposal):** should Step 2 target 500 labels
(fastest honest path) or push toward 2,000 (better training signal, more teacher cost)? **Resolved default
for building purposes: start at 500 and grow incrementally**, since `label.py` is resumable and a larger
batch can be appended without redoing any downstream step. A builder should proceed on 500 unless the
operator has replied `OQ1 -> 2000`. This is the only decision in the plan left open to the operator.

---

### Operator surface source decisions

| ID | P/D | Choice | Status |
|---|---|---|---|
| P2 | P | Add show-switchboard and evaluate bakeoff as a main action | accepted |
| D3 | D | Switchboard owns config/health artifacts; dev-observatory owns caller/pin HTML | accepted |
| D7 | D | Reconcile the active endpoint-launcher worktree before keeping/removing start buttons | accepted |

### Tune source decisions

IDs are **append-only and stable** across republishes of the proposal. A reversed decision is marked
`changed <date>` rather than renumbered or deleted. `P` = operator-picked; `D` = agent-defaulted.

| ID | P/D | Choice | Status |
|---|---|---|---|
| P1 | P | Professional variant (switchboard's local judge) over the toybox activity generator | accepted 2026-07-28 |
| P2 | P | The 5-step spine from the operator's own brief: freeze → baseline → SFT → eval+ship → optional DPO | accepted 2026-07-28 |
| D1 | D | Student is `Qwen/Qwen2.5-1.5B-Instruct`, QLoRA 4-bit (forced by the measured 8188 MiB VRAM ceiling) | proposed |
| D2 | D | Comparison is student-vs-itself; `coder-30b` is a reference column only; claim pre-registered | proposed |
| D3 | D | Teacher labels via the `claude -p` subprocess seam, not the Anthropic API | proposed |
| D4 | D | Dataset inputs mined from real `dev/` git history rather than synthesized by Claude | proposed |
| D5 | D | Code lives in a new sibling project `switchboard-tune/`, running in WSL2 for CUDA | proposed |
| D6 | D | Golden set frozen + hash-pinned before training, with known-good/known-garbage calibration anchors | proposed |
| D7 | D | Ships only by clearing `python -m switchboard bakeoff` under the existing 0.20 kill rule | proposed |
| D8 | D | DPO gated behind a `≥100` disagreement-pair conditional predicate | proposed |
| D9 | D | Negative results ship; no rerunning to chase a better number | proposed |
| D10 | D | Every score is three numbers (agreement / coverage / strict); headline delta uses **strict** | proposed (added by plan-review 2026-07-28) |
| OQ1 | D | Teacher-label target: start at 500 and grow incrementally, rather than minting 2,000 up front | open — awaiting operator |

---

OQ1 teacher label target remains open; the starting 500-label proposal is not silently approved by documentation cleanup.

## Plan history

2026-10-14: semantic consolidation. Umbrella Phase A remains completed history; umbrella B1-B3 are subsumed by concrete Phase B units. Surfaces reuse the same config/bakeoff owners; <friend-project> and tune retain distinct ownership and gates. Historical completed detailed substrate design remains in the existing workspace archive; no old phase is reopened.


### Documentation reconciliation decisions

| ID | P/D | Choice | Status |
|---|---|---|---|
| DOC-P1 | P | Standard docs layout, preserve originals, repair affected references | accepted 2026-10-14 |
| DOC-P2 | P | Preserve shared Toolkit execution/status ownership for mapped work | accepted 2026-10-14 |
| DOC-D1 | D | Remove umbrella duplicate executable phases while retaining their gates. | applied 2026-10-14 |
| DOC-D2 | D | Namespace original numeric steps by source track; keep <friend-project>/tune external and held. | applied 2026-10-14 |
| DOC-D3 | D | Move shared prompt helper construction before its teacher-label consumer. | applied 2026-10-14 |
