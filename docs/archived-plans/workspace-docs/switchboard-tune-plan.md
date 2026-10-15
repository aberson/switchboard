# switchboard-tune — fine-tune a local judge, honestly measured

**Status:** PLANNED (authored 2026-07-28)
**Project:** switchboard (in-coding-root; repo toplevel is `<coding-root>`, no nested `.git`)
**Plan family:** sibling of `switchboard-plan.md` (master, terminal), `switchboard-offload-phase-b-plan.md`, `switchboard-config-loader-plan.md`
**Step numbering:** restarts at 1, matching this corpus's per-file convention (every sub-plan restarts; there is no global sequence). Issue numbers are the real collision surface — `/repo-sync` assigns them.

---

## 1. What This Feature Does

**Proposal:** https://claude.ai/code/artifact/b9d47fc6-e134-4854-9b38-de2d205506c7 (operator-facing view of this plan; see the Decision Inventory appendix for the P/D handles it exposes)

Fine-tunes a small open-weight model (QLoRA on Qwen2.5-1.5B-Instruct) to serve as the local judge that
switchboard already routes `review-deep-style` calls to, distilled from Claude verdicts, and measures
honestly whether fine-tuning beat prompting at that scale.

It is being built to close a specific, named gap — "have integrated and fine-tuned LLMs" appears in two
target job descriptions — with a small, verifiable artifact rather than a tutorial. The shape matters:
switchboard is a real system that already routes judge calls to a local model and already has a
kill-switch that disables a slice when it disagrees with the reference too often. Making the local judge
*better* is that system's natural next phase, so every number this project produces (dataset size,
golden-set size, before/after agreement rates) is grounded in a deployed pipeline rather than a notebook.

**The deliverable is an honest eval delta, not a win.** "Prompting beat fine-tuning at this scale, and
here is the eval that shows it" is an accepted, publishable outcome of this plan. No step is allowed to
be written or reworked in order to produce a positive number.

---

## 2. Existing Context

What a fresh model needs to know about switchboard before building here. Every claim below was read from
the producing file, not from docs.

**The routing core.** `switchboard/client.py` exposes `local_judge(prompt, *, config, cold, timeout,
task_class, metrics) -> JudgeResult`, where `JudgeResult = Verdict | Defer` and both are `TypedDict`s (not
dataclasses). A `Verdict` is `{"verdict": "pass"|"flag", "reason": str, "_raw": str, "_elapsed_s": float}`.
Deferral to Claude is represented by a dict literally carrying `"defer": True` — there is no `None` and no
enum. The discrimination idiom, used by `harness._verdict_of`, is `result.get("defer") is True`. The judge
posts to `{base_url}/chat/completions` and reads the verdict **only** from `choices[0].message.content`;
`reasoning_content` is ignored, because the deployed model is non-reasoning.

**The prompt is a single source of truth.** `SYSTEM_PROMPT` is defined at `switchboard/client.py:28` and
has exactly two references in the entire tree — its definition and its use at line 202 (grep verified).
This project becomes its first external consumer and **must import it, never copy it**.

**Config and slices.** `switchboard/config.py` holds a frozen `SwitchboardConfig` whose JSON keys equal its
field names: `less_token_mode` (bool, default `True`), `enabled_call_sites` (dict), `effort` (dict),
`base_url` (default `"http://localhost:8080/v1"`), `model` (default `"coder-30b"`), `cold_timeout_s`
(540.0), `warm_timeout_s` (60.0), `max_tokens` (800, with a hard `MIN_MAX_TOKENS = 600` floor). A **slice**
is a `task_class` string key inside `enabled_call_sites`; its value is `true` (on), `false` (off), or a
model-name string (on, with a per-slice model pin). Unknown slices are disabled by default. `base_url`,
`max_tokens`, and the timeouts are global only. `load_config()` resolves arg → `$SWITCHBOARD_CONFIG` →
`~/.switchboard/config.json` → defaults, returning a source label.

**Eval plumbing that already exists.** `switchboard/harness.py` defines `ShadowCase(prompt, expected,
label, cold)` and `run_shadow(cases, *, config, kill_threshold=0.20, task_class, metrics) -> ShadowReport`.
The aggregation rule is load-bearing and must be reused, not re-derived: **defers are excluded from the
denominator**, and a slice is killed iff `disagreement_rate` is *strictly* greater than the threshold, so a
run with zero verdicts can never kill. `switchboard/bakeoff.py` loads suite JSON with top-level keys
`slice`, `reference_runner`, `kill_threshold`, `cases`, `recorded`; each case carries `label`, `expected`,
`prompt`. `switchboard/certify.py` turns a report into a `CertVerdict`. The CLI surface is three
subcommands: `judge`, `bakeoff`, `config`.

**The kill-switch.** `switchboard/monitor.py` performs a surgical raw-JSON edit setting
`enabled_call_sites[task_class] = false` on the deployed config, byte-preserving every other key, then
re-validating and atomically replacing. It is currently **unwired** — no CLI, no daemon.

**Tests.** 183 tests across 11 files plus `conftest.py`, entirely network-free. `tests/conftest.py`
supplies `patch_client` / `patch_health` fixtures that monkeypatch `urllib.request.urlopen` with
`make_json_urlopen` / `make_raw_urlopen` / `make_raising_urlopen`, plus a `chat_envelope(...)` builder and
`PASS_CONTENT` / `FLAG_CONTENT` / `TRUNCATED_ENVELOPE` constants. New work must not perturb this suite.

**The data situation, verified.** switchboard persists **no** judge calls. `metrics.py` is in-memory by
design; `client.local_judge` and `monitor.py` never log; the only disk writer is `cmd_bakeoff` →
`_tmp/scores.jsonl`, which has never been run and whose rows carry no prompt text, so they are not
fine-tunable even in principle. Shadow mode is **one-sided**: `run_shadow` executes the local model against
a static operator-supplied `expected` label, and `harness.py` states outright that it does not call Claude.
`~/.switchboard/` exists but contains only a 179-byte `config.json`. Real labelled pairs in the repo total
about 20 — eight cases each in `suites/review-deep-style.json` and `suites/effort-vs-model.json`, plus four
inline `ShadowCase`s in `run_shadow_live.py`. `suites/review-deep-style.json` self-declares
`"HAND-AUTHORED FIXTURE, NOT YET LIVE-MEASURED"`.

**Therefore the dataset must be minted, not harvested.** That is the single biggest scope fact in this
plan and the reason Step 1 and Step 2 exist at all.

**Documentation drift this plan resolves.** `README.md` and `switchboard/CLAUDE.md` correctly name the
deployed endpoint model as `coder-30b` (Qwen3-Coder-30B-A3B-Instruct, non-reasoning, llama-swap on
`localhost:8080` in WSL2). `switchboard-offload-phase-b-plan.md` Step 3 and `switchboard-config-loader-plan.md`
Step 5 still say `general-35b` (a reasoning model needing `max_tokens >= 2000`). **This plan names
`coder-30b` throughout and supersedes those two stale references.**

