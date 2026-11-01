# switchboard — CLAUDE.md

## Project overview

Local-LLM offload core ("less-token mode"): routes cheap **judge/grader** calls (style lens,
overnight grader, suggestion judge, …) to a local OpenAI-compatible model (`coder-30b` via
llama-swap on `localhost:8080`, in WSL2) and **defers to Claude on any failure**. Authorship,
planning, and correctness gates always stay on Claude. The package is **stdlib-only, zero-dependency**
and **inert until a config is deployed** — every call site is disabled by default and `local_judge`
defers with no network call. Full detail in [`README.md`](README.md); plans live at
[`../docs/switchboard-offload-phase-b-plan.md`](docs/plans/master_plan.md) and siblings.

## Stack

- Python ≥3.12 + uv. **Zero runtime dependencies** (`dependencies = []`, stdlib `urllib` only) — keep it that way.
- Package at `switchboard/` (NOT `src/`). Tests under `tests/`. ruff + mypy --strict.

## Key commands

```powershell
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict switchboard
# primary read surface: config, per-site effective model, and bounded endpoint probe
uv run python -m switchboard inspect --json
# report-only role pin table (role -> provider/model/tier/claim_id); no endpoint probe
uv run python -m switchboard inspect --roles --json
# config-only validation (does not launch or probe the endpoint)
uv run python -m switchboard config
# deterministic recorded evidence; writes report.md, scores.jsonl, and bakeoff.json
uv run python -m switchboard bakeoff --suite suites\review-deep-style.json --output-dir _tmp
# make the local endpoint available; this never deploys or enables offload config
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\start-offload.ps1
# non-destructive launcher prerequisite smoke (no WSL/service/config changes)
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\start-offload.ps1 -Smoke
# install a Desktop "Switchboard Offload" icon (one-time setup)
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\install-offload-icon.ps1
# non-destructive installer prerequisite smoke (does not create a Desktop shortcut)
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\install-offload-icon.ps1 -Smoke
# live smoke against a running endpoint on localhost:8080
uv run python -m switchboard
```

Offload-state inspection is `uv run python -m switchboard config` (JSON report + source; non-zero
exit on a broken config). The config is the only offload policy switch; the launcher only manages
endpoint availability.

## Gotchas

- `coder-30b` (Qwen3-Coder-30B-A3B-Instruct) is a **non-reasoning** model, so a verdict needs few
  tokens; `max_tokens` keeps a 600 floor / 800 default as safe headroom (raise a slice only if it
  truncates: `finish_reason: length`, `content: ""`). Read the verdict from
  `choices[0].message.content`; ignore `reasoning_content` (only a reasoning model like the former
  `general-35b` default populates it).
- **Fail-safe by design**: a missing/malformed config or an unreadable prompt degrades to a Claude
  defer (exit 0), never a crash. Deleting `~/.switchboard/config.json` turns offload back off.
- `build-step-style` stays disabled — the local model is never a merge/correctness gate (Decision 3).
- Endpoint (`coder-30b` via `llama-swap.service` on `:8080`) lives in WSL2, installed by
  void_furnace; needs a keep-alive for the localhost relay.

## Ports

- `localhost:8080` — the local model endpoint (client only; switchboard does not bind it).
  Intentionally shared with void_furnace (declared so the collision linter whitelists, not flags, it).
