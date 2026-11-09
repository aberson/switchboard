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
  NOT act on; `local_judge` ignores it), and endpoint/timeout/`max_tokens` defaults (validated at
  construction). `load_config()` resolves an operator config
  (explicit arg → `$SWITCHBOARD_CONFIG` → `~/.switchboard/config.json` → inert defaults) and
  `from_mapping()` rejects unknown keys with a clean `ConfigError` (see "Turning offload on/off").
  The retired `roles` and `claims` keys are unknown keys: roles live in the registry below.
- `registry/models.json` + `switchboard/registry.py` — the committed model registry (schema v1):
  one row per role with, for each host (`claude`, `codex`), an exact model ID or `inherit` and an
  effort level or `inherit`, plus `description`, `read_only`, the cited measure-twice `claim_id`
  and an optional `evidence` note. `inherit` means no key is written, so the host resolves as it
  does today. `load_registry()` resolves `--registry <path>` → `$SWITCHBOARD_REGISTRY` → the
  committed file and never raises: a missing file is `absent`, a bad one `invalid`. Validation
  rejects bare aliases (`haiku|sonnet|opus|fable`) and any model without a digit, any model
  containing `fable` in any case (Fable is never pinned), unknown or missing roles and hosts,
  and an effort the row's host lacks (Claude rows use `ALLOWED_EFFORT_TIERS`; Codex rows use
  `ALLOWED_CODEX_EFFORT_TIERS`, the levels codex-cli 0.147.0 advertises). A model swap is a
  reviewed commit to this file.
- `switchboard/generate.py` — `apply`: renders each registry row into host-native role files
  (`<home>/.claude/agents/role-<role>.md`, `<home>/.codex/agents/role-<role>.toml`) under an
  ownership ledger (`<home>/.switchboard/generated.json`). See "Generating role files" below.
- `switchboard/observe.py` — `observe`: reads one native Claude or Codex transcript's model,
  effort and agent-type metadata and appends a requested-versus-observed receipt to
  `<home>/.switchboard/receipts.jsonl`; `inspect --roles` shows the latest one per role and host.
  See "Recording what ran" below.
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
- `uv run python -m switchboard inspect --roles --json` prints only the registry table
  (`schema_version` 3; one row per role with `claude` and `codex` `{model, effort}`, `claim_id`,
  `read_only`, `description` and `evidence`). It never reads config or probes the endpoint, so an
  external driver can read the table without importing this package. `--registry <path>` reads a
  candidate file. `registry_state` is `ok`, `absent` or `invalid` (with `error`), always exit 0.
  Row pins are requested values: nothing in switchboard, including `local_judge`, dispatches by
  role. Each row also carries `observed`, per host the last receipt `observe` recorded (or
  `unknown`), with `receipts_state`, `receipts_source` and `receipts_error` beside it (`--home
  <dir>` selects the receipts home). `inspect --json` carries the same rows plus
  `registry_state`, `registry_source` and `registry_error`.
- `uv run python -m switchboard config` is the loud validation pre-flight. It resolves and validates
  config without probing or starting the endpoint. Use `--path` before installing a candidate file.
- `uv run python -m switchboard bakeoff --suite suites\review-deep-style.json --output-dir _tmp`
  scores a frozen, recorded suite without network access. It writes `report.md`, `scores.jsonl`,
  and bounded versioned `bakeoff.json`; the latter is the observatory-consumable artifact. A recorded
  PASS is not live endpoint evidence, a caller-wiring claim, or permission to make the model a gate.
- `scripts\start-offload.ps1` only manages endpoint availability. Its `-Smoke` mode is
  non-destructive; the one-time icon installer remains convenience setup, not a dashboard action.
- `uv run python -m switchboard apply` previews, and `apply --write` writes, the role files the
  registry defines (next section).
- `uv run python -m switchboard observe --host claude|codex --latest` records which model and
  effort the newest role dispatch actually ran ("Recording what ran" below).

## Generating role files (`apply`)

```powershell
# preview: the per-file plan, nothing written
uv run python -m switchboard apply
# write: create or refresh the role files and record them in the ledger
uv run python -m switchboard apply --write
# also remove ledger-owned role files whose role left the registry
uv run python -m switchboard apply --prune --write
```

