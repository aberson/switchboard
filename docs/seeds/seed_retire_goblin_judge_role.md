# Seed: Retire the role-goblin-judge role

**Status:** queued 2026-11-18. Not started; no lane. Light work; build when switchboard work resumes.
**Requested by:** dev-observatory core-companion (V4-10 plan), forwarded by dev-observatory main in note `20261118T014436Z-main-to-main-5fc2`. The goblin skills it served are retired, so the role has no caller.

## What changes

| Where | Line | Change |
|---|---|---|
| `registry/models.json` | 44-51 | Remove the `goblin-judge` entry |
| `switchboard/registry.py` | 54 | Remove `goblin-judge` from `ALLOWED_ROLES` |
| `tests/test_registry.py` | 89 | Drop the `goblin-judge` row |
| `docs/observatory-contract.json` | 226 | Remove the role (see the constraint below) |
| `docs/plans/master_plan.md` | 1391 | Mark the role table row retired (R-P5 at 1419 keeps it as history) |

The role id is `goblin-judge`; its generated agent files are named `role-goblin-judge`.

The generator is `switchboard/generate.py`. After the edits, regenerate and prune the installed role files with `uv run python -m switchboard apply --prune --write`, which removes the user-level Claude agent file and Codex agent file for the role.

## Constraints

- dev-observatory Step 39a pins its switchboard panel to `docs/observatory-contract.json`. Removing the role there needs a dev-observatory pin check: tell dev-observatory main (through coding-root main) before the contract change lands, and again when it has.
- Grep every consumer of the role id before landing (`code-quality.md`, key-shape rule).
- No home paths in committed text; locators stay repository-relative.

## When it is picked up

Turn this into a `### Step` in `docs/plans/master_plan.md` through the normal plan flow, with an issue, then build it.