**Hardware, measured on this machine.** NVIDIA RTX 4070 Laptop GPU with **8188 MiB VRAM** (compute 8.9),
Intel Core Ultra 7 155H (16 cores / 22 threads), **15.5 GB system RAM**. WSL2 Ubuntu has working CUDA
passthrough (`nvidia-smi` resolves inside WSL), Python 3.12.3, and `uv` at `~/.local/bin/uv`;
`llama-swap.service` is active. The 8 GB VRAM ceiling is the binding constraint on model size.

---

## 3. Scope

### In scope

- A new sibling project `switchboard-tune/` with its own `pyproject.toml` carrying the training stack.
- Mining realistic judge inputs from real workspace git history.
- Minting teacher labels with Claude via the `claude -p` subprocess seam.
- Freezing a hash-pinned golden set **before** any training run.
- An eval harness that imports switchboard's production prompt and parser, with calibration anchors.
- A prompted baseline measurement of the untuned student.
- A QLoRA SFT run with prompt-loss masking and dev-split checkpoint selection.
- A post-training eval and a written comparison, including the negative-result path.
- Merge → GGUF → llama-swap → certify through `python -m switchboard bakeoff` against the real endpoint.
- An optional DPO stretch, gated on whether usable preference pairs actually materialize.

### Explicitly out of scope

- **Any change to switchboard's runtime dependencies.** `dependencies = []` in
  `switchboard/pyproject.toml` is invariant. Phase B states it as: "switchboard is zero-dependency by
  design... Any new code in switchboard must preserve this." torch, transformers, peft, trl, and datasets
  never enter that file, in any extra.
- **Relaxing Decision 3.** The master plan states "The local model is NEVER on the correctness gate...
  Local = advisory pre-filter only; Claude makes every gate/merge decision." A better-tuned judge does not
  change this. `build-step-style` stays `false`.
- **Enabling any slice by default.** No-config remains inert.
- Frontier scale, RLHF, multi-GPU, training from scratch, vLLM serving, quantization research.
- Closing issue #237. This plan *feeds* it — Step 2 produces the labeled corpus a live-capture suite can
  draw from — but #237 needs a live `coder-30b` capture run, which is its own operator step. Reference, do
  not duplicate.
- Wiring `monitor.py` into a daemon. It stays unwired here.
- Replacing `coder-30b` as the deployed judge. The tuned 1.5B is evaluated as a *candidate*; it ships only
  if it clears the existing kill rule, and even then only for `review-deep-style`.

---

## 4. Impact Analysis

The headline: **this feature adds zero lines to the `switchboard/` package.** switchboard is imported and
read; it is not modified. That is what protects the zero-dependency invariant.

| File | Change Type | Reason | Verified |
|---|---|---|---|
| `switchboard/switchboard/client.py` | **read-only import** | `switchboard-tune` imports `SYSTEM_PROMPT` and the verdict parser so the dataset and eval use the production prompt verbatim | grep `SYSTEM_PROMPT` across `switchboard/` → exactly 2 sites, both in `client.py` (def line 28, use line 202). No other consumer exists; this project becomes the first external one. |
| `switchboard/switchboard/harness.py` | **read-only import** | reuse `ShadowCase` + `aggregate_agreement` rather than re-deriving the "defers excluded from denominator, strict `>` kill" rule | read: `run_shadow` + `aggregate_agreement` signatures confirmed; `_verdict_of` is the defer-discrimination idiom to copy |
| `switchboard/switchboard/config.py` | **read-only import** | eval harness loads real config via `load_config()` rather than hand-building a base_url | read: field list + `load_config` resolution order confirmed (arg → env → home → defaults) |
| `switchboard/pyproject.toml` | **unchanged (asserted)** | `dependencies = []` must stay empty; Step 3 adds a test that fails if it ever isn't | read line 7: `dependencies = []`; optional-deps currently only `dev = [pytest, ruff, mypy]` |
| `switchboard/suites/review-deep-style.json` | **modify (Step 8 only)** | its `recorded` block is a hand-authored fixture; a live capture may add a `student-tuned` runner column | read: top-level keys `note`/`slice`/`reference_runner`/`kill_threshold`/`cases`/`recorded`; runners currently `opus`/`local`/`weak`; loader requires runner labels to cover case labels exactly |
| `switchboard/tests/*` | **unchanged (regression guard)** | all 183 tests must still pass untouched; a diff here is a smell | counted: 11 test files + conftest, 183 collected |
| `~/.switchboard/config.json` | **deployment artifact, Step 8** | slice enablement is a deployed-config edit, not a repo edit | verified on disk: exists, 179 bytes, config-only, no metrics/log dir |
| `dev/.claude/observatory/registry.toml` | **extend** | register `switchboard-tune` as an owned project so observatory can see it | read: `switchboard` present with `slug`/`path`/`owned=true`; unregistered projects default to `owned=false` and are write-blocked |
| `docs/switchboard-offload-phase-b-plan.md` | **annotate** | its Step 3 says `general-35b`; add a one-line correction pointing here | recon-confirmed drift vs README/CLAUDE.md `coder-30b` |
| `docs/switchboard-config-loader-plan.md` | **annotate** | same `general-35b` drift at its Step 5 | recon-confirmed |

**Shared-constant call-site audit** (per the grep-all-downstream rule). Two shared values cross a producer/
consumer boundary in this work:

1. `SYSTEM_PROMPT` — 2 sites, both in `client.py`. `switchboard-tune` must `from switchboard.client import
   SYSTEM_PROMPT`. Step 3 adds a test asserting **identity** (`is`), not equality, so a future copy-paste
   duplication fails CI.
2. The slice name `"review-deep-style"` — appears in `switchboard/bakeoff.py`, `cli.py`, `harness.py`,
   `monitor.py`, `suites/review-deep-style.json`, `README.md`, six test files, plus
   `.claude/observatory/registry.toml`, three skill cores, and `offload-scan-out/offload-config.json`. This
   plan **reads** that string and never redefines it; the suite file remains its on-disk anchor.

---

## 5. New Components

