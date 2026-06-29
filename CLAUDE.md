# switchboard — CLAUDE.md

## Project overview

Local-LLM offload core ("less-token mode"): routes cheap **judge/grader** calls (style lens,
overnight grader, suggestion judge, …) to a local OpenAI-compatible model (`general-35b` via
llama-swap on `localhost:8080`, in WSL2) and **defers to Claude on any failure**. Authorship,
planning, and correctness gates always stay on Claude. The package is **stdlib-only, zero-dependency**
and **inert until a config is deployed** — every call site is disabled by default and `local_judge`
defers with no network call. Full detail in [`README.md`](README.md); plans live at
[`../docs/switchboard-offload-phase-b-plan.md`](../docs/switchboard-offload-phase-b-plan.md) and siblings.

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
# turn offload ON (operator switch: wakes WSL llama-swap, deploys config, holds endpoint warm; Ctrl-C tears down)
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\start-offload.ps1
# install a Desktop "Switchboard Offload" icon (one-time setup)
powershell -ExecutionPolicy Bypass -NoProfile -File scripts\install-offload-icon.ps1
# live smoke against a running endpoint on localhost:8080
uv run python -m switchboard
```

Offload-state inspection is `uv run python -m switchboard config` (JSON report + source; non-zero
exit on a broken config). It ships on `master` via the Phase 1.5 config-loader; this branch gains it
on the next `git merge master`.

## Gotchas

- `general-35b` is a **reasoning** model: `max_tokens` floor 600, default 800 — set **2000+** in the
  deployed config or the verdict truncates (`finish_reason: length`, `content: ""`). Read the verdict
  from `choices[0].message.content`; ignore `reasoning_content`.
- **Fail-safe by design**: a missing/malformed config or an unreadable prompt degrades to a Claude
  defer (exit 0), never a crash. Deleting `~/.switchboard/config.json` turns offload back off.
- `build-step-style` stays disabled — the local model is never a merge/correctness gate (Decision 3).
- Endpoint (`general-35b` via `llama-swap.service` on `:8080`) lives in WSL2, installed by
  void_furnace; needs a keep-alive for the localhost relay.

## Ports

- `localhost:8080` — the local model endpoint (client only; switchboard does not bind it).
  Intentionally shared with void_furnace (declared so the collision linter whitelists, not flags, it).
