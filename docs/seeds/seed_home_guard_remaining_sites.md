# Seed: guard the remaining Path.home() calls (#582)

> **Operator request, 2026-11-09.** Finish what R3 started: every switchboard command reports a
> missing home directory the same way, never as a traceback.
>
> - **Owner:** issue #582. No plan step carries it yet. R3's Produces names these two sites as
>   out of R3 and owned by #582.
> - **Next, either route:**
>   - plan it: `/plan-feature switchboard/docs/seeds/seed_home_guard_remaining_sites.md`, with
>     [`../plans/master_plan.md`](../plans/master_plan.md) as the parent (adds one Track R step);
>   - or, as one small change: `/build-step` from `<coding-root>\switchboard` with
>     `--reviewers deep --isolation worktree --issue 582` and the Problem text below.

## Problem (ready to paste)

`switchboard/config.py` `_default_config_path` (lines 303-309) and the home lookup in
`switchboard/generate.py:817` (`apply`) call `Path.home()` with no guard. So plain `inspect`
(no `--path`, no `SWITCHBOARD_CONFIG`) and every `apply` form end in a `RuntimeError` traceback
when no home directory can be determined. R3 already handles this case for `observe` and
`inspect --roles`, through `observe.HomeUnavailableError` and `_expand_user`. Make the two
remaining sites report it the same way, through one shared helper, with a test per command driven
through `cli.main` that makes `Path.home()` raise.

## Requirements

1. **One source of truth.** Move the home-resolution helper (and `HomeUnavailableError`) into a
   leaf module that `observe.py`, `config.py` and `generate.py` all import. Delete the duplicate
   pattern at `generate.py:817` (`.claude/rules/code-quality.md`, one source of truth for
   data-shape constants and the sibling audit).
2. **Behaviour.**
   - Full `inspect` and `inspect --json` with no config source and no home exit 0. They report
     the config source as unavailable, as data, and keep switchboard's fail-safe inert defaults.
     The plan settles the exact fields, for example a null `config_source` with the reason.
   - Every `apply` form exits 2 with one advisory line and writes nothing, matching `observe`.
   - An unexpandable `~` in `--home` behaves the same.
3. **Tests through the production entry point.**
   - One `cli.main` test per command, with `Path.home()` made to raise the way R3's `_lose_home`
     does, and without patching the default config lookup away (R3's round-1 review caught exactly
     that).
   - Each guard's test must fail with that guard removed.
4. **Contract and docs.**
   - Update `README.md` exit codes.
   - Update `docs/observatory-contract.json` and `.md` if an inspect field becomes nullable or new.
   - Update R3's Produces note only to point at the step that closes #582.
5. **Scope.** No change to what a successful run prints or writes when a home exists.

## Ground truth (2026-11-09)

- #582 lists both sites with their current behaviour and the suggested shared helper.
- R3's no-home tests live in `tests/test_observe.py` (the no-home section). Reuse its helpers and
  constants, not a second copy.
- Gates: `uv run mypy --strict switchboard`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest` (368 passed / 2 skipped before this change).