All new code lives in a **new sibling project**, `<coding-root>\switchboard-tune\`.

| Path | What it is |
|---|---|
| `switchboard-tune/pyproject.toml` | uv project, `requires-python = ">=3.12"`, deps: torch (CUDA), transformers, peft, trl, datasets, accelerate, bitsandbytes. Installs `switchboard` as an editable path dep for prompt/parser reuse. |
| `switchboard-tune/tune/mine_inputs.py` | Walks real git history across `dev/` repos, extracts small diff hunks, renders each through the production prompt shape, dedups, writes `data/inputs.jsonl` with source repo + sha provenance. |
| `switchboard-tune/tune/label.py` | Batch teacher-labeling via the `claude -p` subprocess seam. Writes `data/labeled.jsonl`. Resumable, idempotent, one row per input. |
| `switchboard-tune/tune/freeze.py` | Deterministic 80/10/10 split + SHA256 manifest. Writes `data/golden/{train,dev,test}.jsonl` + `data/golden/MANIFEST.sha256`. Refuses to overwrite an existing frozen manifest. |
| `switchboard-tune/tune/evalharness.py` | Scores any runner against the frozen test split. Imports `SYSTEM_PROMPT` and the verdict parser from switchboard. Runners: `claude`, `always-pass`, `student-prompted`, `student-tuned`, `coder-30b`. |
| `switchboard-tune/tune/train_sft.py` | QLoRA SFT via `trl.SFTTrainer` with prompt-loss masking, dev-split checkpoint selection, bounded `max_steps`. |
| `switchboard-tune/tune/export.py` | Merge adapter into base, convert to GGUF via llama.cpp's `convert_hf_to_gguf.py`, quantize. |
| `switchboard-tune/tune/ship.py` | Place the GGUF into llama-swap's model dir + config, then invoke `python -m switchboard bakeoff` and surface the certify verdict. |
| `switchboard-tune/tune/dpo.py` | Optional. Builds preference pairs from student-wrong cases and runs a DPO pass. |
| `switchboard-tune/results/` | `baseline.json`, `tuned.json`, `comparison.md` — the honest write-up. |
| `switchboard-tune/README.md` | Reproduction instructions, including that this runs in WSL2 and why. |

### Toolchain and first-run

`switchboard-tune` runs **inside WSL2 Ubuntu**, not on Windows, because training needs CUDA. All commands
below are given in the PowerShell-runnable `wsl -- bash -lc` form, since the operator is always at a
PowerShell prompt. Step 1 must establish every one of these and record them in the project's `CLAUDE.md`
under a scrapable `## Commands` block, so dev-observatory derives launch verbs rather than needing them
hand-curated.

| Verb | Command |
|---|---|
| install | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv sync --extra cuda"` |
| test | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run pytest -q"` |
| lint | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run ruff check ."` |
| typecheck | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run mypy tune"` |
| smoke | `wsl -- bash -lc "cd <coding-root>/switchboard-tune && ~/.local/bin/uv run python -m tune.smoke"` |

**System prerequisites**, all verified present on this machine except where noted:

- WSL2 Ubuntu with CUDA passthrough — verified (`nvidia-smi` resolves inside WSL and reports the 4070).
- Python 3.12.3 and `uv` at `~/.local/bin/uv` inside WSL — verified.
- `llama-swap.service` active — verified.
- **llama.cpp checkout with `convert_hf_to_gguf.py` — NOT yet verified.** Step 4's smoke gate must locate
  it and record the path and revision in the README, or clone and pin one. This is the most likely
  first-run blocker.
- Claude CLI authenticated for the `claude -p` seam. Prefer `CLAUDE_CODE_OAUTH_TOKEN` (subscription OAuth)
  over an API key. Step 2 must fail loudly with a clear message if the seam is unauthenticated rather than
  silently producing zero labels — an empty label batch that exits 0 would poison every downstream step.
- No secret is read, written, or logged by any step in this plan. The teacher seam authenticates from the
  operator's existing environment; no key material enters the repo or the dataset.

---

## 6. Design Decisions

**D1 — Student is `Qwen/Qwen2.5-1.5B-Instruct` (exact Hugging Face repo id, ungated — no HF token
required), trained with QLoRA (4-bit), not LoRA.** 8188 MiB of VRAM is the
binding constraint. A 4-bit 1.5B base leaves comfortable headroom for optimizer state, activations, and a
1024-token sequence length on a laptop GPU that is also driving a display. A 3B would fit but leave no room
for the eval loop to run alongside; a 7B risks OOM given only 15.5 GB of system RAM to spill into.
*Alternative considered:* full LoRA in fp16 on a 1.5B — fits, but QLoRA is the technique worth being able
to speak to, and the memory headroom buys a larger effective batch via gradient accumulation.

**D2 — The comparison is student-versus-itself, and this is the honesty anchor.** Baseline is
Qwen2.5-1.5B-Instruct *prompted* with the production `SYSTEM_PROMPT`. Treatment is the same model after
QLoRA SFT. Both are scored on the identical frozen test split. The deployed `coder-30b` is reported as a
**reference column only** — a 1.5B beating a 30B MoE would be a surprising result, and beating it is
explicitly not the claim. Conflating "tuned 1.5B vs 30B" with "tuning helped" is the exact measurement
error this decision exists to prevent.

**Pre-registered claim, fixed before any number is produced:** *On a frozen golden set of
`review-deep-style` judgments labeled by Claude, does QLoRA SFT raise Qwen2.5-1.5B-Instruct's **strict**
agreement-with-Claude (per D10 — agreements over all cases, a defer counting as a miss) above its own
prompted baseline measured on the same runtime and quantization, and by how many percentage points?* Scope
of the claim is exactly that slice, that model, that golden set — it is not a claim about fine-tuning in
general.

**D3 — Teacher labels come from Claude via the `claude -p` subprocess seam.** That is the established
workspace pattern and needs no API key (a consumer subscription is not API access). The seam is hardened
per known workspace failure modes: pass `--model` explicitly so the subprocess does not inherit a
power-user global config; disable tools; parse tolerantly; pass long prompts via **stdin** rather than argv
(argv over 32K raises WinError 206 on Windows); and decode with `encoding="utf-8", errors="replace"` (a
non-cp1252 byte otherwise raises inside the reader thread, silently yielding `stdout=None`).
*Alternative considered:* the Anthropic API — cleaner batching, but requires a key this machine has not
been verified to hold.

**D4 — Inputs are mined from real workspace git history, not synthesized.** The judge's real input
distribution is small code-style diff hunks, and `dev/` contains years of them across many repos. Mining
gives 1,000+ realistic inputs cheaply and grounds the eval in the distribution the deployed judge actually
sees. *Alternative considered and rejected:* having Claude synthesize the inputs as well as the labels.
That collapses the distribution toward what the teacher finds easy to imagine and inflates measured
agreement — the student would be scored on the teacher's own imagination rather than on real diffs.

**D5 — Training code lives in a new sibling project, never inside `switchboard/`.** Two independent reasons,
either of which is sufficient. First, the zero-dependency invariant: torch and friends can never appear in
`switchboard/pyproject.toml`, and putting them behind an optional extra still invites an accidental import
into the shipped package. Second, the environments genuinely differ — training needs CUDA and therefore
runs in WSL2, while switchboard is developed and tested on Windows. `switchboard-tune` installs switchboard
as an editable path dependency so it reuses the production prompt and parser rather than re-implementing
them.

**D6 — The golden set is frozen before any training, with calibration anchors.** `freeze.py` writes a
SHA256 manifest and refuses to overwrite it; the eval harness verifies the manifest on every run and
**aborts** on mismatch rather than warning. Before any student number is trusted, the harness must clear a
calibration gate: a known-good runner (Claude re-scoring the test set) and a known-garbage runner (a
constant `always-pass`) must bracket the metric by a wide margin. A metric that cannot separate those two
is not measuring what it claims. The harness also aborts — never silently falls back — if the production
prompt or config cannot be loaded.

