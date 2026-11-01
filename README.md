# switchboard

Local-LLM offload core for Switchboard Phase 1. Routes cheap judgment calls (style lens,
overnight grader, ...) to a local OpenAI-compatible model (`coder-30b` via llama-swap on
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
  `enabled_call_sites` (`task_class -> bool | model`) map, the `effort` (`task_class -> tier`)
  map (config-only — a Claude-side dispatch hint switchboard validates + round-trips but does
  NOT act on; `local_judge` ignores it), the report-only `roles` pin table
  (`role -> {provider, model, tier, claim_id}`, every value nullable, null = no measured pin yet)
  with the `claims` map (`claim_id -> MEASURED|PARTIAL|ASSERTED|STALE`) a pin must cite, and
  endpoint/timeout/`max_tokens` defaults (validated at construction). `load_config()` resolves an operator config
  (explicit arg → `$SWITCHBOARD_CONFIG` → `~/.switchboard/config.json` → inert defaults) and
  `from_mapping()` rejects unknown keys with a clean `ConfigError` (see "Turning offload on/off").
- `switchboard/health.py` — `health()` / `is_warm()` / `warm_up()` reachability + warmth
  probes against `{base_url}/models`.
- `switchboard/metrics.py` — `Metrics`: in-process counter (total / verdicts / defers-by-
  reason) the validation harness reads to prove quota saved.
- `switchboard/cli.py` — the judge entrypoint skills invoke:
  `python -m switchboard judge --site <task_class> --prompt-file <path>` → one JSON object
  (verdict or defer) on stdout, always exit 0. Loads the operator config defer-safely (a broken
  config or unreadable prompt degrades to a defer, never a crash). Gated by config — returns a
  defer with no network call when offload is off or the site is disabled (inert by default).
  Also exposes `python -m switchboard config [--path PATH]` — the loud pre-flight that validates
  and prints the effective config + its source.
- `switchboard/harness.py` — `run_shadow(...)`: shadow-mode validation. Compares the local
  verdict against an expected (Claude) label, reports agreement + quota saved, and applies a
  kill criterion (revert if disagreement exceeds the threshold, default 0.20). `run_shadow_live.py`
  re-measures against the live endpoint.

## Operator surfaces

- `uv run python -m switchboard inspect --json` is the primary read surface. It reports the
  selected config source, inactive/active state, effective model and `effort` hint per configured
  site, plus one bounded endpoint probe. Endpoint reachability is not quality or certification
  evidence; `effort` is Claude-side metadata only and is not consumed by the local client.
- `uv run python -m switchboard inspect --roles --json` prints only the resolved role pin table
  (all ten roles, nulls for unpinned) and never probes the endpoint, so an external driver can
  read pins without importing this package. Pins are report-only: nothing in switchboard,
  including `local_judge`, dispatches by role. An unknown role, an unknown pin key, or a
  `claim_id` absent from `claims` makes the config invalid, reported as `config_state: invalid`.
- `uv run python -m switchboard config` is the loud validation pre-flight. It resolves and validates
  config without probing or starting the endpoint. Use `--path` before installing a candidate file.
- `uv run python -m switchboard bakeoff --suite suites\review-deep-style.json --output-dir _tmp`
  scores a frozen, recorded suite without network access. It writes `report.md`, `scores.jsonl`,
  and bounded versioned `bakeoff.json`; the latter is the observatory-consumable artifact. A recorded
  PASS is not live endpoint evidence, a caller-wiring claim, or permission to make the model a gate.
- `scripts\start-offload.ps1` only manages endpoint availability. Its `-Smoke` mode is
  non-destructive; the one-time icon installer remains convenience setup, not a dashboard action.

## Key contract points

- `max_tokens` defaults to **800** (floor 600) as generous headroom. The default model
  `coder-30b` (Qwen3-Coder-30B-A3B-Instruct) is **non-reasoning**, so a verdict needs few
  tokens; the 800/600 values are safe headroom retained from the general-35b era (a reasoning
  model that spent ~400–620 tokens on `reasoning_content` before the answer, truncating with
  `content: ""` / `finish_reason: "length"` under a small budget).
- Read the verdict from `choices[0].message.content`; **ignore `reasoning_content`** (only a
  reasoning model populates it).
- Timeouts: cold **540 s** (first call cold-loads), warm **60 s**.
- When `less_token_mode` is OFF (or the call site is not enabled), `local_judge`
  short-circuits to the defer sentinel **without** calling the endpoint.
- **One model** (`coder-30b`) for all slices — no model-swap routing (D2).

## Turning offload on/off

Offload is **OFF by default**: with no config present, every `judge` call defers to Claude and
behaviour is byte-identical to not having Switchboard wired at all. Turning it on is "drop a
file (or set an env var) + verify" — no code edit.

**Config resolution order** (first hit wins), implemented by `config.load_config()`:

1. an explicit `--path` (the `config` subcommand only) → source `arg:<path>`
2. `$env:SWITCHBOARD_CONFIG` — a per-shell override → source `env:<path>`
3. `~/.switchboard/config.json` (`$HOME\.switchboard\config.json` on Windows) — the global switch → source `home:<path>`
4. none of the above → inert defaults (offload off) → source `defaults`

### Turn it ON

> **Single-slice enablement (pending live certification):** to enable ONLY the `review-deep-style`
> slice (and explicitly keep `build-step-style` off), skip step 1 and use the committed
> [`scripts/offload-config.review-deep-style.json`](scripts/offload-config.review-deep-style.json)
> as the source in steps 2–3 — it is the review-deep-style-only enable config (`max_tokens: 2000`,
> the operator-verified general-35b-era ceiling, retained as safe headroom above the 800 default).
> Note: the bake-off behind
> this slice currently scores **hand-authored fixture** verdicts (see
> [`suites/review-deep-style.json`](suites/review-deep-style.json)); a B2b live capture (#237)
> replaces them with real `coder-30b` output before the slice is genuinely certified against the
> live model.

```powershell
# 1. Generate a config from your own skills (writes .\offload-scan-out\offload-config.json).
#    /offload-scan classifies each skill and emits only the local-safe judge/grader slices.

# 2. Validate it BEFORE installing (catches a bad shape early; exits non-zero if invalid):
uv run python -m switchboard config --path .\offload-scan-out\offload-config.json

# 3a. Install globally — copy to the home default:
New-Item -ItemType Directory -Force "$HOME\.switchboard" | Out-Null
Copy-Item .\offload-scan-out\offload-config.json "$HOME\.switchboard\config.json"

# 3b. ...OR point at it for this shell only (an env var overrides the home file):
$env:SWITCHBOARD_CONFIG = "$HOME\.switchboard\config.json"

# 4. Verify it is actually on (the loud pre-flight):
uv run python -m switchboard config
```

`config` prints the effective config as JSON: `source` (which file won), `offload_active`
(`true` when at least one site would offload right now), `less_token_mode` (the global
toggle), `enabled_sites`, and the endpoint knobs. If `offload_active` is `true`, offload is
live for those sites.

The **local endpoint must be up** (llama-swap serving `coder-30b` on `localhost:8080`) for a
judge to return a *verdict*; if it is down, judges *defer* (`reason_class: unreachable`) — still
safe, just no quota saved.

### The endpoint launcher (one-click)

`scripts/start-offload.ps1` is the retained endpoint-only launcher. It wakes WSL, starts
`llama-swap.service`, probes `:8080/v1/models`, and holds WSL warm while its foreground window is
open. On normal exit it stops the service it started. It never creates, copies, changes, or enables
the Switchboard config: the deployed config above remains the policy switch, so an endpoint with no
enabled certified site still causes judges to defer safely.

```powershell
# non-destructive prerequisite check; does not wake WSL, touch the service, or change config
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\start-offload.ps1 -Smoke

# run the endpoint launcher directly (Ctrl-C or closing the window releases the endpoint)
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\start-offload.ps1
```

For one-time desktop convenience only, install the shortcut below. It is not a dashboard action and
does not alter the policy config:

```powershell
# optional smoke; verifies the launcher is present and does not create a shortcut
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\install-offload-icon.ps1 -Smoke

# create or refresh the Desktop shortcut
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\install-offload-icon.ps1
```

### Turn it OFF

Any one of:

```powershell
Remove-Item "$HOME\.switchboard\config.json"   # remove the global switch
Remove-Item Env:\SWITCHBOARD_CONFIG            # drop the per-shell override
```

...or set `"less_token_mode": false` in the config file (keeps the file, disables all offload).
Re-run `uv run python -m switchboard config` to confirm `offload_active: false`.

### Defer-safety

A broken config **never** crashes a skill: the `judge` hot path catches the error, writes a
one-line warning to stderr, and emits a `config_error` defer to stdout (exit 0) so the skill
falls back to Claude. The `config` subcommand is the loud counterpart — it exits non-zero and
prints the validation error so you can fix it. `build-step-style` stays disabled even when a
config enables other sites (Switchboard Decision 3 — the local model never owns a gate).

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
