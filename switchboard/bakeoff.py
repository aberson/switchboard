"""Slice bake-off harness — certify a slice's candidate runners against a frozen suite.

This is the Switchboard Phase B (B1) certification engine, and it doubles as
judging-Phase-3's live-sweep artifact: instead of grading against a gold label, every
candidate runner is graded against a REFERENCE runner (Opus) on a frozen suite of real slice
prompts. The question it answers: "can a cheaper/local runner stand in for the reference on
this slice without degrading the verdict, and what does it cost / how slow is it?"

The math is the SAME rule the shadow harness uses: per runner, per case, compare the runner's
recorded verdict to the case's expected (reference) verdict; a DEFER (null verdict — the
runner fell back: model down, truncated, wrong-shape) is EXCLUDED from the agreement
denominator; a runner KILLS when its disagreement rate among verdicted cases strictly exceeds
the kill threshold (default 0.20). That rule lives in ONE place — ``harness.aggregate_agreement``
— and both ``run_shadow`` and this module call it, so the threshold and the defer-exclusion
are never re-derived (code-quality.md one-source-of-truth discipline).

Two modes:

  * **Recorded** (the tested core) — candidate outputs are supplied as committed JSON: no
    network, no live endpoint, no model needed. Given the same suite the bake-off is fully
    deterministic, which is what makes ``suites/review-deep-style.json`` a regression gate.
  * **Live local** (thin) — the local runner is run live by delegating to ``run_shadow`` (so
    it reuses the EXACT engine), and its ``ShadowReport`` is folded into a ``RunnerReport``.

The report dataclasses port the SHAPE of void_furnace's benchmark report (a per-(runner,case)
matrix + per-runner aggregate, with ``render`` markdown and ``render_jsonl`` NDJSON pure
functions). We port the shape, NOT the code: void_furnace is a separate repo with heavy deps,
and switchboard is stdlib-only (``dependencies = []``). JSON, never YAML, for the same reason.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from switchboard.config import SwitchboardConfig
from switchboard.harness import (
    DEFAULT_KILL_THRESHOLD,
    ShadowCase,
    aggregate_agreement,
    run_shadow,
)

__all__ = [
    "BAKEOFF_ARTIFACT_SCHEMA_VERSION",
    "BakeoffError",
    "BakeoffReport",
    "CaseRow",
    "RunnerReport",
    "Suite",
    "SuiteCase",
    "load_suite",
    "render",
    "render_jsonl",
    "render_observatory_artifact",
    "run_bakeoff",
    "run_live_local_runner",
    "score_runner",
]

#: Versioned bounded bake-off result artifact for producer-owned observatory reads.
BAKEOFF_ARTIFACT_SCHEMA_VERSION = 1

# A reference/expected verdict and a recorded runner verdict share the same {pass, flag}
# domain. A recorded verdict may additionally be None (the runner DEFERRED).
Reference = Literal["pass", "flag"]
RecordedVerdict = Literal["pass", "flag"] | None


class BakeoffError(ValueError):
    """Raised when a bake-off suite is malformed. Subclass of ValueError so callers that catch
    ValueError (mirroring config.ConfigError) keep working."""


# --- Suite model -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SuiteCase:
    """One frozen-suite case: the prompt plus the REFERENCE verdict to score runners against.

    ``expected`` is what the reference runner (Claude/Opus) says — the gold-by-proxy label.
    ``label`` is the join key: every runner's recorded list is matched to a case by label.
    """

    label: str
    expected: Reference
    prompt: str


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """One runner's recorded output for one case (matched to a ``SuiteCase`` by ``label``).

    ``verdict`` is ``None`` when the runner DEFERRED (excluded from agreement, like a shadow
    defer). ``cost_usd`` / ``latency_s`` are per-call; for the local runner cost is 0.0.
    """

    label: str
    verdict: RecordedVerdict
    cost_usd: float
    latency_s: float


@dataclass(frozen=True, slots=True)
class Suite:
    """A parsed + validated frozen bake-off suite.

    ``recorded`` maps a runner name to its per-case recorded calls (already aligned to the
    suite's case labels — the loader rejects a runner whose labels don't cover the cases).
    """

    slice_name: str
    reference_runner: str
    kill_threshold: float
    cases: tuple[SuiteCase, ...]
    recorded: Mapping[str, tuple[RecordedCall, ...]]


# --- Report model (void_furnace BenchmarkReport/BenchmarkRow shape, ported) ---------------


@dataclass(frozen=True, slots=True)
class CaseRow:
    """One cell of the (runner x case) bake-off matrix — the ported ``BenchmarkRow`` shape.

    ``agreed`` is True only when the runner verdicted AND matched the reference. ``deferred``
    flags a null verdict (the runner fell back). A deferred row is neither an agreement nor a
    disagreement — it is simply excluded from the runner's denominator.
    """

    runner: str
    label: str
    expected: Reference
    verdict: RecordedVerdict
    deferred: bool
    agreed: bool
    cost_usd: float
    latency_s: float


@dataclass(frozen=True, slots=True)
class RunnerReport:
    """Per-runner aggregate over the suite — the ported per-model aggregate shape.

    Rates and the kill verdict are computed by the shared ``aggregate_agreement`` helper, so a
    runner here and a local judge under ``run_shadow`` apply the identical kill rule. Means are
    over VERDICTED calls only (a defer has no meaningful cost/latency to fold into the average).
    """

    runner: str
    is_reference: bool
    total: int
    verdicted: int
    deferred: int
    agreements: int
    disagreements: int
    agreement_rate: float | None
    disagreement_rate: float | None
    mean_cost_usd: float | None
    mean_latency_s: float | None
    kill_threshold: float
    kill: bool
    kill_reason: str


@dataclass(frozen=True, slots=True)
class BakeoffReport:
    """One full bake-off: the slice, the reference, every runner's aggregate, and the matrix.

    ``runners`` preserves suite order (reference first if present), and ``rows`` is the flat
    per-(runner,case) matrix in that same order — mirroring void_furnace's flat-rows design so
    ``render_jsonl`` is a row-per-line stream.
    """

    slice_name: str
    reference_runner: str
    kill_threshold: float
    n_cases: int
    runners: tuple[RunnerReport, ...]
    rows: tuple[CaseRow, ...] = field(default_factory=tuple)


# --- Loader + validation -----------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BakeoffError(message)


def _as_reference(value: object, where: str) -> Reference:
    _require(
        value in ("pass", "flag"),
        f"{where}: expected verdict must be 'pass' or 'flag', got {value!r}",
    )
    return cast("Reference", value)


def _as_recorded_verdict(value: object, where: str) -> RecordedVerdict:
    _require(
        value is None or value in ("pass", "flag"),
        f"{where}: recorded verdict must be 'pass', 'flag', or null (defer), got {value!r}",
    )
    return cast("RecordedVerdict", value)


def _as_float(value: object, where: str) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{where}: must be a number, got {value!r}",
    )
    return float(cast("float", value))


def _parse_cases(raw_cases: object) -> tuple[SuiteCase, ...]:
    _require(isinstance(raw_cases, list) and len(raw_cases) > 0, "'cases' must be a non-empty list")
    cases: list[SuiteCase] = []
    seen: set[str] = set()
    for i, raw in enumerate(cast("list[object]", raw_cases)):
        where = f"cases[{i}]"
        _require(isinstance(raw, dict), f"{where}: must be an object")
        case = cast("dict[str, object]", raw)
        label = case.get("label")
        _require(
            isinstance(label, str) and label != "",
            f"{where}: 'label' must be a non-empty string, got {label!r}",
        )
        label = cast("str", label)
        _require(label not in seen, f"{where}: duplicate case label {label!r}")
        seen.add(label)
        prompt = case.get("prompt")
        _require(
            isinstance(prompt, str) and prompt != "",
            f"{where} ({label}): 'prompt' must be a non-empty string",
        )
        cases.append(
            SuiteCase(
                label=label,
                expected=_as_reference(case.get("expected"), f"{where} ({label})"),
                prompt=cast("str", prompt),
            )
        )
    return tuple(cases)


def _parse_recorded(
    raw_recorded: object,
    case_labels: tuple[str, ...],
) -> dict[str, tuple[RecordedCall, ...]]:
    _require(isinstance(raw_recorded, dict), "'recorded' must be an object of runner -> calls")
    recorded_raw = cast("dict[str, object]", raw_recorded)
    label_set = set(case_labels)
    out: dict[str, tuple[RecordedCall, ...]] = {}
    for runner, raw_calls in recorded_raw.items():
        where = f"recorded[{runner!r}]"
        _require(isinstance(raw_calls, list), f"{where}: must be a list of per-case calls")
        calls: dict[str, RecordedCall] = {}
        for j, raw in enumerate(cast("list[object]", raw_calls)):
            cw = f"{where}[{j}]"
            _require(isinstance(raw, dict), f"{cw}: must be an object")
            call = cast("dict[str, object]", raw)
            label = call.get("label")
            _require(
                isinstance(label, str) and label in label_set,
                f"{cw}: 'label' {label!r} is not one of the suite case labels",
            )
            label = cast("str", label)
            _require(label not in calls, f"{cw}: duplicate recorded label {label!r}")
            calls[label] = RecordedCall(
                label=label,
                verdict=_as_recorded_verdict(call.get("verdict"), cw),
                cost_usd=_as_float(call.get("cost_usd"), f"{cw}.cost_usd"),
                latency_s=_as_float(call.get("latency_s"), f"{cw}.latency_s"),
            )
        missing = label_set - set(calls)
        _require(
            not missing,
            f"{where}: missing recorded calls for case label(s): {sorted(missing)}",
        )
        # Re-key into suite case order so the matrix rows are stable regardless of JSON order.
        out[runner] = tuple(calls[label] for label in case_labels)
    return out


def load_suite(path: str | Path) -> Suite:
    """Parse + validate a frozen bake-off suite from a JSON file.

    Validation (raises ``BakeoffError`` — a ValueError subclass — on any breach):
      * top-level is an object with a non-empty ``slice`` and ``reference_runner`` string;
      * ``kill_threshold`` (optional) is a number in [0, 1] (default 0.20);
      * ``cases`` is a non-empty list; every case has a unique non-empty ``label``, a non-empty
        ``prompt``, and an ``expected`` in {pass, flag};
      * ``recorded`` is an object of runner -> calls; every runner's calls cover EXACTLY the
        suite case labels (no missing, no unknown, no duplicate); each call has a number
        ``cost_usd`` + ``latency_s`` and a ``verdict`` in {pass, flag, null};
      * the declared ``reference_runner`` actually appears in ``recorded``.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        data_raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BakeoffError(f"suite {p} is not valid JSON: {exc}") from exc

    _require(isinstance(data_raw, dict), f"suite {p}: top level must be a JSON object")
    data = cast("dict[str, object]", data_raw)

    slice_name = data.get("slice")
    _require(
        isinstance(slice_name, str) and slice_name != "",
        f"suite {p}: 'slice' must be a non-empty string",
    )
    reference_runner = data.get("reference_runner")
    _require(
        isinstance(reference_runner, str) and reference_runner != "",
        f"suite {p}: 'reference_runner' must be a non-empty string",
    )

    kill_threshold = DEFAULT_KILL_THRESHOLD
    if "kill_threshold" in data:
        kill_threshold = _as_float(data["kill_threshold"], f"suite {p}: kill_threshold")
        _require(
            0.0 <= kill_threshold <= 1.0,
            f"suite {p}: kill_threshold must be in [0, 1], got {kill_threshold!r}",
        )

    cases = _parse_cases(data.get("cases"))
    case_labels = tuple(c.label for c in cases)
    recorded = _parse_recorded(data.get("recorded"), case_labels)

    reference_runner = cast("str", reference_runner)
    _require(
        reference_runner in recorded,
        f"suite {p}: reference_runner {reference_runner!r} has no 'recorded' entry "
        f"(runners present: {sorted(recorded)})",
    )

    return Suite(
        slice_name=cast("str", slice_name),
        reference_runner=reference_runner,
        kill_threshold=kill_threshold,
        cases=cases,
        recorded=recorded,
    )


