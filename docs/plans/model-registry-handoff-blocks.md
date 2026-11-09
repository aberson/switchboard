# Model registry handoff blocks (skill-mesh and measure-twice)

Companion to the switchboard [master plan](master_plan.md#model-registry-track-r), model registry
track R (2026-11-08). These blocks are **not steps of the switchboard plan** (decision R-P2). Paths
inside each block are relative to the named repository (`skill-mesh/` or `measure-twice/` under
`<coding-root>`). Cross-references such as R1, R2, R5, R-D5, R-D9 and R-D13 name steps and
decisions in that track.

## Adoption

Each block follows the step contract so the adopting plan can paste it, renumber it into its own
sequence, and run plan-review, plan-redline, plan-wrap and repo-sync there.

Adoption preconditions:
- the target tree's concurrent work has landed;
- the Toolkit program has selected the work;
- for skill-mesh, R2 is built and R5 passed;
- for skill-mesh, the usage review's worktree `skill-mesh-q1-followups` is settled: branch
  `q1/usage-review-followups` (`7c35e03`) is merged or dropped, and its uncommitted judge-call prose in
  goblin-suggest, review-deep, review-gauntlet, skill-evolve, skill-iterate and context-slim has landed
  or been dropped. R-SM3 and R-SM4 edit the same files, so re-verify their line citations afterwards.

Once a block is adopted, the target plan is authoritative and this appendix points to it.

## R-SM1 (skill-mesh): Spawn-site gate and declaration
- **Problem:** Make every helper launch a declared, gated fact. Each dispatch locus must map to a role or
  an explicit `inherit`, and any new launch that names a model fails the package gate.
- **Type:** code
- **Flags (suggested):** --reviewers deep --isolation worktree
- **Files:** `config/spawn-sites.json` (new; site id to role or `inherit`),
  `tests/package-integrity/test_spawn_sites.py` (new), `tests/package-integrity/spawn_baseline.json`
  (new, frozen and shrink-only), `tools/gen_manifest.py` (ship `_shared/spawn-sites.json` as a support
  asset), the regenerated manifest and inventory
- **Produces:**
  - A detector over cores, the claude and codex adapters, and `_shared` and skill workflow scripts. gpt
    adapters are excluded with the reason: they halt at Step 0 for spawning skills (D-GPT).
  - The Step-63 pattern: a frozen baseline with a digest pin, scope floors, and red-on-garbage anchors.
  - All 42 loci declared, with today's model-naming sites frozen in the baseline.
  - A row-count reconciliation against `v3/w3-pin-ledger`'s 67 rows.
  - A sibling issue for `skill-eval-setup` missing from `SUB_AGENT`.
- **Done when:** The gate passes on the current tree. It fails on a synthetic new `model: sonnet` spawn
  and on a narrowed scan scope. `_shared/spawn-sites.json` is present in the built claude and codex
  profiles. The `python -m pytest tests/package-integrity` run is named in the checkpoint.
- **Depends on:** R1 (role names)

## R-SM2 (skill-mesh): build-step dispatches by role
- **Problem:** Make build-step's developer, reviewer, re-dispatch and diagnosis launches name roles on
  Claude and Codex, with a non-blocking fallback when a role file is missing.
- **Type:** code
- **Flags (suggested):** --reviewers deep --isolation worktree
- **Files:** `skills/build-step/core.md` (`:123-127`, `:330`, `:418`, `:511`, `:683`),
  `skills/build-step/providers/claude.md:14`, `skills/build-step/providers/codex.md:7-10`,
  `config/spawn-sites.json`, `tests/package-integrity/spawn_baseline.json`, the affected contract tests
- **Produces:**
  - On Claude, `subagent_type: role-builder|role-reviewer|role-diagnosis`; on Codex, a spawn by the same
    agent names.
  - No model names remain at these sites. The phone-a-friend arm's `model: fable`
    (`skills/build-step/providers/claude.md:14`) becomes `role-diagnosis`, which runs `claude-opus-5-5`:
    no skill dispatches Fable automatically (registry decision R-P7).
  - The fallback reports `role_missing` and never blocks (R-D13).
  - The baseline loses exactly the build-step entries.
  - A release is cut, and its install note runs `python -m switchboard apply --catalog <installed _shared/spawn-sites.json>`
    clean before installing.
- **Done when:** The targeted suites pass, and the built claude and codex profiles carry role dispatch
  text with no model names at those sites. The full `python -m pytest` runs at the phase gate, about four
  hours, and the checkpoint names it.
- **Depends on:** R-SM1, R2, R5

## R-SM3 (skill-mesh): Judge, lens and grader sites dispatch by role
- **Problem:** Move the review, judge and grader launches to roles, or to explicit `inherit`, following
  the behavior-preserving rule (R-D5).
- **Type:** code
- **Flags (suggested):** --reviewers deep --isolation worktree
- **Files:**
  - review-deep: `skills/review-deep/core.md:107,126,619-624,642-657`.
  - review-gauntlet: `skills/review-gauntlet/core.md:99,151`.
  - citation: `skills/citation-review/core.md:52` and `skills/citation-sweep/core.md:43` (declare
    `inherit`).
  - skill-eval-setup: `skills/skill-eval-setup/core.md:422,584,650`.
  - Workflows: `_shared/score_skill.workflow.js` (declare `inherit`), and the goblin-suggest workflow
    (locate the canonical source first; only the installed copy was found).
  - Judges: `skills/judge-ui/core.md:80-83`, `skills/judge-motion/providers/claude.md:124,195`.
  - Final judges: `skills/user-uat/core.md:136,156`, `skills/lesson-harvest/core.md:278,310`.
- **Produces:**
  - The listed launches name roles or `inherit`.
  - review-deep's `--model-override <lens>=<tier>` stays as a documented runtime override (pins are
    defaults), and the gate allowlists it.
  - review-deep route 2 (`claude -p` per lens) moves to role dispatch only if the CLI can select an agent.
    Otherwise it stays in the baseline with the reason.
  - The review-deep `model-tier-map.json` snapshot is untouched.
