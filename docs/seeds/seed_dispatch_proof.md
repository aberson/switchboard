# Seed: dispatch proof — a standing check that each role runs its pinned model

> **Operator request, 2026-11-09.** Turn the experiment that closed R5 (#575) into a standard,
> repeatable proof point that the model registry works, and show its verdict in dev-observatory.
>
> - **Next:** hand this file to `/plan-feature` as the seed, with
>   [`../plans/master_plan.md`](../plans/master_plan.md) (Track R) as the parent.
> - **Consumer half:** [`dev-observatory/docs/seeds/seed_switchboard_dispatch_proof_view.md`](../../../dev-observatory/docs/seeds/seed_switchboard_dispatch_proof_view.md)
>   owns the dev-observatory reader and view. dev-observatory never imports switchboard; it reads
>   the producer artifact this seed defines.
> - **Already hooked up (2026-11-09):** the observatory registry's switchboard `[project.launch]`
>   table has a `roles` verb (`uv run python -m switchboard inspect --roles`, task
>   `obs: switchboard: run-roles`). It shows requested versus observed per role from the real
>   receipts. It is the readout only, not the proof run.
> - **Origin:** session 3202181c (2026-11-09): the R3 build, an offline 12-claim check of the
>   Phase R-A tour, and the R5 live probe.

## Goal

Answer one question on demand, with a dated verdict a person or dev-observatory can read:

> Does a dispatch by role name run the model and effort the registry pins, on every host and
> dispatch path we rely on?

The verdict must fail when the answer is no, and must go stale when the registry or a host CLI
changes, so a green proof can never outlive the facts it was taken on.

## Baseline: what the 2026-11-09 run proved

**Tier B, live (real home, operator-approved).** Plan Status for R5 is in 9eda81aa; #575 is closed
with the table.

| Path | Parent ran | Role ran | Pinned | Result |
|---|---|---|---|---|
| Agent tool `subagent_type: role-extractor` (VS Code) | session model | `claude-sonnet-5-5` / low | `claude-sonnet-5-5` / low | match |
| Workflow `agentType: role-extractor` (VS Code) | session model | `claude-sonnet-5-5` / low | same | match |
| `claude -p --model claude-opus-5-5` (PATH CLI 2.1.311) | `claude-opus-5-5` | `claude-sonnet-5-5` / low | same | match |
| `codex exec` spawn of `role-builder` (Codex 0.167.0) | `gpt-6-astra` | `gpt-5.6-sol` / medium | `gpt-5.6-sol` / medium | match |

**Tier A, offline (throwaway home, synthetic fixtures).** All of these passed, including the two
negative controls:

| ID | Check |
|---|---|
| A1 | `inspect --roles --json --home <tmp>` lists exactly the registry's roles; every observed value is `unknown`; `receipts_state` is `absent` |
| A2 | `apply --home <tmp>` without `--write` creates no file |
| A3 | `apply --write --home <tmp>` creates `role-<role>.md` and `role-<role>.toml` for every role; each ledger sha256 equals an independent hash of the file |
| A4 | **Control:** a hand-edited role file survives a second `apply --write` byte for byte (and a refuse line prints) |
| A5 | `observe` on `claude-role-reviewer.jsonl` -> `inspect` shows reviewer/claude `match` |
| A6 | **Control:** `observe` on `claude-role-reviewer-style-mismatch.jsonl` -> `mismatch`, never `match` |
| A7 | `observe` on `claude-no-agent-type.jsonl` -> receipt with role `unattributed`, `agent_type` null |
| A8 | Every receipt has the 10 documented fields, and no message text from the fixture transcripts appears in `receipts.jsonl` |
| A9 | With USERPROFILE, HOMEPATH, HOMEDRIVE and HOME unset (a real process, no mock): `inspect --roles --json` exits 0 with `receipts_state: invalid`, `receipts_source: null`; `observe --latest` exits 2 with one line, no traceback |

The throwaway script was `verify_tour.py` (session scratchpad, not committed). Its tour-specific
ledger checks (commit SHAs on origin, issue states) do not belong in the standing proof.

## Shape

| Tier | Runs | Touches | Proves | Cannot prove |
|---|---|---|---|---|
| **A, contract** | Any time, unattended, in CI-like conditions | A temporary home only | switchboard's own logic: generation, ledger ownership, receipt parsing, status join, no-home handling | That real hosts honour role files |
| **B, live dispatch** | On demand, operator-approved | The real home (`apply --write`, receipts) and two headless host sessions | That each host and path runs the pinned model and effort | Roles or paths not exercised |

## Requirements

1. **Pass rules are fixed in code before a run, never judged after.** A Tier B path passes only
   when `observed_model == requested_model`, the effort matches (or the pin is `inherit` and an
   effort is recorded), and the confound guard (requirement 3) holds. A path that cannot run is
   `NOT RUN` with its reason. A path that runs but cannot be judged is `INCONCLUSIVE`. Neither
   ever counts as `PASS`.
2. **Controls must discriminate.** Tier A keeps A4 and A6 (or stronger). A Tier A run whose
   controls pass with the behaviour removed is invalid. Calibrate once by pointing the run at a
   deliberately broken copy (for example a registry pin changed so A5 must flip to `mismatch`).
3. **Confound guard.** On every Tier B path the parent session must run a different model from
   the role's pin. Otherwise a role file that is ignored, with the child inheriting from the
   parent, would look like a match. Record the parent model per path. Equal models give
   `INCONCLUSIVE`.
4. **Scoped transcript selection.** Every live `observe` names its transcript by a dedicated
   probe directory (`--project-dir`) or an explicit path. A bare `--latest` can pick up another
   session's subagent.
5. **Codex forks parent history.** Judge a Codex child only by its own `turn_context` lines.
   The child rollout also carries the parent's model from forked history (seen 2026-11-09).
6. **Host preflight, recorded in the result.** Claude CLI at least 2.1.292 (the R5 floor). The
   Codex CLI must be able to run the configured default parent model: 0.147.0 could not run
   `gpt-6-astra`, 0.167.0 could. A failed preflight is `NOT RUN (cli: <reason>)` with the upgrade
   command, never a silent pass or a silent upgrade.
7. **Session freshness.** A window that started before `apply --write` may not list the
   `role-*` agents yet (seen 2026-11-09; they appeared later in the same window). The
   interactive paths record session start versus apply time; a missing agent type is
   `NOT RUN (session predates role files)`, not `FAIL`.
8. **Real-home writes only with operator approval** (decision R-D11). Tier A never reads or
   writes the real home. It asserts afterwards that `~/.switchboard/receipts.jsonl` is unchanged.
9. **Proof record, project-relative and metadata only.**
   - Path: `switchboard/.observatory/dispatch-proof.json`. dev-observatory view sources must be
     project-relative.
   - Schema: `switchboard.dispatch-proof.v1`.
   - Fields: `generated_at`, `registry_sha256`, the host CLI versions, Tier A results
     `{id, result, evidence}`, Tier B paths
     `{path, host, role, parent_model, requested, observed, result, receipt_ts}`, and an overall
     `verdict` of `PASS | FAIL | INCONCLUSIVE | NOT RUN | STALE`.
   - No message text. No absolute home paths: record transcript basenames only.
   - Default: gitignored and machine-local. The plan decides whether a sanitized copy is committed.
10. **Staleness.** The verdict reads `STALE` when `registry_sha256` differs from the current
    registry, when a recorded CLI version differs from the installed one, or when the record is
    older than the plan's window (proposal: 14 days). dev-observatory shows `STALE` as its own
    state, not as `PASS`.
11. **Contract.** Add the artifact (path, schema, fields, verdict enum) to
    `docs/observatory-contract.json` and `.md`. The producer owns it; the consumer pins it, as it
    pins `config.filename` today.
12. **Commands** (the plan settles names and flags):
    - an offline command (proposal: `python -m switchboard proof --offline`) that runs Tier A in a
      temporary home and writes the record;
    - a live command (proposal: `proof --live`) that runs the two headless paths itself (claude -p
      and codex exec, each in its own probe directory), prints the two interactive prompts to send
      in a fresh VS Code window, records their receipts by probe directory, and rewrites the record.
    - Both list in `CLAUDE.md` Key commands. The live one is a `confirm = true` launch verb in the
      observatory registry, because it writes the real home and spends tokens.
13. **No proxy claims.** A fixture-only or mocked result never sets a Tier B field. Scoring is
    the real artifact end to end (`.claude/rules/measurement-validity.md`): real receipts from
    real transcripts, assembled through switchboard's own `observe` and `inspect`.

## Lessons from 2026-11-09 to encode, not rediscover

- The project's pytest `addopts` already sets `-q`; adding another `-q` suppresses the summary
  line, and a count parser then reads nothing. Run the declared command.
- A Windows path built in a shell string (`"...\\$B\..."`) wrote files into a literal
  `build-step-runs$B` directory. Build paths in Python, not shell.
- `observe --latest` without a scope picks the newest subagent transcript anywhere in the home.
- Matching parent and child models would have hidden an ignored role file (requirement 3).
- Effort was recorded, never `UNKNOWN`, on all four paths with these CLI versions; a later run
  that sees `UNKNOWN` is a regression worth surfacing.

## Open questions the plan must close

1. Command shape: a `proof` subcommand, a script under `scripts/`, or a pytest marker for Tier A.
2. Whether a sanitized proof record is committed, or stays machine-local only.
3. Staleness window (14 days proposed) and whether a registry change invalidates only the changed
   roles or the whole record.
4. Coverage: one canary role per host per path (the mechanism is per host), plus a targeted
   re-proof of any role whose row changes. Or all 14 roles.
5. Whether Tier B may run its headless paths on a schedule (cost: two short host sessions), or
   only on demand.

## Not in this seed

- Changing any pin, and the R6/R7 migration steps.
- The dev-observatory reader and view (see the consumer seed).
