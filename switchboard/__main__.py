"""``python -m switchboard`` entrypoint.

Two modes, dispatched on argv:

* ``python -m switchboard judge --site <task_class> ...`` — the CLI judge entrypoint a
  SKILL.md invokes (see ``switchboard.cli``). Prints a verdict-or-defer JSON; always exit 0.
* ``python -m switchboard`` (no subcommand) — an OPTIONAL live smoke against a running local
  endpoint. NOT part of the test suite — the unit tests stub the HTTP boundary and never
  touch the network. Run it manually when a llama-swap host is up on localhost:8080:

      uv run python -m switchboard

  It probes /models, fires a pass-case and a flag-case judge call (cold timeout on the
  first), demonstrates the disabled short-circuit, and prints the metrics snapshot.
"""

from __future__ import annotations

import json
import sys

from switchboard.cli import main as cli_main
from switchboard.client import local_judge
from switchboard.config import SwitchboardConfig
from switchboard.health import health
from switchboard.metrics import Metrics

PASS_PROMPT = (
    "Code-style diff under review:\n"
    "- def add(a, b):\n"
    "+ def add(a: int, b: int) -> int:\n"
    "      return a + b\n\n"
    "The change adds type hints to a previously untyped function. "
    'Respond with ONLY JSON: {"verdict":"pass"|"flag","reason":"<short>"}'
)

FLAG_PROMPT = (
    "Code-style diff under review:\n"
    "- total = sum(values)\n"
    "+ l = 0\n"
    "+ for x in values: l = l + x\n\n"
    "The change replaces a clear built-in sum() with a hand-rolled loop using the "
    "single-letter name 'l' (which is easily confused with the digit 1). "
    'Respond with ONLY JSON: {"verdict":"pass"|"flag","reason":"<short>"}'
)


def main() -> None:
    cfg = SwitchboardConfig(enabled_call_sites={"style-lens": True})
    metrics = Metrics()

    print("# 1. /models reachability")
    h = health(cfg)
    print(json.dumps(h, indent=2))
    if not h["reachable"]:
        print("endpoint unreachable — skipping live judge calls (this is fine offline).")
    else:
        print("\n# 2. PASS prompt (cold timeout)")
        cold = local_judge(
            PASS_PROMPT, config=cfg, cold=True, task_class="style-lens", metrics=metrics
        )
        print(json.dumps(cold, indent=2))

        print("\n# 3. FLAG prompt (warm)")
        warm = local_judge(FLAG_PROMPT, config=cfg, task_class="style-lens", metrics=metrics)
        print(json.dumps(warm, indent=2))

    print("\n# 4. less_token_mode OFF short-circuits to defer (no network)")
    off = local_judge(PASS_PROMPT, config=SwitchboardConfig(less_token_mode=False), metrics=metrics)
    print(json.dumps(off, indent=2))
    assert off.get("defer") is True

    print("\n# metrics snapshot")
    print(json.dumps(metrics.snapshot(), indent=2))


if __name__ == "__main__":
    # A subcommand (e.g. `judge`) routes to the CLI; bare invocation runs the live smoke.
    if len(sys.argv) > 1:
        raise SystemExit(cli_main(sys.argv[1:]))
    main()
