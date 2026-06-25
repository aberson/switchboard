"""Judge entrypoint CLI — so a SKILL.md can invoke ``local_judge`` from the shell.

    python -m switchboard judge --site <task_class> [--prompt-file PATH | --prompt STR]

``--site`` is the canonical flag the wired SKILL.md prose passes (the call-site task_class);
``--slice`` is a back-compat alias for the same value. Exactly one must be given.

Reads the site (``task_class``) and the judge prompt (from ``--prompt-file``, ``--prompt``,
or stdin),
checks ``offload_allowed(slice)`` FIRST (a clean "defer: offload-disabled" with NO network
when offload is off or the slice is disabled), else calls ``local_judge`` and prints the
verdict-or-defer as JSON to stdout.

Contract for the CALLER (a skill):
  * exit code is ALWAYS 0 on a well-formed invocation — a ``defer`` is not an error, it is
    the signal to fall back to the existing Claude path. The caller inspects the JSON, not
    the exit code, to decide verdict-vs-defer.
  * stdout is exactly one JSON object. Diagnostics go to stderr.
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

from switchboard.client import (
    RC_CONFIG_ERROR,
    RC_INPUT_ERROR,
    JudgeResult,
    config_error_defer,
    input_error_defer,
    local_judge,
)
from switchboard.config import ConfigError, SwitchboardConfig, load_config
from switchboard.metrics import METRICS, Metrics


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


def _emit(result: JudgeResult) -> None:
    """Write EXACTLY one JSON object + newline to stdout — the caller's parse contract."""
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


def _run_config(path: str | None) -> int:
    """The ``config`` subcommand: resolve + validate the effective config and print a JSON
    report (including its source) to stdout, exit 0. On a broken config, print the error to
    stderr and exit non-zero.

    This is the operator's loud "is offload actually on?" pre-flight — the antidote to
    silent-off. Per Design Decision D2 the judge hot path stays defer-safe and quiet; this is
    where the loudness lives. With ``--path`` it validates an arbitrary file (e.g. check
    /offload-scan's freshly written offload-config.json before installing it to ~/.switchboard).
    """
    try:
        config, source = load_config(path)
    except ConfigError as exc:
        print(f"switchboard config: INVALID - {exc}", file=sys.stderr)
        return 1

    enabled = sorted(tc for tc in config.enabled_call_sites if config.offload_allowed(tc))
    report: dict[str, object] = {
        "source": source,
        "offload_active": bool(enabled),  # at least one site would offload right now
        "less_token_mode": config.less_token_mode,
        "enabled_sites": enabled,
        "model": config.model,
        "base_url": config.base_url,
        "max_tokens": config.max_tokens,
        "cold_timeout_s": config.cold_timeout_s,
        "warm_timeout_s": config.warm_timeout_s,
        "enabled_call_sites": dict(config.enabled_call_sites),
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
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

    cfg_cmd = sub.add_parser(
        "config",
        help="Resolve + validate the effective config; print it as JSON (the loud pre-flight).",
    )
    cfg_cmd.add_argument(
        "--path",
        dest="path",
        default=None,
        help="Validate a specific config file instead of the resolved source "
        "(e.g. check /offload-scan's offload-config.json before installing it).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry. Returns the process exit code (0 for any well-formed judge invocation)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "judge":
        try:
            prompt = _read_prompt(args.prompt_file, args.prompt)
        except (OSError, UnicodeDecodeError) as exc:
            # Defer-safe: a provided-but-unreadable --prompt-file (missing/locked/non-UTF8) or a
            # failed stdin read is still a well-formed invocation per argparse, so the judge must
            # NOT crash — it degrades to a Claude defer (judge contract: exit 0, one JSON object).
            print(f"switchboard: cannot read prompt, deferring to Claude: {exc}", file=sys.stderr)
            METRICS.record_defer(RC_INPUT_ERROR)
            _emit(input_error_defer(str(exc)))
            return 0
        try:
            config, _ = load_config()
        except ConfigError as exc:
            # Defer-safe: a broken config must NEVER crash the judge — it degrades to a Claude
            # fallback. The warning goes to stderr so stdout stays exactly one JSON object; the
            # defer is counted into METRICS for parity with every other defer reason class.
            print(f"switchboard: config error, deferring to Claude: {exc}", file=sys.stderr)
            METRICS.record_defer(RC_CONFIG_ERROR)
            _emit(config_error_defer(str(exc)))
            return 0
        _emit(run_judge(slice_name=args.site, prompt=prompt, config=config, cold=args.cold))
        return 0

    if args.command == "config":
        return _run_config(args.path)

    # argparse `required=True` on the subparser makes this unreachable, but keep it total.
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