# --- Scoring -----------------------------------------------------------------------------


def score_runner(
    runner: str,
    cases: Sequence[SuiteCase],
    calls: Sequence[RecordedCall],
    *,
    reference_runner: str,
    kill_threshold: float,
) -> tuple[RunnerReport, list[CaseRow]]:
    """Score one runner's recorded calls against the suite's reference verdicts.

    ``calls`` is aligned to ``cases`` (the loader re-keys into case order). For each case we
    compare the runner's recorded verdict to the case's expected reference verdict; a defer
    (null) is excluded from the denominator. The agreement + kill math comes from the shared
    ``aggregate_agreement`` helper — the SAME rule ``run_shadow`` uses — so a runner here cannot
    drift from a live local runner's kill decision.
    """
    rows: list[CaseRow] = []
    by_label = {c.label: c for c in cases}
    verdicted = 0
    agreements = 0
    cost_sum = 0.0
    latency_sum = 0.0
    for call in calls:
        case = by_label[call.label]
        deferred = call.verdict is None
        agreed = (not deferred) and call.verdict == case.expected
        if not deferred:
            verdicted += 1
            cost_sum += call.cost_usd
            latency_sum += call.latency_s
            if agreed:
                agreements += 1
        rows.append(
            CaseRow(
                runner=runner,
                label=call.label,
                expected=case.expected,
                verdict=call.verdict,
                deferred=deferred,
                agreed=agreed,
                cost_usd=call.cost_usd,
                latency_s=call.latency_s,
            )
        )

    agg = aggregate_agreement(
        verdicted=verdicted, agreements=agreements, kill_threshold=kill_threshold
    )
    deferred_count = len(rows) - verdicted
    report = RunnerReport(
        runner=runner,
        is_reference=runner == reference_runner,
        total=len(rows),
        verdicted=agg.verdicted,
        deferred=deferred_count,
        agreements=agg.agreements,
        disagreements=agg.disagreements,
        agreement_rate=agg.agreement_rate,
        disagreement_rate=agg.disagreement_rate,
        mean_cost_usd=(cost_sum / verdicted) if verdicted else None,
        mean_latency_s=(latency_sum / verdicted) if verdicted else None,
        kill_threshold=agg.kill_threshold,
        kill=agg.kill,
        kill_reason=agg.kill_reason,
    )
    return report, rows


