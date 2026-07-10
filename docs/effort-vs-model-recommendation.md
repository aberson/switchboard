# Effort-tier vs. model-downgrade for judge slices — recommendation

**Phase B / Step B3 (issue #238). Status: config-only this phase — no live consumer.**

## Hypothesis

For a cheap fan-out **judge slice** (the only offload-safe niche — see `offload-scan`), there
are two ways to make the per-call judgment cheaper than running it at full strength on the
reference model (Opus):

1. **Model downgrade** — run the same prompt on a smaller model (`model:haiku`).
2. **Effort tier** — keep the strong model but lower its reasoning budget (`effort:low`, a
   Claude-side Workflow/Agent `reasoning_effort` override).

The claim under test: **`effort:low` beats `model:haiku` for judge slices by avoiding the
model-downgrade quality cliff.** A smaller model loses calibration on the harder cases (it
starts passing diffs the reference flags, and defers more), whereas a strong model at low
effort keeps the reference's calibration while spending fewer tokens.

## What the bake-off arm shows (illustrative numbers)

The committed suite `suites/effort-vs-model.json` records a 3-runner bake-off on the
review-deep style slice: `opus` (reference), `effort-low`, and `haiku`. The numbers are an
**illustrative hypothesis demonstration, NOT measured truth** — the suite says so in its
top-level `note` field, and the test docstring repeats it. On those recorded numbers:

| arm | agreement vs opus | disagreement | gate | mean cost/call |
| --- | --- | --- | --- | --- |
| `effort-low` | 100% (8/8) | 0% | **PASS** | ~$0.0040 |
| `haiku` | 71% (5/7) | ~29% | **FAIL (kill)** | ~$0.0008 |

`haiku` falls off the cliff: it passes two diffs the reference flags (`comprehension-to-loop`,
`magic-number`) and defers a third (`bare-except`), pushing disagreement over the 20% kill
threshold. `effort-low` keeps full agreement at ~5x the cost of haiku but still far cheaper
than the opus reference.

## Honest caveat

These are **not** captured measurements. Real numbers need a **B2b-style live capture** — run
each arm against the real endpoints and record actual verdicts/cost/latency. The arm here only
demonstrates the *shape* of the tradeoff the recommendation rests on; treat the table as a
hypothesis, not evidence.

## Recommendation

**Default judge slices to `effort:low` over `model:haiku`, pending live confirmation.** Better
to keep the reference model's calibration and trim effort than to swap in a weaker model that
silently mis-grades the hard cases (the local model is never the gate — Switchboard Decision 3).

## Scope note (read this)

`effort` is **config-only this phase**. `SwitchboardConfig` gained an `effort` field that is
validated + round-tripped, and `offload-scan` can emit an `effort` block, but **nothing in
switchboard acts on it** — the `local_judge` urllib client has no effort knob. `effort` is a
hint for Claude-side sub-agent dispatch (the slice's judges when they run on Claude), to be
consumed by a future caller, not by this package. See the `SwitchboardConfig.effort` docstring.