Options: `--home <dir>` (default: your home directory, `Path.home()`), `--registry <path>` (same
resolution as `inspect`: `--registry`, then `$SWITCHBOARD_REGISTRY`, then the committed file) and
`--catalog <spawn-sites.json>` (coverage advisories, below).

**What is written.** For every registry row, on both hosts:

- `<home>/.claude/agents/role-<role>.md`: YAML frontmatter `name: "role-<role>"`, `description`,
  `model` and `effort`, then a one-to-two sentence role prompt. A `read_only` row adds
  `disallowedTools: Agent, Edit, Write, NotebookEdit` and `omitClaudeMd: true`.
- `<home>/.codex/agents/role-<role>.toml`: `name`, `description`, `developer_instructions` (the
  same role prompt), `model` and `model_reasoning_effort`. Codex agents cannot override
  permissions, so a `read_only` row adds a read-only sentence to `developer_instructions`.

`inherit` writes no key, so that host resolves exactly as it does today. Every file starts with
the same provenance comment (`# generated by switchboard apply ...`) and holds nothing
run-specific, so an unchanged registry produces byte-identical files. Values are written as
double-quoted strings using only the `\\`, `\"` and `\uXXXX` escapes, so a description with `:`,
quotes or `#` reads back unchanged in both YAML and TOML.

**The plan.** Every run prints one line per target: `create` (absent), `update` (owned and
changed), `unchanged`, or `refuse` (left untouched, with the reason). A ledger-owned file whose
role left the registry shows as `orphan`; with `--prune` it becomes `delete` (or `refuse` if it
was hand-edited, or `forget` if it is already gone, which drops its ledger entry). A bare run,
and `--prune` without `--write`, writes nothing. A role leaves the registry only when it is
removed from both `ALLOWED_ROLES` and `models.json`, because the registry must define every
allowed role.

**Ownership (never acts on a file it cannot prove it wrote).** `--write` records each file it
writes in `<home>/.switchboard/generated.json`:

```json
{"schema_version": 1, "files": {".claude/agents/role-reviewer.md": {"sha256": "...", "role": "reviewer", "host": "claude"}}}
```

Keys are home-relative paths and must equal the generated path of the entry's role and host.
A file is updated or pruned only when it has a ledger entry and its current bytes hash to that
entry, re-checked just before the write or delete. Everything else is refused and left
untouched: a foreign file (even one carrying the provenance comment, or byte-identical to the
generated content), a hand edit, a symlink, or a directory. A missing ledger, or a corrupt one
(any schema or path defect), means no existing file is provably switchboard's, so every existing
target is refused. On the next `--write` that changes something, a corrupt ledger is kept beside
the new one as `generated.json.corrupt-<hash>`. To let `apply` regenerate a refused file, move
it away by hand.

Writes are atomic: the content is staged in a temp file in the target directory, then renamed
into place. A create never replaces a file that appeared after the plan was made, and the
ledger itself is replaced atomically, once per run and only when its entries changed. Hosts may
not see the first file in a new agents directory until restarted; `apply` says when it creates
one.

**Exit codes.** `0`: the plan was computed (and, with `--write`, carried out); refusals are
reported plan lines, not errors. `1`: a write, delete or ledger update failed (stderr says
which). `2`: the registry is missing or invalid (or a value cannot be written as UTF-8), or
`--home` is not a directory. Exit 2 prints exactly one advisory line and writes nothing, so the
last-generated files stay byte-identical.

**Advisory lines** (stderr, each prefixed `switchboard apply: `, never errors):

- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` or `CLAUDE_CODE_EFFORT_LEVEL` is set to a non-empty value:
  it defeats the generated per-agent `model` or `effort`. `CLAUDE_CODE_SUBAGENT_MODEL` is set:
  Claude roles whose model is `inherit` get that model instead of the session's.
- A same-named project agent exists: any `*.md` under `.claude/agents` whose file name or
  frontmatter `name` is `role-<role>`, in the current directory or a parent up to its git root
  (only the current directory when there is no git root). A project agent beats the user-level
  one. The user-level directory under `--home` is never treated as a project directory.
- With `--catalog`, one line per catalog role that has no registry row (a dispatch by it falls
  back to the default agent, `role_missing`). The catalog is skill-mesh's
  `config/spawn-sites.json`, read as `{"schema_version": 1, "sites": {"<site-id>": "<role>" |
  "inherit"}}`; `inherit` sites need no row and other top-level keys are ignored. A missing or
  malformed catalog is one advisory line, never a crash.

`apply` writes role definitions only. Whether a host dispatch honors them is proven live
(Step R5), not by these tests.

## Recording what ran (`observe`)

```powershell
# after a dispatch by role: record the newest subagent transcript's model and effort
uv run python -m switchboard observe --host claude --latest
uv run python -m switchboard observe --host codex --latest
# only sessions started in one directory, or one named transcript
uv run python -m switchboard observe --host claude --latest --project-dir <project-dir>
uv run python -m switchboard observe --host claude --transcript <agent-transcript.jsonl>
# each role's latest observed value beside its requested pin
uv run python -m switchboard inspect --roles
```

Options: `--home <dir>` (default: your home directory; it holds `.claude`, `.codex` and
`.switchboard`) and `--registry <path>` (same resolution as `inspect`). Each run reads one
native transcript and appends one line to the private `<home>/.switchboard/receipts.jsonl`:

```json
{"ts": "2026-11-08T12:00:00.000000Z", "host": "claude", "role": "reviewer", "agent_type": "role-reviewer", "requested_model": "claude-sonnet-5-5", "requested_effort": "inherit", "observed_model": "claude-sonnet-5-5", "observed_effort": "medium", "source_locator": "C:\\...\\subagents\\agent-<id>.jsonl", "registry_sha256": "<sha256 of the registry bytes>"}
```

- **Metadata only.** Claude: the `"type": "assistant"` lines' `message.model`, `effort` and
  `attributionAgent` (the agent type). Codex: the thread's own `session_meta`
  (`payload.source.subagent.thread_spawn.agent_role`, and `payload.subagent_history_start_ordinal`,
  before which a fork's lines are inherited parent history and are not counted) and its own
  `turn_context` lines' `payload.model` and `payload.effort`. No message content is read into a
  receipt or printed. The names were captured from real transcripts (Claude Code 2.1.318, Codex
  CLI 0.155.0-alpha.16.3); the `switchboard/observe.py` docstring records which. The test
  fixtures (`tests/fixtures/observe/`) use the same names with synthetic content.
- **No guessing.** `role` is `<role>` only when the host recorded the agent type `role-<role>`
  and the registry has that row. No agent type, several, or one that is not a role agent (such
  as `general-purpose`) gives `"role": "unattributed"` with `requested_*` null; the receipt is
  still written, keeps what the host recorded in `agent_type`, and never joins a row.
- **Values.** `observed_effort` is `UNKNOWN` when the transcript records no effort. Several
  distinct models (or efforts) are all kept, joined by `|`, so a mixed run never reads as a
  match. `<synthetic>` (host-made) messages are skipped. A transcript with no model metadata
  writes nothing.
- **`--latest`** reads the most recently modified subagent transcript (a main session is never
  picked): Claude `<home>/.claude/projects/<project>/<session>/subagents/**/agent-*.jsonl`
  (`--project-dir` selects that directory's project folder: every character other than an ASCII
  letter or digit becomes `-`), Codex `<home>/.codex/sessions/**/rollout-*.jsonl` whose own
  `session_meta` is a spawned subagent (`--project-dir` matches its `cwd`).
- **Display.** `observe` prints the requested and observed values, then per value `match`,
  `MISMATCH (requested X, observed Y)`, `inherit` (the row requests inherit; nothing to compare)
  or `unknown`. `inspect --roles` prints, under each role, its last receipt per host compared
  with the CURRENT row, plus one `MISMATCH <host> <model|effort>: requested X, observed Y` line
  per mismatch. With `--json`, each row's `observed` is `{"claude": ..., "codex": ...}`, each
  `{model, effort, model_status, effort_status, ts, source_locator}` or `"unknown"`, and
  `receipts_state` is `absent`, `ok` or `invalid` (malformed lines are skipped and counted in
  `receipts_error`). In the text views a character the console cannot encode (a non-Latin path
  on a cp1252 console, say) is printed as a backslash escape rather than failing.
- **Exit codes.** `0`: the receipt was appended (an unattributed one included). `1`: the append
  failed. `2`: the registry is not `ok`, `--home` is not a directory, or no readable transcript
  with model metadata was found; nothing is written and exactly one advisory line (prefixed
  `switchboard observe: `) is printed. `--project-dir` without `--latest` is a usage error.

`observe` only reads transcripts the hosts already wrote. Live dispatches are proven by Step R5.

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
