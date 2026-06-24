"""Judge + bake-off entrypoint CLI — so a SKILL.md (or operator) can invoke from the shell.

    python -m switchboard judge --site <task_class> [--prompt-file PATH | --prompt STR]
    python -m switchboard bakeoff --suite <path> [--output-dir <dir>]

``--site`` is the canonical flag the wired SKILL.md prose passes (the call-site task_class);
``--slice`` is a back-compat alias for the same value. Exactly one must be given.

Reads the site (``task_class``) and the judge prompt (from ``--prompt-file``, ``--prompt``,
or stdin),
checks ``offload_allowed(slice)`` FIRST (a clean "defer: offload-disabled" with NO network
when offload is off or the slice is disabled), else calls ``local_judge`` and prints the
verdict-or-defer as JSON to stdout.

The ``bakeoff`` subcommand runs the recorded-mode slice certification: it reads a frozen
suite, scores every recorded runner against the reference (agreement + cost + latency + the
0.20 kill verdict), writes ``report.md`` + ``scores.jsonl`` to the output dir, and prints ONE
grep-able summary line. It is deterministic — no network, no model.

Contract for the CALLER (a skill):
  * exit code is ALWAYS 0 on a well-formed judge invocation — a ``defer`` is not an error, it
    is the signal to fall back to the existing Claude path. The caller inspects the JSON, not
    the exit code, to decide verdict-vs-defer. (``bakeoff`` exits 2 on a malformed suite —
    that is an input defect, distinct from a runner verdict.)
  * stdout is exactly one JSON object (judge) or one summary line (bakeoff). Diagnostics go to
    stderr.
  * a usage error (bad/missing args) exits non-zero via argparse — that is a caller bug,
    distinct from a defer.

The local model is NEVER a gate (switchboard-plan Decision 3): a ``flag`` verdict ADVISES;
the skill's Claude path still makes the gating call. On ``defer`` the skill MUST fall back.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from switchboard.bakeoff import (
    BakeoffError,
    BakeoffReport,
    load_suite,
    render,
    render_jsonl,
    run_bakeoff,
)
from switchboard.client import JudgeResult, local_judge
from switchboard.config import SwitchboardConfig
from switchboard.metrics import METRICS, Metrics

# Default output dir for `bakeoff` when --output-dir is omitted: a repo-local _tmp/ sibling.
DEFAULT_BAKEOFF_OUTPUT = "_tmp"


def _read_prompt(prompt_file: str | None, prompt: str | None) -> str:
    """Read the judge prompt from an explicit string, a file path, or stdin.

    Precedence: ``--prompt`` (explicit string) > ``--prompt-file`` > stdin.
    """
    if prompt is not None:
        return prompt
    if prompt_file is not None:
        with open(prompt_file, encoding="utf-8") as fh:
            return fh.read()
    return sys.stdin.read()


def run_judge(
    *,
    slice_name: str,
    prompt: str,
    config: SwitchboardConfig | None = None,
    cold: bool = False,
    metrics: Metrics | None = None,
) -> JudgeResult:
    """Run one judge call for ``slice_name``, recording into ``metrics``.

    ``local_judge`` already short-circuits to the defer sentinel WITHOUT touching the
    network when ``offload_allowed(slice)`` is False, and records that defer into metrics.
    We delegate to it rather than re-checking here so there is ONE source of truth for the
    gate (config.offload_allowed) — see code-quality.md one-source-of-truth discipline.
    """
    return local_judge(
        prompt,
        config=config,
        cold=cold,
        task_class=slice_name,
        metrics=metrics if metrics is not None else METRICS,
    )


def _bakeoff_summary_line(report: BakeoffReport, output_dir: Path) -> str:
    """One grep-able stdout line summarizing a recorded bake-off run.

    Names the slice, the runner count, and the PASS/FAIL gate per non-reference runner so a
    calling shell can grep the result without parsing report.md. Reference is excluded from
    the pass/fail roll-up (it agrees with itself by construction).
    """
    candidates = [r for r in report.runners if not r.is_reference]
    passed = sum(1 for r in candidates if not r.kill)
    failed = len(candidates) - passed
    gates = " ".join(f"{r.runner}={'FAIL' if r.kill else 'PASS'}" for r in candidates)
    return (
        f"bakeoff complete: slice={report.slice_name} n_cases={report.n_cases} "
        f"runners={len(report.runners)} candidates={len(candidates)} "
        f"pass={passed} fail={failed} [{gates}] kill_threshold={report.kill_threshold:.0%} "
        f"output={output_dir}"
    )


def run_bakeoff_cli(
    *,
    suite_path: str,
    output_dir: str | None = None,
    stdout: object = None,
) -> int:
    """Read a frozen suite, run the recorded bake-off, write outputs, print the summary line.

    Returns the process exit code: 0 on success, 2 on a malformed suite (an input defect,
    surfaced to stderr). Deterministic — no network, no model.
    """
    out = stdout if stdout is not None else sys.stdout
    try:
        suite = load_suite(suite_path)
    except (BakeoffError, OSError) as exc:
        print(f"error: failed to load suite {suite_path}: {exc}", file=sys.stderr)
        return 2

    report = run_bakeoff(suite)
    out_dir = Path(output_dir) if output_dir else Path(DEFAULT_BAKEOFF_OUTPUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render(report), encoding="utf-8")
    (out_dir / "scores.jsonl").write_text(render_jsonl(report), encoding="utf-8")

    print(_bakeoff_summary_line(report, out_dir), file=out)  # type: ignore[arg-type]
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m switchboard",
        description="Switchboard local-offload entrypoints.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    judge = sub.add_parser(
        "judge",
        help="Run a local judge call for a site; print a verdict-or-defer JSON; always exit 0.",
    )
    # --site is canonical; --slice is a back-compat alias. Exactly one is required; both
    # write the same dest, and add_mutually_exclusive_group(required=True) enforces the count.
    site_group = judge.add_mutually_exclusive_group(required=True)
    site_group.add_argument(
        "--site",
        dest="site",
        help="The call-site task_class (e.g. 'review-deep-style'). Gated by config.",
    )
    site_group.add_argument(
        "--slice",
        dest="site",
        help="Back-compat alias for --site.",
    )
    judge.add_argument(
        "--prompt-file",
        dest="prompt_file",
        default=None,
        help="Path to the judge prompt. If omitted (and no --prompt), read from stdin.",
    )
    judge.add_argument(
        "--prompt",
        dest="prompt",
        default=None,
        help="The judge prompt as an inline string (takes precedence over --prompt-file).",
    )
    judge.add_argument(
        "--cold",
        action="store_true",
        help="Use the cold timeout (first call may cold-load the model).",
    )

    bakeoff = sub.add_parser(
        "bakeoff",
        help=(
            "Score a frozen suite's recorded runners against the reference "
            "(agreement + cost + latency + 0.20 kill); write report.md + scores.jsonl."
        ),
    )
    bakeoff.add_argument(
        "--suite",
        dest="suite",
        required=True,
        help="Path to the frozen bake-off suite JSON (e.g. switchboard/suites/<slice>.json).",
    )
    bakeoff.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help=f"Where to write report.md + scores.jsonl (default './{DEFAULT_BAKEOFF_OUTPUT}').",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. Returns the process exit code (0 for any well-formed judge invocation)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "judge":
        prompt = _read_prompt(args.prompt_file, args.prompt)
        result = run_judge(slice_name=args.site, prompt=prompt, cold=args.cold)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0

    if args.command == "bakeoff":
        return run_bakeoff_cli(suite_path=args.suite, output_dir=args.output_dir)

    # argparse `required=True` on the subparser makes this unreachable, but keep it total.
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