def _ordered_runners(suite: Suite) -> list[str]:
    """Runner names with the reference first, then the rest in recorded-insertion order."""
    rest = [r for r in suite.recorded if r != suite.reference_runner]
    return [suite.reference_runner, *rest]


def run_bakeoff(suite: Suite) -> BakeoffReport:
    """Score every recorded runner against the reference and build the full bake-off report.

    Deterministic: given the same suite it produces byte-identical ``render`` / ``render_jsonl``
    output — no network, no clock, no model. That is the recorded-mode certification gate.
    """
    runner_reports: list[RunnerReport] = []
    all_rows: list[CaseRow] = []
    for runner in _ordered_runners(suite):
        report, rows = score_runner(
            runner,
            suite.cases,
            suite.recorded[runner],
            reference_runner=suite.reference_runner,
            kill_threshold=suite.kill_threshold,
        )
        runner_reports.append(report)
        all_rows.extend(rows)
    return BakeoffReport(
        slice_name=suite.slice_name,
        reference_runner=suite.reference_runner,
        kill_threshold=suite.kill_threshold,
        n_cases=len(suite.cases),
        runners=tuple(runner_reports),
        rows=tuple(all_rows),
    )


# --- Live local path (thin — delegates to run_shadow for the EXACT engine) ----------------


