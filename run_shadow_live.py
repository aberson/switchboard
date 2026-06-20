"""Operator-run live shadow measurement against general-35b on localhost:8080.

NOT part of the test suite. Drives the real harness over a handful of real style-judgment
prompts with hand-labelled expected (Claude) verdicts, then prints agreement + quota saved.

    uv run python run_shadow_live.py
"""

from __future__ import annotations

import json
import sys

from switchboard import SwitchboardConfig, health, run_shadow
from switchboard.harness import ShadowCase

SITE = "style-lens"
CFG = SwitchboardConfig(enabled_call_sites={SITE: True})


def _prompt(diff: str, note: str) -> str:
    return (
        f"Code-style diff under review:\n{diff}\n\n{note} "
        'Respond with ONLY JSON: {"verdict":"pass"|"flag","reason":"<short>"}'
    )


# Real style-judgment cases. `expected` = the Claude verdict a human/Claude would give.
CASES = [
    ShadowCase(
        _prompt(
            "- def add(a, b):\n+ def add(a: int, b: int) -> int:\n      return a + b",
            "Adds type hints to a previously untyped function.",
        ),
        expected="pass",
        label="add-type-hints",
        cold=True,  # first call may cold-load the model
    ),
    ShadowCase(
        _prompt(
            "- total = sum(values)\n+ l = 0\n+ for x in values: l = l + x",
            "Replaces a clear built-in sum() with a hand-rolled loop using single-letter 'l'.",
        ),
        expected="flag",
        label="manual-loop-bad-name",
    ),
    ShadowCase(
        _prompt(
            "- # TODO fix later\n- x=compute( )\n+ x = compute()",
            "Whitespace + removes a stale TODO; purely cosmetic cleanup.",
        ),
        expected="pass",
        label="whitespace-cleanup",
    ),
    ShadowCase(
        _prompt(
            "- result = [transform(i) for i in items]\n"
            "+ result = []\n+ for i in items:\n+     result.append(transform(i))",
            "Expands a clear list comprehension into a verbose append loop.",
        ),
        expected="flag",
        label="comprehension-to-loop",
    ),
]


def main() -> int:
    h = health(CFG)
    print("# endpoint health")
    print(json.dumps(h, indent=2))
    if not h["reachable"]:
        print("endpoint unreachable — cannot run the live shadow measurement.")
        return 1

    print("\n# running shadow harness over", len(CASES), "real style cases ...")
    report = run_shadow(CASES, config=CFG, task_class=SITE)

    print("\n# shadow report")
    for line in report.summary_lines():
        print("  " + line)

    print("\n# per-case")
    for o in report.outcomes:
        verdict = o.local_verdict if o.local_verdict else f"DEFER({o.reason_class})"
        mark = "OK " if o.agreed else ("def" if o.deferred else "DIFF")
        print(
            f"  [{mark}] {o.label:24} expected={o.expected:4} "
            f"local={verdict}  {o.elapsed_s:.1f}s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
