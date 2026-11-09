# Seed: R7 kickoff — migrate deep-research-pinned to role dispatch

> **Operator request, 2026-11-09.** A ready-to-run kickoff for plan Step R7 (#577), parked until
> Phase R-B is selected. R7 is already planned in
> [`../plans/master_plan.md`](../plans/master_plan.md) (`### Step R7:`), so this is not a new
> plan. It records what is ready, what changed since R7 was written, and the exact command.
>
> - **Gate:** Toolkit program unit U04 governs when Phase R-B starts (plan Track R, "Steps"
>   table). Do not start R7 until U04 selects it.
> - **Satisfied:** R7 depends on R5, which passed on 2026-11-09 on all four dispatch paths. That
>   includes the Workflow `agentType: role-extractor` path that deep-research-pinned uses (#575).
> - **Next, once U04 selects R-B:**
>   - Run in: `<coding-root>` (the repository root, see Gotchas)
>   - `/build-phase --plan switchboard/docs/plans/master_plan.md --steps R7`

## What R7 changes (from the plan)

- `.claude/workflows/deep-research-pinned.js`: search arms use `agentType: 'role-researcher'`,
  fetch arms `role-extractor`, and verify arms `role-research-verifier`. None passes `model` or
  `effort`. The scope and synthesize phases still inherit the session model. The header stops
  telling the operator to switch the session to Fable (plan R-P7).
- `switchboard/registry/models.json`: the researcher, extractor and research-verifier rows cite
  `deep-research-sonnet-arms-a3`.
- `.claude/references/model-tiering.md` (lines 69-73): name the roles instead of the model.
- Done when: no `model:` or `effort:` agent option remains in the script; `grep -n "claude-fable"`
  over it returns nothing; the three rows equal the script's previous values; and
  `python -m switchboard apply` lists the three role files as unchanged.

## Ground truth checked 2026-11-09 (read-only)

| Fact | Value | Note for the build |
|---|---|---|
| Script git state | clean | No other window is editing it |
| Header lines | `:13-17` (`:15` is the Fable instruction) | The plan says `:12-18` |
| Search arm `model: "sonnet"` | `:189` | The plan says `:188` |
| Fetch arm `model` / `effort: "low"` | `:223-224` | The plan says `:219-224` |
| Verify arm `model: "sonnet"` | `:274` | The plan says `:270`. Re-read the file; do not trust plan line numbers |
| Registry rows | researcher, research-verifier: `claude-sonnet-5-5` / inherit; extractor: `claude-sonnet-5-5` / low | Values already equal the script's |
| Row `claim_id` | `registry-<role>-initial` | R7 Files expects `deep-research-sonnet-arms-a3`; measure-twice must hold that claim first, or the plan decides |
| Role files on disk | 14 Claude + 14 Codex, written by R5's `apply --write` | So "apply lists unchanged" is checkable |

## Gotchas from R5 (2026-11-09)

- **Run from the repository root.** R7 edits files outside `switchboard/` (`.claude/workflows/`,
  `.claude/references/`). A `/build-phase` started in `switchboard/` scopes `/build-step` to that
  directory and ends the step as a scope escape. Expect the `REPO-WIDE-SCOPE` advisory, and expect
  the dev root to be dirty with other windows' files: checkpoints stage only landed paths.
- **Fresh window for the first real run.** A window that started before `apply --write` may not
  list `role-*` agents yet. R8 (the operator's first real dispatches) should run in a fresh window.
- **Only `role-extractor` has been proven through Workflow `agentType`.** `role-researcher` and
  `role-research-verifier` get their first real dispatch in R8; check them with
  `uv run python -m switchboard observe --host claude --latest --project-dir <run dir>` and
  `inspect --roles`, scoped as the R5 probe was.
- **Confound guard.** The session model (Opus) differs from the arms' pin (Sonnet), so a
  `match` receipt proves that the role file set the model. Keep it that way when verifying.
- **No Fable.** Nothing in the script may name or suggest a Fable model (R-P7).