**D7 — Shipping is certification, not assertion.** A tuned model reaches the router only by clearing
`python -m switchboard bakeoff` against the real endpoint under the existing 0.20 strict-greater-than
disagreement kill rule, with defers excluded from the denominator. If it does not clear, it does not ship,
and the write-up says so. The slice stays `review-deep-style` only.

**D8 — DPO is genuinely optional and predicate-gated.** It runs only if SFT leaves enough
student-wrong-versus-Claude-right cases to build meaningful preference pairs. A `Type: conditional` step
with a real shell predicate keeps `/build-phase` from running a training pass over an empty pair set.

**D9 — Negative results ship.** If the tuned model loses to the prompted baseline, Step 7 still produces
`comparison.md` with the real numbers and the interpretation. No step may be rerun with different settings
in order to find a better number; if settings change, that is a new run recorded alongside the first, not a
replacement for it.

**D10 — Every score is three numbers, never one.** This is the correction that keeps D2 honest, and it
exists because switchboard's native metric has a denominator that moves. `run_shadow` excludes defers from
the denominator — correct for its purpose (a defer costs quota, not correctness), but actively misleading
here. A 1.5B model prompted with a system prompt written for a 30B model will often fail to emit parseable
JSON at all, so the *baseline* would be scored over a small, self-selected subsample of cases it happened
to answer, while the *tuned* model — which learns the output format almost immediately — is scored over
nearly all of them. Comparing those two agreement percentages compares two different test sets and can
manufacture either a fake win or a fake loss.

Every runner therefore reports the following, where **total** = the number of rows in the frozen test
split, **verdicted** = rows where `local_judge` returned a `Verdict` (i.e. `result.get("defer") is not
True`), and **agreements** = verdicted rows whose `verdict` field equals the frozen Claude label:

- **agreement** = agreements / verdicted — switchboard's native rule, kept for continuity with the kill
  threshold and the bake-off. Undefined when `verdicted == 0`; report `null`, never 0.0.
- **coverage** = verdicted / total — the share of cases the model answered at all. This is where format
  compliance shows up.
- **strict** = agreements / total — a defer counts as a miss. This is the number the headline claim uses,
  because it is the only one whose denominator is fixed by the frozen golden set.

All three are reported as floats in `[0, 1]` alongside their raw integer counts, so any of them can be
recomputed from the JSON without trusting the arithmetic.

The headline delta in `comparison.md` is the **strict** delta. Agreement and coverage are reported
alongside so the write-up can separate "the fine-tune taught the model to emit JSON" from "the fine-tune
taught the model to judge code" — at 1.5B, the former is the likelier effect, and calling it the latter
would be the exact dishonesty this project exists to avoid.

---

## 7. Build Steps

### Step 1: Scaffold `switchboard-tune` and mine real judge inputs
- **Problem:** Create the sibling uv project (WSL2/CUDA-targeted, switchboard as an editable path dep, registered in the observatory registry as owned) and implement `tune/mine_inputs.py`, which walks git history across `dev/` repos, extracts small code-style diff hunks, renders each through the **mined-case prompt shape defined in Appendix A.2** (diff plus the JSON instruction, and deliberately **no editorial summary sentence** — see the label-leak note there, which is load-bearing), dedups near-identical hunks, and writes `data/inputs.jsonl` per the Appendix A.1 schema. Mining bounds: hunks of 2-30 changed lines from `.py`/`.ts`/`.tsx`/`.js`/`.ps1` files, at most 40 hunks per source repo so no single repo dominates, skipping vendored, generated, and lockfile paths.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `switchboard-tune/pyproject.toml`, `tune/mine_inputs.py`, `data/inputs.jsonl`, `README.md`, `CLAUDE.md` (with scrapable `## Stack` + `## Commands` blocks per the descriptor contract), and a `[[project]]` entry in `dev/.claude/observatory/registry.toml` with `slug = "switchboard-tune"`, `path = "switchboard-tune"`, `owned = true`
- **Done when:** `uv run python -m tune.mine_inputs --limit 1200` writes at least 1,000 deduped rows; every row carries provenance; re-running is deterministic given the same repo state; the mined prompt text is built from `switchboard.client.SYSTEM_PROMPT`, not a local string
- **Depends on:** none

<!-- autofix-applied: 2026-07-28 -->
### Step 2: Mint teacher labels with Claude and freeze the golden set
- **Problem:** Implement `tune/label.py` (batch `claude -p` labeling, hardened per D3: explicit `--model`, no tools, stdin for the prompt, `encoding="utf-8", errors="replace"`, resumable so a crash mid-batch does not restart from zero) and `tune/freeze.py` (deterministic 80/10/10 split, SHA256 manifest, refuses to overwrite an existing manifest). Label 500-2,000 mined inputs. **Near-duplicate leakage across splits is the failure mode to design against** — exact-match dedup in Step 1 does not catch a hunk that differs by a variable name, and a near-dupe spanning train and test silently inflates the tuned score.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** `tune/label.py`, `tune/freeze.py`, `data/labeled.jsonl`, `data/golden/{train,dev,test}.jsonl`, `data/golden/MANIFEST.sha256`, `data/golden/leakage-report.json`
- **Done when:** at least 500 labeled rows exist with the `pass`/`flag` distribution reported in the run log; the frozen splits are written; `freeze.py` exits non-zero when asked to overwrite an existing manifest; a deliberate one-byte edit to `test.jsonl` makes manifest verification fail; **and `leakage-report.json` shows zero test-split rows whose normalized-token Jaccard similarity against any train-split row exceeds 0.9** (the check runs inside `freeze.py`, before the manifest is written, and a violation is a hard non-zero exit rather than a warning)
- **Depends on:** 1

<!-- autofix-applied: 2026-07-28 -->
### Step 3: Eval harness with calibration anchors and the zero-dep guard
- **Problem:** Implement `tune/evalharness.py`, scoring any named runner against the frozen test split. It must import `SYSTEM_PROMPT` and the verdict-parsing path from `switchboard.client` (never re-implement them), expose **one** `build_messages(case) -> list[dict]` helper that every consumer (miner, labeler, trainer, evaluator) calls so the message assembly has a single source of truth, reuse `harness.aggregate_agreement`'s rule that defers are excluded from the denominator, verify the golden manifest on every run, and **abort** rather than warn on manifest mismatch or on any fallback prompt/config path. Report the **three-number metric block** defined in D10 (agreement, coverage, strict) rather than a single agreement figure. Add the calibration anchors (`claude`, `always-pass`) and a regression test asserting `evalharness` uses switchboard's `SYSTEM_PROMPT` object **identity** (`is`), plus a test asserting `switchboard/pyproject.toml` still declares `dependencies = []`.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** `tune/evalharness.py`, `tune/messages.py`, `tests/test_evalharness.py`, `tests/test_switchboard_invariants.py`
- **Done when:** the calibration gate passes — `score(claude) > score(always-pass)` by a wide, recorded margin on the frozen test set; **Claude's self-agreement against its own frozen labels is recorded as the practical ceiling** (the student is not expected to exceed it, and a ceiling far below 1.0 means the task itself is ambiguous and the write-up must say so); every runner report carries all three of agreement / coverage / strict; the `is`-identity test fails if `SYSTEM_PROMPT` is copied instead of imported; the zero-dep test fails if any dependency is added to `switchboard/pyproject.toml`; a corrupted manifest causes a non-zero exit, not a warning
- **Depends on:** 2