def run_live_local_runner(
    suite: Suite,
    *,
    runner_name: str = "local",
    config: SwitchboardConfig | None = None,
    task_class: str | None = None,
) -> RunnerReport:
    """Run the LOCAL runner live over the suite by delegating to ``run_shadow``.

    The live local runner reuses the EXACT shadow engine (gating, defer classification, the
    kill rule) by handing the suite's cases to ``run_shadow`` and folding the resulting
    ``ShadowReport`` into a ``RunnerReport``. This keeps the live path thin — the tested core
    is the recorded path; this is the bridge for an operator's real-endpoint run.

    Cost is not measured live (the local model is free → 0.0 mean); latency comes from the
    shadow per-case elapsed average.
    """
    cases = [ShadowCase(c.prompt, expected=c.expected, label=c.label) for c in suite.cases]
    shadow = run_shadow(
        cases,
        config=config,
        kill_threshold=suite.kill_threshold,
        task_class=task_class if task_class is not None else suite.slice_name,
    )
    return RunnerReport(
        runner=runner_name,
        is_reference=runner_name == suite.reference_runner,
        total=shadow.total,
        verdicted=shadow.verdicted,
        deferred=shadow.deferred,
        agreements=shadow.agreements,
        disagreements=shadow.disagreements,
        agreement_rate=shadow.agreement_rate,
        disagreement_rate=shadow.disagreement_rate,
        mean_cost_usd=0.0 if shadow.verdicted else None,
        mean_latency_s=shadow.avg_elapsed_s,
        kill_threshold=shadow.kill_threshold,
        kill=shadow.kill,
        kill_reason=shadow.kill_reason,
    )


