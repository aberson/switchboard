# switchboard

Local-LLM offload core for Switchboard Phase 1. Routes cheap judgment calls (style lens,
overnight grader, ...) to a local OpenAI-compatible model (`general-35b` via llama-swap on
`localhost:8080`) and **defers to Claude on any failure**.

Built to the D1 contract pinned in
[`docs/investigations/switchboard-spike.md`](../docs/investigations/switchboard-spike.md)
(issue #203). The throwaway spike prototype
(`scripts/switchboard_spike_local_judge.py`) is replaced by this package.

## Modules

- `switchboard/client.py` — `local_judge(...)`: sync, stdlib-only (`urllib`). Returns a
  validated `Verdict` (`{"verdict": "pass"|"flag", "reason": str, ...}`) or a `Defer`
  sentinel (`{"defer": True, "reason": ..., "reason_class": ...}`) on any of the 7
  documented failure conditions.
- `switchboard/config.py` — `SwitchboardConfig`: the `less_token_mode` global toggle, the
  `enabled_call_sites` (`task_class -> bool | model`) map, and endpoint/timeout/`max_tokens`
  defaults (validated at construction).
- `switchboard/health.py` — `health()` / `is_warm()` / `warm_up()` reachability + warmth
  probes against `{base_url}/models`.
- `switchboard/metrics.py` — `Metrics`: in-process counter (total / verdicts / defers-by-
  reason) the Step 4 validation harness reads to prove quota saved.

## Key contract points

- `max_tokens` defaults to **800** (floor 600): `general-35b` is a reasoning model that
  spends ~400–620 tokens on `reasoning_content` before the answer lands in `content`. A
  small budget truncates with `content: ""` and `finish_reason: "length"`.
- Read the verdict from `choices[0].message.content`; **ignore `reasoning_content`**.
- Timeouts: cold **540 s** (first call cold-loads), warm **60 s**.
- When `less_token_mode` is OFF (or the call site is not enabled), `local_judge`
  short-circuits to the defer sentinel **without** calling the endpoint.
- **One model** (`general-35b`) for all slices — no model-swap routing (D2).

## Dev

```
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict switchboard
uv run pytest -q
```

Optional live smoke (requires a running endpoint on `localhost:8080`):

```
uv run python -m switchboard
```
