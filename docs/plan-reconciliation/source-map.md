# Source extraction and merge map

## switchboard-offload-plan.md
- Vision / goal: optional cheaper judge offload.
- Phase list: A completed config-loader; B1 bakeoff/B2 certify/B3 effort.
- Data contracts: config + verdict/defer; fail-safe, disabled-by-default.
- External dependencies: existing core, local endpoint, Claude ground truth.
- Kill criteria and rollbacks: no cert -> no enable; >0.20 disagreement disables.

## switchboard-offload-phase-b-plan.md
- Vision / goal: validated live slice enablement.
- Phase list: 1 DONE,2 DONE,3 operator pending,4 DONE.
- Data contracts: bakeoff v1, certify rules, effort and surgical monitor disable.
- External dependencies: Phase A, endpoint, explicit live operator selection.
- Kill criteria and rollbacks: >0.20 non-defer disagreement; never correctness gate.

## switchboard-operator-surfaces-plan.md
- Vision / goal: clear inspect/config/launcher UX.
- Phase list: 70-73 DONE;74 operator UAT.
- Data contracts: versioned observatory JSON and recorded bakeoff artifacts.
- External dependencies: existing config and bakeoff owners.
- Kill criteria and rollbacks: launcher cannot imply enablement; malformed config distinct.

## switchboard-phase-2-plan.md
- Vision / goal: external session attribution and guarded overrides.
- Phase list: 1-6 branch DONE;7 visual UAT and PRs.
- Data contracts: message.model attribution; model allowlist; ephemeral token.
- External dependencies: <friend-project> feature branches and owner review.
- Kill criteria and rollbacks: unset inert; rejected override no side effects; never log/persist token.

## switchboard-tune-plan.md
- Vision / goal: honest same-student fine-tune measurement.
- Phase list: 1-9 proposed;10 conditional DPO.
- Data contracts: frozen split hashes, JSONL schemas, shared prompt, strict/coverage/agreement.
- External dependencies: new sibling, WSL CUDA, explicit Claude teacher labels.
- Kill criteria and rollbacks: smoke before training; negative result valid; no test tuning.

## Explicit overlap/subsumption
[PATTERN: same-goal-different-fidelity] Umbrella A duplicates completed config-loader; umbrella B1/B2/B3 map respectively to B1/B2+B3/B4, removed as separate units. [PATTERN: same-artifact-different-owners] O71-O73 reuse B config/bakeoff owners, not a second policy store. [PATTERN: implicit-prerequisites] T1 now owns shared prompt helper before T2 consumes it; T3 validates it. <friend-project> and tune are distinct external tracks, not subsumed. New coder-30b defaults supersede historical general-35b assumptions without rewriting the preserved evidence. P1 actual transcript decision supersedes early sidecar assumption.


## Move record

See `moves.json` for pre-move git status, original hashes, archive destinations and affected references. Original plans are preserved byte-for-byte. Historical evidence paths/hashes are not current execution authorization.