<!-- autofix-applied: 2026-07-28 -->
### Step 4: End-to-end smoke gate — 20 rows, 10 steps, one real verdict
- **Problem:** Prove the whole pipeline can complete one real cycle before spending an hour on a full run, and before any number is measured. Implement `tune/train_sft.py` and `tune/export.py` far enough to train 10 optimizer steps on 20 rows, merge the adapter, convert to GGUF via llama.cpp's `convert_hf_to_gguf.py`, load it into llama.cpp, and send exactly one judge prompt through switchboard's own `local_judge`. Judgment quality is explicitly out of scope; the deliverable is "the producer/consumer chain does not crash, the prompt survives the round trip unchanged, and trained weights actually reach the served model."
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `tune/train_sft.py` (smoke-capable), `tune/export.py`, `tests/test_chat_template_parity.py`, a smoke run log
- **Done when:** all three gates pass — (a) one command runs train(10 steps)→merge→GGUF→llama.cpp→`local_judge` and the returned dict satisfies `result.get("defer") is not True` and carries a `verdict` in `{"pass","flag"}` with a non-empty `reason`; (b) **chat-template parity** — `tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)` from the HF side is compared against llama-server's `/apply-template` response for the identical `msgs`, and the two strings are equal after normalizing trailing whitespace only; if llama-server in the installed revision does not expose `/apply-template`, fall back to reading the `tokenizer.chat_template` string embedded in the GGUF metadata via `gguf-dump` and asserting it equals the HF template source. A mismatch trains one format and serves another and is invisible to every other test in this plan, so this gate blocks; (c) **weights-moved sentinel** — the 20 smoke rows are labeled with a sentinel reason string the base model would never emit (use the fixed literal `ZZ-SMOKE-SENTINEL-7f3a`), and the exported GGUF reproduces that sentinel in `choices[0].message.content` for a smoke-set prompt, proving the merge→GGUF→llama.cpp path carries trained weights rather than silently serving the base model. Total wall clock under ~10 minutes.
- **Depends on:** 3

<!-- autofix-applied: 2026-07-28 -->
### Step 5: Baseline — score the untuned student through the shipped runtime
- **Problem:** Score Qwen2.5-1.5B-Instruct, prompted with the production `SYSTEM_PROMPT` and untouched by training, against the frozen test split. **The baseline must be measured through the same runtime and the same quantization the tuned model will be served on** — convert the untuned base to GGUF at the identical quant level and score it through `local_judge`, exactly as Step 7 will score the tuned model. Measuring the baseline in fp16 transformers and the treatment in quantized llama.cpp would confound the training effect with a runtime and precision change. Also record the `coder-30b` reference column from the live endpoint.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `results/baseline.json` (the D10 three-number block, per-case outcomes, model id, quant level, runtime, git sha, golden-set hash), a short note in `results/comparison.md`
- **Done when:** `baseline.json` records agreement, coverage, and strict scores on the frozen test set with the golden-set SHA and the quant level embedded; the run is reproducible to the same numbers twice at temperature 0 **for the local student runners** (the `claude` runner is explicitly exempt from this reproducibility claim); `baseline.json` and the eventual `tuned.json` agree on `runtime` and `quant` fields, and the harness refuses to emit a delta if they do not; the `coder-30b` reference column is present and labeled as reference, not as a competitor
- **Depends on:** 4

<!-- autofix-applied: 2026-07-28 -->
### Step 6: Full QLoRA SFT run
- **Problem:** Complete `tune/train_sft.py` for the real run: 4-bit base, LoRA rank/alpha recorded, **loss masked on the prompt so only the verdict tokens train**, checkpoint selection on the dev split, temperature-0 eval, and a bounded `max_steps` so the run cannot exceed roughly 90 minutes. Record every hyperparameter alongside the adapter.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers deep --isolation worktree
- **Produces:** the trained adapter, `results/train_run.json` (hyperparameters, loss curve, chosen checkpoint + why, wall clock, peak VRAM)
- **Done when:** training completes within the step budget without OOM; the selected checkpoint is chosen by dev-split metric and the choice is recorded; prompt-loss masking is demonstrated by a test asserting label tensors are `-100` across the prompt span
- **Depends on:** 5

<!-- autofix-applied: 2026-07-28 -->
### Step 7: Eval the tuned student and write the honest comparison
- **Problem:** Re-score the tuned student on the same frozen test split with the same harness, same runtime, and same quant level, then write `results/comparison.md`: baseline versus tuned across all three D10 numbers, the delta with its direction stated plainly, the `coder-30b` reference column, the Claude self-agreement ceiling, and an interpretation section that separates **format-compliance gains from judgment gains** (a coverage jump with a flat strict score means the fine-tune taught JSON formatting, not code review — say so). If tuning lost, the write-up says tuning lost and explores why. No re-running to chase a better number; a settings change produces a second recorded run, not a replacement. Emit `results/disagreements.jsonl` — one row per case where the tuned student disagreed with Claude — which is both an error-analysis artifact and the input Step 10's predicate tests.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `results/tuned.json`, `results/comparison.md`, `results/disagreements.jsonl`
- **Done when:** `comparison.md` states the delta in percentage points for agreement, coverage, and strict, with the golden-set hash and both model ids; the format-versus-judgment interpretation is present; the numbers in the doc are copy-verifiable from the two JSON files; `disagreements.jsonl` exists (possibly empty) and matches the Appendix A.1 schema. **If the strict delta is zero or negative, the write-up must additionally contain all four of:** (i) the delta stated plainly in the opening sentence, without hedging; (ii) the three most common disagreement patterns, quoted from `disagreements.jsonl` with their case labels; (iii) an explicit list of the candidate explanations considered — too few labels, model too small, teacher labels too noisy (compare against the Claude self-agreement ceiling from Step 3), prompt-loss masking wrong, quantization damage — each marked supported or ruled out **by a number already in hand**, not by speculation; (iv) the one experiment that would most cheaply discriminate between the remaining explanations, written as a concrete next step rather than a vague "more data would help"
- **Note:** a losing result does not block Step 8 or Step 9. The ship script still runs and the certify verdict is still recorded; a tuned model that fails the 0.20 kill rule simply does not get enabled, and that outcome is itself the reportable finding
- **Depends on:** 6