- **Done when:** The baseline loses every listed entry except the recorded exceptions; the targeted suites
  pass; the full suite runs at the phase gate.
- **Depends on:** R-SM2

## R-SM4 (skill-mesh): Author, scanner and diagnosis sites dispatch by role
- **Problem:** Move the remaining authoring, scanning and repro launches to roles, so that no skill-mesh
  launch names a model.
- **Type:** code
- **Flags (suggested):** --reviewers deep --isolation worktree
- **Files:**
  - `skills/user-brainstorm/core.md:98`.
  - `skills/user-learn/core.md:70` and `providers/codex.md:11` (implementation arms become `builder`;
    update the codifying assertion at `tests/package-integrity/test_v2_authoring_contract.py:49`).
  - `skills/skill-iterate/core.md:447`.
  - `skills/context-slim/providers/claude.md:59`.
  - `skills/research-prospect/core.md:65`. The same line cites `model-tiering.md § Default: Opus 4.8 +
    Sonnet fan-out`, a heading R9 renames; drop that citation when the line moves to the `scanner` role.
  - `skills/test-prune/core.md:25`.
  - `skills/tier-escalate/core.md:70`.
  - `skills/tier-offload/core.md:86`.
  - `skills/user-debug/core.md:169,221`.
  - `m2_launcher.workflow.js`: locate its canonical source (only the legacy top-level and release-stage
    copies were found).
- **Produces:** No model-naming spawn entry remains in the baseline beyond the recorded runtime-override
  paths, and `_shared/spawn-sites.json` covers every site.
- **Done when:** The gate passes with only those exceptions, the full suite passes at the phase gate, the
  release is installed, and `python -m switchboard apply --catalog` reports full coverage.
- **Depends on:** R-SM3

## R-MT1 (measure-twice): Claims export, status parity and initial claims
- **Problem:** Give switchboard a stable, committed view of claim status, and give every initial registry
  row a claim, without coupling switchboard to the ledger's internals.
- **Type:** code
- **Flags (suggested):** --reviewers code --isolation worktree
- **Files:** `measure_twice/cli.py` (a `claims export` action next to `list|audit|render`),
  `measure_twice/ledger.py`, `tests/test_ledger.py`, `tests/test_switchboard_status_parity.py` (new),
  `data/ledger/claims.jsonl`, `data/exports/claims.json` (new, committed)
- **Produces:**
  - `uv run mt claims export --out data/exports/claims.json` writes
    `{schema_version, claims: [{claim_id, status, decision_surface, last_verified_utc}]}`.
  - A parity test asserting that `ClaimStatus` order equals switchboard's `CLAIM_STATUSES`.
  - One ASSERTED claim per initial row not already covered. Each cites the row's lines in
    `switchboard/registry/models.json` with a quote hash, so a later swap turns it STALE on `audit`.
  - The researcher, extractor and research-verifier deep-research rows cite the existing
    `deep-research-sonnet-arms-a3`.
- **Done when:** The export round-trips through `load_ledger`. The parity test fails if either constant
  changes. Every `claim_id` cited by the registry exists in the export.
- **Depends on:** R1
