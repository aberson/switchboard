"""Judge + bake-off + config entrypoint CLI — so a SKILL.md (or operator) can invoke from the shell.

    python -m switchboard judge --site <task_class> [--prompt-file PATH | --prompt STR]
    python -m switchboard bakeoff --suite <path> [--output-dir <dir>]
    python -m switchboard config [--path PATH]
    python -m switchboard inspect [--path PATH] [--registry PATH] [--json] [--roles]

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

The ``config`` subcommand resolves + validates the effective config and prints it as JSON —
the operator's loud "is offload actually on?" pre-flight (the antidote to silent-off).

The ``inspect`` subcommand reports config, per-site effective models, the role registry
table, and one bounded endpoint probe. ``inspect --roles --json`` prints only the registry
table (role -> per-host model and effort, plus the cited ``claim_id``) and never probes the
endpoint, so an external driver can read it without importing this package. The table is read
from the committed registry (``--registry``, then ``$SWITCHBOARD_REGISTRY``, then the repo
default); an absent or invalid registry is reported as data with exit 0. Rows are requested
values only: nothing here dispatches by role.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from switchboard.bakeoff import (
    BakeoffError,
    BakeoffReport,
    load_suite,
    render,
    render_jsonl,
    render_observatory_artifact,
    run_bakeoff,
)
from switchboard.client import (
    RC_CONFIG_ERROR,
    RC_INPUT_ERROR,
    JudgeResult,
    config_error_defer,
    input_error_defer,
    local_judge,
)
from switchboard.config import (
    ConfigError,
    SiteInspection,
    SwitchboardConfig,
    config_source_label,
    inspect_sites,
    load_config,
)
from switchboard.health import EndpointStatus, Health, endpoint_status, health
from switchboard.metrics import METRICS, Metrics
from switchboard.registry import (
    ALLOWED_HOSTS,
    RegistryResult,
    RegistryState,
    RoleRow,
    load_registry,
)

# Default output dir for `bakeoff` when --output-dir is omitted: a repo-local _tmp/ sibling.
DEFAULT_BAKEOFF_OUTPUT = "_tmp"
# v2 added a config-resident ``roles`` table (and the probe-free ``inspect --roles`` view).
# v3 reads roles from the committed registry: per-host ``model``/``effort`` plus ``claim_id``,
# with ``registry_state`` (absent | invalid | ok) in place of the roles view's config_state.
INSPECT_SCHEMA_VERSION = 3
InspectState = Literal[
    "absent",
    "invalid",
    "inactive",
    "active-offline",
    "active-online-model-missing",
    "active-online",
]
INSPECT_STATES: tuple[InspectState, ...] = (
    "absent",
    "invalid",
    "inactive",
    "active-offline",
    "active-online-model-missing",
    "active-online",
)


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
    (out_dir / "bakeoff.json").write_text(render_observatory_artifact(report), encoding="utf-8")

    print(_bakeoff_summary_line(report, out_dir), file=out)  # type: ignore[arg-type]
    return 0


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
        "effort": dict(config.effort),
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


@dataclass(frozen=True, slots=True)
class InspectReport:
    """Versioned config + bounded endpoint facts for the operator ``inspect`` surface."""

    schema_version: int
    state: InspectState
    config_state: Literal["absent", "valid", "invalid"]
    source: str
    offload_active: bool | None
    endpoint_status: EndpointStatus | Literal["not-probed"]
    config: dict[str, object] | None
    health: Health | None
    sites: tuple[SiteInspection, ...]
    registry_state: RegistryState
    registry_source: str
    registry_error: str | None
    roles: tuple[RoleRow, ...]
    error: str | None
    limitations: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "config_state": self.config_state,
            "source": self.source,
            "offload_active": self.offload_active,
            "endpoint_status": self.endpoint_status,
            "config": self.config,
            "health": self.health,
            "sites": [site.to_json() for site in self.sites],
            "registry_state": self.registry_state,
            "registry_source": self.registry_source,
            "registry_error": self.registry_error,
            "roles": [role.to_json() for role in self.roles],
            "error": self.error,
            "limitations": list(self.limitations),
        }


_INSPECT_LIMITATIONS = (
    "Endpoint reachability is not bake-off certification or correctness evidence.",
    "A configured effort hint is Claude-side metadata; the local judge client does not consume it.",
    "No outcome or retry evidence is inferred from endpoint health or config state.",
    "Role rows are requested registry values, not observed dispatches: nothing in switchboard "
    "dispatches by role, and inherit means the host resolves exactly as it does today.",
)


def _inspect_state(
    source: str, offload_active: bool, status: EndpointStatus
) -> tuple[InspectState, Literal["absent", "valid"]]:
    """Give no-config, inactive, endpoint, and model-serving states distinct labels."""
    if source == "defaults":
        return "absent", "absent"
    if not offload_active:
        return "inactive", "valid"
    if status == "offline":
        return "active-offline", "valid"
    if status == "online-model-missing":
        return "active-online-model-missing", "valid"
    return "active-online", "valid"


def build_inspect_report(
    path: str | None = None, registry_path: str | None = None
) -> InspectReport:
    """Read validated config, the registry, and one bounded health probe; mutate nothing.

    The registry is independent of config: an invalid config still reports the role table, and
    an absent or invalid registry never hides the config and endpoint facts.
    """
    registry = load_registry(registry_path)
    source = config_source_label(path)
    try:
        config, source = load_config(path)
    except ConfigError as exc:
        return InspectReport(
            schema_version=INSPECT_SCHEMA_VERSION,
            state="invalid",
            config_state="invalid",
            source=source,
            offload_active=None,
            endpoint_status="not-probed",
            config=None,
            health=None,
            sites=(),
            registry_state=registry.state,
            registry_source=registry.source,
            registry_error=registry.error,
            roles=registry.roles,
            error=str(exc),
            limitations=_INSPECT_LIMITATIONS,
        )

    sites = inspect_sites(config)
    offload_active = any(site.offload_allowed for site in sites)
    health_result = health(config)
    status = endpoint_status(health_result)
    state, config_state = _inspect_state(source, offload_active, status)
    return InspectReport(
        schema_version=INSPECT_SCHEMA_VERSION,
        state=state,
        config_state=config_state,
        source=source,
        offload_active=offload_active,
        endpoint_status=status,
        config={
            "less_token_mode": config.less_token_mode,
            "default_model": config.model,
            "base_url": config.base_url,
            "cold_timeout_s": config.cold_timeout_s,
            "warm_timeout_s": config.warm_timeout_s,
            "max_tokens": config.max_tokens,
        },
        health=health_result,
        sites=sites,
        registry_state=registry.state,
        registry_source=registry.source,
        registry_error=registry.error,
        roles=registry.roles,
        error=None,
        limitations=_INSPECT_LIMITATIONS,
    )


def _print_inspect(report: InspectReport) -> None:
    """Render the same facts in concise human form; JSON remains the stable contract."""
    print("== switchboard inspect ==")
    print(f"  state: {report.state}")
    print(f"  source: {report.source}")
    print(f"  endpoint: {report.endpoint_status}")
    if report.error is not None:
        print(f"  config error: {report.error}")
    else:
        print(f"  offload active: {report.offload_active}")
        for site in report.sites:
            print(
                f"  site={site.site} enabled={site.site_enabled} "
                f"effective_model={site.effective_model} effort={site.effort_hint}"
            )
    print(f"  registry: {report.registry_state}")
    print(f"  registry source: {report.registry_source}")
    if report.registry_error is not None:
        print(f"  registry error: {report.registry_error}")
    _print_roles(report.roles)


def build_roles_report(registry_path: str | None = None) -> dict[str, object]:
    """The probe-free ``inspect --roles`` view: the registry table only.

    Reads and validates the registry but never reads config or calls the endpoint. An absent
    or invalid registry is reported as data (``registry_state``, empty ``roles``, an ``error``),
    not a crash, so a driver sees the failure instead of an empty table that looks unpinned.
    """
    registry: RegistryResult = load_registry(registry_path)
    return {
        "schema_version": INSPECT_SCHEMA_VERSION,
        "view": "roles",
        "registry_state": registry.state,
        "source": registry.source,
        "roles": [role.to_json() for role in registry.roles],
        "error": registry.error,
    }


def _print_roles(rows: Sequence[RoleRow]) -> None:
    for row in rows:
        hosts = " ".join(
            f"{host}={row.host(host).model}/{row.host(host).effort}" for host in ALLOWED_HOSTS
        )
        print(f"  role={row.role} {hosts} read_only={row.read_only} claim={row.claim_id}")


def _run_inspect(
    path: str | None,
    json_output: bool,
    roles_only: bool = False,
    registry_path: str | None = None,
) -> int:
    """Emit an inspect report for all config/endpoint states; invalid is data, not a crash."""
    if roles_only:
        if json_output:
            json.dump(build_roles_report(registry_path), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        registry = load_registry(registry_path)
        print("== switchboard inspect --roles ==")
        print(f"  registry: {registry.state}")
        print(f"  registry source: {registry.source}")
        if registry.error is not None:
            print(f"  registry error: {registry.error}")
            return 0
        _print_roles(registry.roles)
        return 0
    report = build_inspect_report(path, registry_path)
    if json_output:
        json.dump(report.to_json(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        _print_inspect(report)
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
            "(agreement + cost + latency + 0.20 kill); write report.md, scores.jsonl, and "
            "a versioned bakeoff.json artifact."
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
        help=(
            "Where to write report.md, scores.jsonl, and bakeoff.json "
            f"(default './{DEFAULT_BAKEOFF_OUTPUT}')."
        ),
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

    inspect_cmd = sub.add_parser(
        "inspect",
        help="report config, effective site models, the role registry, and endpoint health",
    )
    inspect_cmd.add_argument(
        "--path",
        dest="path",
        default=None,
        help="inspect a specific config file instead of the resolved config source",
    )
    inspect_cmd.add_argument(
        "--json",
        action="store_true",
        help="write the versioned machine-readable report to stdout",
    )
    inspect_cmd.add_argument(
        "--registry",
        dest="registry",
        default=None,
        help="read a specific role registry file instead of $SWITCHBOARD_REGISTRY or the "
        "committed registry/models.json",
    )
    inspect_cmd.add_argument(
        "--roles",
        action="store_true",
        help="report only the role registry table; never reads config or probes the endpoint",
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

    if args.command == "bakeoff":
        return run_bakeoff_cli(suite_path=args.suite, output_dir=args.output_dir)

    if args.command == "config":
        return _run_config(args.path)

    if args.command == "inspect":
        return _run_inspect(args.path, args.json, args.roles, args.registry)

    # argparse `required=True` on the subparser makes this unreachable, but keep it total.
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