<!-- autofix-applied: 2026-07-28 -->
### Step 8: Ship script — place, certify, and report
- **Problem:** Implement `tune/ship.py`: copy the quantized GGUF into llama-swap's model directory, add the model entry to llama-swap config, invoke `python -m switchboard bakeoff --suite <suite>` against the real endpoint, and surface the `certify_slice` verdict against the existing 0.20 kill threshold. The script only reports — it must not enable a slice on its own.
- **Type:** code
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `tune/ship.py`, a suite file for the tuned runner
- **Done when:** `ship.py --dry-run` prints every action without performing it; the certify verdict is computed with switchboard's own `certify_slice`, not a local reimplementation; the script exits non-zero if the endpoint is unreachable rather than reporting a false pass
- **Depends on:** 7

### Step 9: Live certify and enable decision (operator)
- **Problem:** Run `tune/ship.py` against the live WSL2 endpoint, review the bake-off report, and decide whether the tuned model earns the `review-deep-style` slice. Related to issue #237 (live capture) — this run produces real captured verdicts for the tuned runner, but does not close #237, which needs its own `coder-30b` live capture.
- **Type:** operator
- **Issue:** #
- **Done when (operator confirms each):**
  1. `llama-swap` serves the tuned GGUF and `python -m switchboard config` reports the expected endpoint.
  2. `python -m switchboard bakeoff` produces a report with real captured verdicts (not fixture values).
  3. The disagreement rate is read against the 0.20 strict-greater-than kill rule, with defers excluded.
  4. A written enable/do-not-enable decision is recorded in `results/comparison.md`.
  5. If enabling: `~/.switchboard/config.json` sets `enabled_call_sites["review-deep-style"]` and nothing else; `build-step-style` remains absent or `false`.
- **Depends on:** 8

<!-- autofix-applied: 2026-07-28 -->
### Step 10: Optional DPO stretch
- **Problem:** Build preference pairs from cases where the tuned student disagreed with Claude (Claude verdict = chosen, student verdict = rejected) and run a DPO pass, then re-score on the frozen test split with the same harness, same runtime, and same quant level.
- **Type:** conditional
- **Condition:** `f="$(git rev-parse --show-toplevel)/switchboard-tune/results/disagreements.jsonl"; test -s "$f" && test "$(wc -l < "$f")" -ge 100`
- **Issue:** #
- **Flags:** --reviewers code --isolation worktree
- **Produces:** `tune/dpo.py`, `results/dpo.json`, a comparison section appended to `results/comparison.md`
- **Done when:** DPO completes within VRAM budget and the post-DPO score is recorded against the same frozen test split under the same runtime/quant fields the harness enforces; if the pair-count predicate is false the step skips cleanly and Step 7's write-up notes why
- **Depends on:** 9

---

## 8. Risks and Open Questions

| Item | Risk | Mitigation |
|---|---|---|
| **Defer-inflated baseline** | A 1.5B often fails to emit parseable JSON, so switchboard's native agreement metric scores the baseline over a small self-selected subsample and the tuned model over nearly all cases — comparing two different test sets and manufacturing a fake delta | **D10**: every runner reports agreement + coverage + strict; the headline claim uses **strict**, whose denominator is fixed by the frozen golden set. This is the single most important correction in this plan. |
| **Chat-template drift** | The HF tokenizer's training-time template and llama.cpp's serve-time template differ, so the model is trained on one format and served another — invisible to every unit test and to the eval itself, which would simply report a bad score with no explanation | Step 4 gate (b) asserts byte-for-byte parity and fails the smoke before any expensive run |
| **Silent no-op merge** | The adapter fails to merge, or GGUF conversion drops it, and llama.cpp serves the base model while every step reports success — producing a "tuned" score that is really a second baseline run | Step 4 gate (c): the smoke rows carry a sentinel reason string the base model cannot emit; the exported GGUF must reproduce it |
| **Runtime confound** | Baseline measured in fp16 transformers, treatment measured in quantized llama.cpp — the delta then mixes the training effect with a precision and runtime change | Step 5 converts the *untuned* base to GGUF at the identical quant level and scores it through `local_judge`; the harness refuses to emit a delta when `runtime`/`quant` fields disagree |
| **Train/test leakage via near-duplicates** | Exact-match dedup misses hunks differing only by a variable name; one spanning train and test inflates the tuned score | Step 2's `freeze.py` runs a Jaccard-similarity gate at 0.9 before writing the manifest and hard-exits on a violation |
| 8 GB VRAM ceiling | QLoRA OOM at 1.5B if sequence length or batch is set naively | D1 pins 4-bit + 1024 tokens; Step 4's smoke gate surfaces OOM in 10 minutes rather than 90; peak VRAM recorded in Step 6 |
| 15.5 GB system RAM, and WSL2 defaults to roughly half of it | GGUF conversion or dataset processing gets OOM-killed inside WSL | Verify WSL memory during Step 4; if short, raise it via `.wslconfig` — a documented one-line operator fix, recorded in the README |
| Injected instructions inside mined diffs | A mined hunk contains `<system-reminder>`-shaped text or "ignore previous instructions" and steers the teacher, poisoning labels | Step 2 wraps every hunk in an explicit data delimiter and discards responses that do not parse to the strict verdict schema (Testing Strategy § "Mined content is data") |
| Unauthenticated `claude -p` seam | The batch emits zero labels and exits 0, poisoning every downstream step with an empty dataset | Step 2 fails loudly on an unauthenticated seam; the toolchain section names `CLAUDE_CODE_OAUTH_TOKEN` as the prerequisite |
| Teacher labels are Claude's opinion, not ground truth | The whole eval measures agreement-with-Claude, not correctness | Stated explicitly in `comparison.md`: the metric is *agreement with the teacher*, which is exactly what switchboard's kill rule already measures. Scope of claim pre-registered in D2. |
| Class imbalance in mined inputs | Real diffs may be overwhelmingly `pass`, so a constant-`pass` student scores well | The `always-pass` calibration anchor in Step 3 measures this directly; Step 2's run log reports the label distribution; report balanced accuracy alongside raw agreement if skew exceeds roughly 70/30 |
| `claude -p` batch cost and wall clock | Labeling 2,000 inputs is slow or expensive | Start at 500 (the floor that satisfies the plan); `label.py` is resumable, so the batch can grow incrementally |
| llama.cpp conversion script drift | `convert_hf_to_gguf.py` may not support the chosen architecture in the installed llama.cpp revision, or may not be present at all | Presence is **not yet verified** — Step 4's smoke gate locates and pins it before the expensive run; fallback is to clone and pin a known-good llama.cpp revision, recorded in the README |
| A 1.5B may simply be too small for the task | Both baseline and tuned score near chance, making the delta meaningless | This is a legitimate finding, not a failure — D9 ships it. The `coder-30b` reference column quantifies the capability gap. |
| Stale plan siblings say `general-35b` | A fresh model follows the wrong model name and wrong `max_tokens` | This plan names `coder-30b` throughout and annotates both stale files (Impact Analysis rows) |
| Scope creep into switchboard | A convenient helper lands in `switchboard/` and drags in a dependency | Step 3's `dependencies = []` regression test fails CI if it ever happens |