# --- Rendering (pure, no I/O — void_furnace render/render_jsonl shape) ---------------------


def _fmt_rate(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _fmt_cost(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.4f}"


def _fmt_latency(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f}s"


def _escape_md_cell(text: str) -> str:
    """Make ``text`` safe in a markdown table cell (pipes split cells; newlines break rows)."""
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def render(report: BakeoffReport) -> str:
    """Render the bake-off report as markdown: header, per-runner aggregate, per-case matrix.

    Pure function of the report — no I/O. Mirrors void_furnace's three-section render.
    """
    kt = report.kill_threshold
    lines: list[str] = []
    lines.append(f"# Bake-off report: {report.slice_name}")
    lines.append("")

    # ---- Section 1: header ----------------------------------------------------------------
    lines.append("## Header")
    lines.append("")
    lines.append("| field | value |")
    lines.append("| --- | --- |")
    lines.append(f"| slice | {_escape_md_cell(report.slice_name)} |")
    lines.append(f"| reference | {_escape_md_cell(report.reference_runner)} |")
    lines.append(f"| kill_threshold | {kt:.0%} disagreement |")
    lines.append(f"| n_cases | {report.n_cases} |")
    lines.append(f"| n_runners | {len(report.runners)} |")
    lines.append("")

    # ---- Section 2: per-runner aggregate --------------------------------------------------
    lines.append("## Per-runner aggregate")
    lines.append("")
    lines.append(
        f"| runner | agreement | disagreement | mean_cost | mean_latency | PASS/FAIL@{kt:.0%} |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in report.runners:
        name = r.runner + (" (ref)" if r.is_reference else "")
        gate = "FAIL" if r.kill else "PASS"
        lines.append(
            "| "
            + _escape_md_cell(name)
            + f" | {_fmt_rate(r.agreement_rate)} ({r.agreements}/{r.verdicted})"
            + f" | {_fmt_rate(r.disagreement_rate)}"
            + f" | {_fmt_cost(r.mean_cost_usd)}"
            + f" | {_fmt_latency(r.mean_latency_s)}"
            + f" | {gate} |"
        )
    lines.append("")

    # ---- Section 3: per-case matrix -------------------------------------------------------
    lines.append("## Per-case matrix")
    lines.append("")
    lines.append("| runner | case | expected | verdict | result | cost | latency |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in report.rows:
        verdict = "DEFER" if row.deferred else (row.verdict or "")
        result = "defer" if row.deferred else ("OK" if row.agreed else "DIFF")
        lines.append(
            "| "
            + _escape_md_cell(row.runner)
            + f" | {_escape_md_cell(row.label)}"
            + f" | {row.expected}"
            + f" | {verdict}"
            + f" | {result}"
            + f" | {_fmt_cost(row.cost_usd)}"
            + f" | {_fmt_latency(row.latency_s)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _runner_to_jsonable(r: RunnerReport) -> dict[str, object]:
    return {
        "runner": r.runner,
        "is_reference": r.is_reference,
        "total": r.total,
        "verdicted": r.verdicted,
        "deferred": r.deferred,
        "agreements": r.agreements,
        "disagreements": r.disagreements,
        "agreement_rate": r.agreement_rate,
        "disagreement_rate": r.disagreement_rate,
        "mean_cost_usd": r.mean_cost_usd,
        "mean_latency_s": r.mean_latency_s,
        "kill_threshold": r.kill_threshold,
        "kill": r.kill,
        "kill_reason": r.kill_reason,
    }


def _row_to_jsonable(row: CaseRow) -> dict[str, object]:
    return {
        "runner": row.runner,
        "label": row.label,
        "expected": row.expected,
        "verdict": row.verdict,
        "deferred": row.deferred,
        "agreed": row.agreed,
        "cost_usd": row.cost_usd,
        "latency_s": row.latency_s,
    }


def render_observatory_artifact(report: BakeoffReport) -> str:
    """Render the bounded, versioned bake-off artifact consumed by observatory surfaces.

    The artifact includes recorded evidence only: runner aggregates and per-case labels,
    verdicts, costs, and latencies. It intentionally excludes suite prompts and any live
    endpoint claim. The input suite remains the operator-selected evidence source; a
    ``PASS`` is recorded-suite agreement, not a routing gate or a live certification claim.
    """
    payload = {
        "schema_version": BAKEOFF_ARTIFACT_SCHEMA_VERSION,
        "artifact": "switchboard-bakeoff",
        "slice": report.slice_name,
        "reference_runner": report.reference_runner,
        "kill_threshold": report.kill_threshold,
        "n_cases": report.n_cases,
        "runners": [_runner_to_jsonable(runner) for runner in report.runners],
        "rows": [_row_to_jsonable(row) for row in report.rows],
        "limitations": [
            "Recorded-suite agreement is not live endpoint evidence or certification.",
            "A PASS does not make the local model a correctness or merge gate.",
            "No outcome or caller-wiring evidence is inferred by this artifact.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def render_jsonl(report: BakeoffReport) -> str:
    """Render the bake-off report as newline-delimited JSON.

    The first line is a ``{"kind": "header", ...}`` record (slice, reference, kill_threshold,
    n_cases, plus the per-runner aggregates); subsequent lines are one ``{"kind": "row", ...}``
    per (runner, case) cell. Consumers filter on ``kind``. Pure function — no I/O.
    """
    lines: list[str] = []
    header = {
        "kind": "header",
        "slice": report.slice_name,
        "reference_runner": report.reference_runner,
        "kill_threshold": report.kill_threshold,
        "n_cases": report.n_cases,
        "runners": [_runner_to_jsonable(r) for r in report.runners],
    }
    lines.append(json.dumps(header, sort_keys=True))
    for row in report.rows:
        lines.append(json.dumps({"kind": "row", **_row_to_jsonable(row)}, sort_keys=True))
    return "\n".join(lines) + "\n"