**Open question OQ1 (tracked in Appendix B, surfaced in the proposal):** should Step 2 target 500 labels
(fastest honest path) or push toward 2,000 (better training signal, more teacher cost)? **Resolved default
for building purposes: start at 500 and grow incrementally**, since `label.py` is resumable and a larger
batch can be appended without redoing any downstream step. A builder should proceed on 500 unless the
operator has replied `OQ1 -> 2000`. This is the only decision in the plan left open to the operator.

---

## 9. Testing Strategy

**Autonomous-behavior classification.** The training and eval pipeline is a set of **one-shot CLI
invocations** that complete and return — it is not a daemon, scheduled job, soak loop, or always-on
watcher. The autonomous-behavior trigger therefore **does not fire** for Steps 1-8 and 10, and reviewers
should confirm that classification rather than looking for a soak step. The one genuinely
observation-shaped unit is Step 9, which watches a real endpoint under live bake-off and is marked
`Type: operator` for exactly that reason.

**Data-pipeline smoke gate.** This feature is a long producer→consumer chain — mined hunk → production
prompt → teacher label → frozen split → tokenizer → trainer → merged weights → GGUF → llama.cpp →
switchboard client → parsed verdict. Every arrow is a place where mocked unit tests pass while the real
chain is broken. **Step 4 is the mandatory smoke gate**, and it deliberately precedes both the baseline
measurement (Step 5) and the expensive training run (Step 6): 20 rows, 10 optimizer steps, one real
verdict through `local_judge`, no mocks anywhere in the chain. Its three gates map to the three arrows
most likely to break silently — the client boundary (a real `Verdict`, not a `Defer`), the template
boundary (train-time and serve-time prompt strings byte-identical), and the weights boundary (a sentinel
the base model cannot produce, proving the merge actually took).

**New tests.**
- `test_evalharness.py` — golden-manifest verification aborts on mismatch; the three D10 numbers are
  computed with the denominators they claim; the calibration anchors bracket the metric;
  `SYSTEM_PROMPT` identity (`is`, not `==`); the harness refuses to emit a delta across mismatched
  `runtime`/`quant` fields.
- `test_switchboard_invariants.py` — `switchboard/pyproject.toml` still declares `dependencies = []`.
  This is the guard that makes D5 mechanical rather than aspirational.
- `test_freeze.py` — split determinism; refusal to overwrite an existing manifest; a one-byte edit breaks
  verification; a planted near-duplicate spanning train and test trips the leakage gate.
- `test_chat_template_parity.py` — the HF-rendered training prompt and the llama.cpp-rendered inference
  prompt are byte-identical for the same case.
- `test_train_sft.py` — label tensors are `-100` across the prompt span (prompt-loss masking actually on).
- `test_label.py` — the `claude -p` seam is invoked with an explicit `--model`, tools disabled, prompt via
  stdin, and `errors="replace"` decoding; a non-UTF-8 byte in a diff does not crash the batch; an
  unauthenticated seam fails loudly rather than emitting zero labels and exiting 0.

**Mined content is data, never instructions.** Step 1 mines diff hunks from real repositories and Step 2
sends them to Claude. A mined hunk could contain text shaped like an instruction — a `<system-reminder>`
block, "ignore previous instructions", or fake tool output — either incidentally (this workspace's own
docs discuss prompt injection) or adversarially. `label.py` must wrap every mined hunk in an explicit
data delimiter, instruct the teacher to treat the payload as the artifact under review rather than as
direction, and discard any response that does not parse to the strict verdict schema. A hunk that
repeatedly fails to yield a schema-valid verdict is dropped from the dataset with its label recorded, not
retried into compliance.

**Existing tests that must not change.** All 183 switchboard tests must pass untouched. A diff to
`switchboard/tests/` in any step of this plan is a signal that scope leaked into the package and should be
challenged in review rather than accepted.

**End-to-end verification.** The feature is verified end-to-end when Step 9's operator run shows a real
bake-off report — captured verdicts, not fixture values — with the disagreement rate evaluated against the
0.20 strict-greater-than rule, and `results/comparison.md` states the baseline-versus-tuned strict delta
with the golden-set hash embedded so the number can be re-derived later.

---

---

## Appendix A — Data shapes, prompt shape, and glossary

Everything a fresh builder needs that is not derivable from the switchboard source.

### A.1 On-disk schemas

Every file below is JSON Lines (one JSON object per line, UTF-8, LF). Field names are exact.

`data/inputs.jsonl` — produced by Step 1, consumed by Step 2:

| field | type | note |
|---|---|---|
| `label` | str | unique case id, format defined in A.3 |
| `diff` | str | the raw hunk text, `+`/`-` prefixed lines, newline-joined |
| `repo` | str | source repo directory name, e.g. `Alpha4Gate` |
| `sha` | str | 40-char commit sha the hunk came from |
| `path` | str | repo-relative file path |
| `lang` | str | one of `py`, `ts`, `tsx`, `js`, `ps1` |

`data/labeled.jsonl` — Step 2 output; every `inputs.jsonl` field plus:

| field | type | note |
|---|---|---|
| `expected` | str | `"pass"` or `"flag"` — the frozen Claude label |
| `reason` | str | Claude's one-line rationale, non-empty |
| `teacher_model` | str | exact model id string passed to `claude -p` |

`data/golden/{train,dev,test}.jsonl` — same schema as `labeled.jsonl`. `data/golden/MANIFEST.sha256`
holds one `<sha256>  <filename>` line per split file, in `sha256sum` format.

`results/baseline.json` and `results/tuned.json` — identical schema:

| field | type | note |
|---|---|---|
| `runner` | str | e.g. `student-prompted`, `student-tuned`, `claude`, `always-pass`, `coder-30b` |
| `model_id` | str | HF repo id or served model name |
| `runtime` | str | `llama.cpp` — the harness refuses a delta across differing values |
| `quant` | str | e.g. `Q4_K_M` — likewise |
| `golden_sha256` | str | manifest hash of the test split scored |
| `total`, `verdicted`, `agreements` | int | raw counts |
| `agreement`, `coverage`, `strict` | float\|null | the D10 numbers; `agreement` is `null` when `verdicted == 0` |
| `defers_by_reason_class` | obj | `{reason_class: count}` using switchboard's `RC_*` strings |
| `cases` | list | per-case `{label, expected, got, deferred, reason_class}` |

`results/disagreements.jsonl` — Step 7 output, Step 10 input: `{label, diff, expected, got, teacher_reason, student_reason}`.

### A.2 The mined-case prompt shape (load-bearing)

A mined case is rendered into exactly two chat messages, assembled by the single `build_messages()`
helper from Step 3:

- **system** — `switchboard.client.SYSTEM_PROMPT`, imported, never retyped.
- **user** — `"Code-style diff under review:\n" + diff + "\n\nRespond with ONLY JSON: {\"verdict\":\"pass\"|\"flag\",\"reason\":\"<short>\"}"`

**Do not copy the hand-authored fixture shape.** The eight cases in
`switchboard/suites/review-deep-style.json` insert an editorial summary sentence between the diff and the
JSON instruction, and those sentences telegraph the answer. The `bare-except` case reads *"Wraps a parse
in a BARE except that swallows every exception including KeyboardInterrupt, hiding real failures"* and is
labeled `flag`; `whitespace-cleanup` reads *"purely cosmetic cleanup"* and is labeled `pass`. A model
could score near-perfectly on those fixtures by reading only the summary and ignoring the diff entirely.

Two consequences make this a hard rule rather than a preference. First, **label leakage**: training on
summary-bearing prompts teaches the student to read the summary, not the code. Second, **train/serve
skew**: mined hunks have no summary and neither does anything the deployed judge sees in production, so a
summary-trained student would face a systematically different input at inference. Mined prompts therefore
carry the diff only. The existing fixtures stay untouched — they are the bake-off's calibration
instrument, not training data.

### A.3 Case-label format

`label` is `<repo>-<sha7>-<n>` — source repo directory name, first 7 sha characters, and a zero-based
per-commit hunk index. Example: `Alpha4Gate-3ac5769-0`. Generated by `mine_inputs.py`; consumed by
`label.py`, `freeze.py`, `evalharness.py`, and any suite file Step 8 writes.

Uniqueness is not cosmetic: `switchboard/bakeoff.py`'s suite loader requires a runner's recorded labels to
cover the suite's case labels **exactly** — no missing, unknown, or duplicate entries — so a duplicate
label surfaces as a suite-load failure at Step 8 rather than as a silently dropped case.

### A.4 Wiring switchboard into switchboard-tune from WSL

`switchboard-tune` declares switchboard as an editable path dependency in its own `pyproject.toml`, which
is how `SYSTEM_PROMPT` and the verdict parser are reused rather than copied:

```toml
[tool.uv.sources]
switchboard = { path = "../switchboard", editable = true }
```

The relative path resolves identically from Windows (`<coding-root>\switchboard`) and from WSL
(`<coding-root>/switchboard`), so no per-platform branch is needed. switchboard is pure-stdlib,
so it imports cleanly under WSL's Python 3.12.3 with nothing else installed.

**Keep large artifacts off `/mnt/c`.** The Windows drive is mounted through the 9P filesystem and is slow
enough to dominate training wall-clock. The repo itself stays on `/mnt/c` so Windows tooling can see it,
but set `HF_HOME=~/.cache/huggingface` and write checkpoints, merged weights, and GGUFs to a native WSL
path such as `~/switchboard-tune-work/`, copying only the final GGUF and the `results/*.json` files back
into the repo.

### A.5 Glossary

| Term | Meaning |
|---|---|
| **LoRA** | Low-Rank Adaptation — trains small adapter matrices alongside frozen base weights instead of updating all parameters. |
| **QLoRA** | LoRA applied on top of a 4-bit-quantized frozen base, cutting VRAM enough to fine-tune on a laptop GPU. |
| **SFT** | Supervised fine-tuning — training on (prompt, desired-output) pairs. Here the desired output is Claude's verdict JSON. |
| **DPO** | Direct Preference Optimization — trains on (chosen, rejected) response pairs rather than single targets. The optional Step 10. |
| **GGUF** | The on-disk model format llama.cpp loads. Produced from HF weights by `convert_hf_to_gguf.py`. |
| **llama.cpp / llama-server** | The C++ inference engine and its OpenAI-compatible HTTP server. |
| **llama-swap** | The WSL2 service on `localhost:8080` that fronts llama.cpp and swaps models on demand. Installed by void_furnace, shared with switchboard. |
| **slice** | switchboard's unit of offload routing: a `task_class` string key in `enabled_call_sites`. This project targets exactly one, `review-deep-style`. |
| **defer** | switchboard's fail-safe outcome — a dict carrying `"defer": True`, meaning the caller routes the judgment to Claude instead. Never an exception. |
| **bake-off / certify** | `python -m switchboard bakeoff` scores runners against a suite; `certify_slice` turns that report into a pass/fail under the kill threshold. |
| **kill rule** | A slice is disabled when its disagreement rate is **strictly greater than** 0.20, with defers excluded from the denominator. |
| **Jaccard similarity** | Intersection-over-union on token sets; used in Step 2 at a 0.9 threshold to catch near-duplicate hunks spanning train and test. |
| **golden set** | The frozen, hash-pinned test split. Frozen before training so it cannot be tuned against. |

---

## Appendix B — Decision Inventory

IDs are **append-only and stable** across republishes of the proposal. A reversed decision is marked
`changed <date>` rather than renumbered or deleted. `P` = operator-picked; `D` = agent-defaulted.

| ID | P/D | Choice | Status |
|---|---|---|---|
| P1 | P | Professional variant (switchboard's local judge) over the toybox activity generator | accepted 2026-07-28 |
| P2 | P | The 5-step spine from the operator's own brief: freeze → baseline → SFT → eval+ship → optional DPO | accepted 2026-07-28 |
| D1 | D | Student is `Qwen/Qwen2.5-1.5B-Instruct`, QLoRA 4-bit (forced by the measured 8188 MiB VRAM ceiling) | proposed |
| D2 | D | Comparison is student-vs-itself; `coder-30b` is a reference column only; claim pre-registered | proposed |
| D3 | D | Teacher labels via the `claude -p` subprocess seam, not the Anthropic API | proposed |
| D4 | D | Dataset inputs mined from real `dev/` git history rather than synthesized by Claude | proposed |
| D5 | D | Code lives in a new sibling project `switchboard-tune/`, running in WSL2 for CUDA | proposed |
| D6 | D | Golden set frozen + hash-pinned before training, with known-good/known-garbage calibration anchors | proposed |
| D7 | D | Ships only by clearing `python -m switchboard bakeoff` under the existing 0.20 kill rule | proposed |
| D8 | D | DPO gated behind a `≥100` disagreement-pair conditional predicate | proposed |
| D9 | D | Negative results ship; no rerunning to chase a better number | proposed |
| D10 | D | Every score is three numbers (agreement / coverage / strict); headline delta uses **strict** | proposed (added by plan-review 2026-07-28) |
| OQ1 | D | Teacher-label target: start at 500 and grow incrementally, rather than minting 2,000 up front | open — awaiting operator |

---

## Next steps

Canonical order from `.claude/rules/plan-and-issue-flow.md` — review and redline are **done**:

```
/plan-review  ✓  →  /plan-redline  ✓  →  /plan-wrap
```

Then, once any redline feedback is folded in:

```
/plan-expedite --plan docs/switchboard-tune-plan.md
```

followed by `/build-phase --plan docs/switchboard-tune-plan.md` once `/plan-expedite` returns READY.

If redline feedback lands material changes after `/plan-wrap` has run, re-run `/plan-review` +
`/plan-wrap` before building.
