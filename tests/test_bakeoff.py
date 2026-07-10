"""Slice bake-off harness: suite loading/validation, scoring, the kill boundary, rendering.

Everything here is deterministic and network-free — the bake-off's recorded mode supplies
candidate outputs as data, so there is no model, no endpoint, no clock. The committed
``suites/review-deep-style.json`` is exercised as a golden regression gate (local PASSES,
weak FAILS). One test pins that the bake-off and ``run_shadow`` share the SAME kill rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from switchboard.bakeoff import (
    BakeoffError,
    RecordedCall,
    Suite,
    SuiteCase,
    load_suite,
    render,
    render_jsonl,
    run_bakeoff,
    score_runner,
)
from switchboard.harness import DEFAULT_KILL_THRESHOLD, aggregate_agreement

# The committed canonical suite lives next to the package (switchboard/suites/).
SUITE_PATH = Path(__file__).resolve().parent.parent / "suites" / "review-deep-style.json"
# The Phase B effort-vs-model arm suite (illustrative numbers — see its top-level "note").
EFFORT_SUITE_PATH = Path(__file__).resolve().parent.parent / "suites" / "effort-vs-model.json"


# --- Helpers to build small in-test suites without touching disk -------------------------


def _suite_dict(
    *,
    cases: list[dict[str, object]],
    recorded: dict[str, list[dict[str, object]]],
    reference_runner: str = "opus",
    kill_threshold: float = 0.20,
    slice_name: str = "test-slice",
) -> dict[str, object]:
    return {
        "slice": slice_name,
        "reference_runner": reference_runner,
        "kill_threshold": kill_threshold,
        "cases": cases,
        "recorded": recorded,
    }


def _write_suite(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "suite.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# --- Loading + validation ----------------------------------------------------------------


def test_good_suite_parses(tmp_path: Path) -> None:
    data = _suite_dict(
        cases=[
            {"label": "a", "expected": "pass", "prompt": "p-a"},
            {"label": "b", "expected": "flag", "prompt": "p-b"},
        ],
        recorded={
            "opus": [
                {"label": "a", "verdict": "pass", "cost_usd": 0.01, "latency_s": 4.0},
                {"label": "b", "verdict": "flag", "cost_usd": 0.01, "latency_s": 4.0},
            ],
            "local": [
                {"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 16.0},
                {"label": "b", "verdict": None, "cost_usd": 0.0, "latency_s": 12.0},
            ],
        },
    )
    suite = load_suite(_write_suite(tmp_path, data))
    assert isinstance(suite, Suite)
    assert suite.slice_name == "test-slice"
    assert suite.reference_runner == "opus"
    assert suite.kill_threshold == 0.20
    assert [c.label for c in suite.cases] == ["a", "b"]
    assert set(suite.recorded) == {"opus", "local"}
    # Recorded calls are re-keyed into case order, regardless of JSON order.
    assert [c.label for c in suite.recorded["local"]] == ["a", "b"]


def test_kill_threshold_defaults_when_omitted(tmp_path: Path) -> None:
    data = {
        "slice": "s",
        "reference_runner": "opus",
        "cases": [{"label": "a", "expected": "pass", "prompt": "p"}],
        "recorded": {
            "opus": [{"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0}],
        },
    }
    suite = load_suite(_write_suite(tmp_path, data))
    assert suite.kill_threshold == DEFAULT_KILL_THRESHOLD


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.update(slice=""), id="empty-slice"),
        pytest.param(lambda d: d.pop("reference_runner"), id="missing-reference"),
        pytest.param(lambda d: d.update(kill_threshold=1.5), id="threshold-out-of-range"),
        pytest.param(lambda d: d.update(cases=[]), id="empty-cases"),
        pytest.param(lambda d: d["cases"][0].update(expected="maybe"), id="bad-expected-verdict"),
        pytest.param(lambda d: d["cases"][0].update(label=""), id="empty-label"),
        pytest.param(lambda d: d["cases"][0].pop("prompt"), id="missing-prompt"),
    ],
)
def test_malformed_suite_raises(tmp_path: Path, mutate: object) -> None:
    data = _suite_dict(
        cases=[{"label": "a", "expected": "pass", "prompt": "p"}],
        recorded={
            "opus": [{"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0}],
        },
    )
    mutate(data)  # type: ignore[operator]
    with pytest.raises(BakeoffError):
        load_suite(_write_suite(tmp_path, data))


def test_runner_missing_a_case_label_raises(tmp_path: Path) -> None:
    # 'local' only covers 'a' but the suite has two cases -> missing 'b'.
    data = _suite_dict(
        cases=[
            {"label": "a", "expected": "pass", "prompt": "p-a"},
            {"label": "b", "expected": "pass", "prompt": "p-b"},
        ],
        recorded={
            "opus": [
                {"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0},
                {"label": "b", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0},
            ],
            "local": [{"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0}],
        },
    )
    with pytest.raises(BakeoffError, match="missing recorded calls"):
        load_suite(_write_suite(tmp_path, data))


def test_runner_with_unknown_label_raises(tmp_path: Path) -> None:
    data = _suite_dict(
        cases=[{"label": "a", "expected": "pass", "prompt": "p"}],
        recorded={
            "opus": [{"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0}],
            "local": [{"label": "ZZZ", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0}],
        },
    )
    with pytest.raises(BakeoffError, match="not one of the suite case labels"):
        load_suite(_write_suite(tmp_path, data))


def test_reference_runner_without_recorded_entry_raises(tmp_path: Path) -> None:
    data = _suite_dict(
        cases=[{"label": "a", "expected": "pass", "prompt": "p"}],
        recorded={"local": [{"label": "a", "verdict": "pass", "cost_usd": 0.0, "latency_s": 1.0}]},
        reference_runner="opus",  # not present in recorded
    )
    with pytest.raises(BakeoffError, match="has no 'recorded' entry"):
        load_suite(_write_suite(tmp_path, data))


def test_non_json_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(BakeoffError, match="not valid JSON"):
        load_suite(p)


# --- Scoring correctness over a small in-test fixture ------------------------------------


def _cases(*labels_expected: tuple[str, str]) -> list[SuiteCase]:
    return [SuiteCase(label=lbl, expected=exp, prompt=f"p-{lbl}") for lbl, exp in labels_expected]  # type: ignore[arg-type]


def _calls(*specs: tuple[str, object, float, float]) -> list[RecordedCall]:
    return [
        RecordedCall(label=lbl, verdict=v, cost_usd=c, latency_s=lat)  # type: ignore[arg-type]
        for lbl, v, c, lat in specs
    ]


def test_aggregation_counts_rates_and_means() -> None:
    cases = _cases(("a", "pass"), ("b", "flag"), ("c", "pass"), ("d", "flag"))
    # 3 verdicted (one defer on 'b'); 2 agree, 1 disagree -> 1/3 disagreement.
    calls = _calls(
        ("a", "pass", 0.02, 4.0),  # agree
        ("b", None, 0.0, 12.0),  # DEFER -> excluded from denominator
        ("c", "flag", 0.0, 8.0),  # disagree (expected pass)
        ("d", "flag", 0.0, 10.0),  # agree
    )
    report, rows = score_runner("local", cases, calls, reference_runner="opus", kill_threshold=0.50)
    assert report.total == 4
    assert report.verdicted == 3
    assert report.deferred == 1
    assert report.agreements == 2
    assert report.disagreements == 1
    assert report.agreement_rate == pytest.approx(2 / 3)
    assert report.disagreement_rate == pytest.approx(1 / 3)
    # Means are over VERDICTED calls only (defer excluded): cost (0.02+0+0)/3, lat (4+8+10)/3.
    assert report.mean_cost_usd == pytest.approx(0.02 / 3)
    assert report.mean_latency_s == pytest.approx((4.0 + 8.0 + 10.0) / 3)
    assert report.kill is False  # 33% <= 50% threshold
    assert len(rows) == 4
    deferred_row = next(r for r in rows if r.label == "b")
    assert deferred_row.deferred is True
    assert deferred_row.agreed is False


def test_pass_fail_boundary_is_strict_greater_than() -> None:
    # 5 cases, 1 disagreement = exactly 20% -> PASS (kill is strictly >).
    cases = _cases(("a", "pass"), ("b", "pass"), ("c", "pass"), ("d", "pass"), ("e", "pass"))
    at_threshold = _calls(
        ("a", "pass", 0.0, 1.0),
        ("b", "pass", 0.0, 1.0),
        ("c", "pass", 0.0, 1.0),
        ("d", "pass", 0.0, 1.0),
        ("e", "flag", 0.0, 1.0),  # the 1 disagreement
    )
    report_at, _ = score_runner(
        "r", cases, at_threshold, reference_runner="opus", kill_threshold=0.20
    )
    assert report_at.disagreement_rate == pytest.approx(0.20)
    assert report_at.kill is False  # exactly at the threshold passes

    # 5 cases, 2 disagreements = 40% -> just above 20% -> FAIL.
    above = _calls(
        ("a", "pass", 0.0, 1.0),
        ("b", "pass", 0.0, 1.0),
        ("c", "pass", 0.0, 1.0),
        ("d", "flag", 0.0, 1.0),
        ("e", "flag", 0.0, 1.0),
    )
    report_above, _ = score_runner("r", cases, above, reference_runner="opus", kill_threshold=0.20)
    assert report_above.disagreement_rate == pytest.approx(0.40)
    assert report_above.kill is True
    assert "REVERT" in report_above.kill_reason


def test_defer_only_disagreements_do_not_kill() -> None:
    # A runner whose ONLY non-agreements are defers must not kill: defers are excluded from
    # the denominator, so disagreement_rate is computed over verdicted-only.
    cases = _cases(("a", "flag"), ("b", "flag"), ("c", "flag"))
    calls = _calls(
        ("a", "flag", 0.0, 1.0),  # agree
        ("b", None, 0.0, 1.0),  # defer
        ("c", None, 0.0, 1.0),  # defer
    )
    report, _ = score_runner("local", cases, calls, reference_runner="opus", kill_threshold=0.20)
    assert report.verdicted == 1
    assert report.deferred == 2
    assert report.disagreements == 0
    assert report.disagreement_rate == 0.0
    assert report.kill is False


def test_all_deferred_runner_cannot_kill() -> None:
    cases = _cases(("a", "pass"), ("b", "flag"))
    calls = _calls(("a", None, 0.0, 1.0), ("b", None, 0.0, 1.0))
    report, _ = score_runner("local", cases, calls, reference_runner="opus", kill_threshold=0.20)
    assert report.verdicted == 0
    assert report.agreement_rate is None
    assert report.disagreement_rate is None
    assert report.mean_cost_usd is None
    assert report.mean_latency_s is None
    assert report.kill is False
    assert "all deferred" in report.kill_reason


# --- Shared-rule pin: bakeoff and run_shadow use the SAME kill helper ---------------------


@pytest.mark.parametrize(
    ("verdicted", "agreements", "kill_threshold", "expected_kill"),
    [
        (5, 4, 0.20, False),  # 20% disagreement, exactly at threshold -> PASS
        (5, 3, 0.20, True),  # 40% disagreement -> FAIL
        (7, 6, 0.20, False),  # 14% disagreement -> PASS (mirrors canonical 'local')
        (7, 4, 0.20, True),  # 43% disagreement -> FAIL (mirrors canonical 'weak')
        (0, 0, 0.20, False),  # all deferred -> cannot kill
    ],
)
def test_bakeoff_kill_matches_shared_aggregate(
    verdicted: int, agreements: int, kill_threshold: float, expected_kill: bool
) -> None:
    # score_runner must produce the identical kill decision as the shared helper for the same
    # verdicted/agreement counts — proving there is no second copy of the threshold rule.
    direct = aggregate_agreement(
        verdicted=verdicted, agreements=agreements, kill_threshold=kill_threshold
    )
    # Build a runner whose recorded calls realize exactly these counts (rest are defers).
    cases = _cases(*((f"c{i}", "pass") for i in range(verdicted)))
    calls = _calls(
        *((f"c{i}", ("pass" if i < agreements else "flag"), 0.0, 1.0) for i in range(verdicted))
    )
    report, _ = score_runner(
        "r", cases, calls, reference_runner="opus", kill_threshold=kill_threshold
    )
    assert report.kill == direct.kill == expected_kill
    assert report.disagreement_rate == direct.disagreement_rate


# --- Golden determinism: the committed canonical suite -----------------------------------


def test_canonical_suite_local_passes_weak_fails() -> None:
    suite = load_suite(SUITE_PATH)
    report = run_bakeoff(suite)
    by_runner = {r.runner: r for r in report.runners}

    assert report.reference_runner == "opus"
    assert report.kill_threshold == 0.20
    assert by_runner["opus"].is_reference is True
    # Reference agrees with itself by construction.
    assert by_runner["opus"].agreement_rate == 1.0
    assert by_runner["opus"].kill is False
    # local: under the threshold -> PASS; weak: over the threshold -> FAIL.
    assert by_runner["local"].kill is False
    assert by_runner["local"].disagreement_rate is not None
    assert by_runner["local"].disagreement_rate <= 0.20
    # Pin the exact rates so a fixture edit that keeps the same PASS/FAIL side but
    # silently flips a verdict (e.g. local 1/7 -> 2/7, still <= 0.20) is caught.
    assert by_runner["local"].disagreement_rate == pytest.approx(1 / 7)
    assert by_runner["weak"].kill is True
    assert by_runner["weak"].disagreement_rate is not None
    assert by_runner["weak"].disagreement_rate > 0.20
    assert by_runner["weak"].disagreement_rate == pytest.approx(3 / 7)


# --- Effort-vs-model arm (Phase B / Step B3): illustrative measurement, not truth ---------


def test_effort_vs_model_arm_shows_the_tradeoff() -> None:
    """The committed effort-vs-model suite demonstrates the downgrade-cliff hypothesis.

    ILLUSTRATIVE numbers (the suite's top-level "note" says so): the point of this test is that
    BOTH candidate arms appear in the report with their agreement/cost numbers, and the recorded
    data encodes the claim that ``effort-low`` (a Claude effort-tier candidate) sidesteps the
    model-downgrade quality cliff that ``model:haiku`` falls into. switchboard does not ACT on
    ``effort`` — this is a measurement arm + recorded recommendation only (see config.effort
    docstring + docs/effort-vs-model-recommendation.md).
    """
    suite = load_suite(EFFORT_SUITE_PATH)
    report = run_bakeoff(suite)
    by_runner = {r.runner: r for r in report.runners}

    assert report.slice_name == "effort-vs-model"
    assert report.reference_runner == "opus"
    # Both candidate arms are present in the report alongside the reference.
    assert set(by_runner) == {"opus", "effort-low", "haiku"}
    assert by_runner["opus"].is_reference is True

    eff = by_runner["effort-low"]
    hk = by_runner["haiku"]

    # The effort-tier arm clears the gate (no kill) and agrees better than the model-downgrade
    # arm — the whole point of the hypothesis.
    assert eff.kill is False
    assert eff.agreement_rate is not None and hk.agreement_rate is not None
    assert eff.agreement_rate > hk.agreement_rate

    # The model-downgrade arm falls off the cliff: it KILLS (disagreement strictly over 20%).
    assert hk.kill is True
    assert hk.disagreement_rate is not None and hk.disagreement_rate > 0.20

    # ...but it is cheaper — effort-low costs more than haiku. That is the recorded tradeoff:
    # better agreement for more cost, per the recommendation doc.
    assert eff.mean_cost_usd is not None and hk.mean_cost_usd is not None
    assert eff.mean_cost_usd > hk.mean_cost_usd

    # The numbers actually surface in the rendered report (not just the dataclasses), so an
    # operator reading the markdown sees both arms with their agreement + cost columns.
    md = render(report)
    assert any("effort-low" in ln and "PASS" in ln for ln in md.splitlines())
    assert any("haiku" in ln and "FAIL" in ln for ln in md.splitlines())


def test_canonical_suite_renders_stably() -> None:
    suite = load_suite(SUITE_PATH)
    report = run_bakeoff(suite)

    md = render(report)
    # Deterministic: re-rendering the same report is byte-identical.
    assert md == render(report)
    assert "# Bake-off report: review-deep-style" in md
    assert "## Per-runner aggregate" in md
    assert "## Per-case matrix" in md
    assert "PASS/FAIL@20%" in md
    # Non-vacuous: the gate token must land on each runner's OWN aggregate row, not just
    # in the static "PASS/FAIL@20%" header (which contains neither runner name).
    assert any("weak" in ln and "FAIL" in ln for ln in md.splitlines())
    assert any("local" in ln and "PASS" in ln for ln in md.splitlines())
    assert any("opus" in ln and "PASS" in ln for ln in md.splitlines())

    jsonl = render_jsonl(report)
    assert jsonl == render_jsonl(report)  # deterministic
    lines = jsonl.strip().split("\n")
    header = json.loads(lines[0])
    assert header["kind"] == "header"
    assert header["slice"] == "review-deep-style"
    assert header["reference_runner"] == "opus"
    assert len(header["runners"]) == 3
    # One row per (runner, case): 3 runners x 8 cases.
    rows = [json.loads(line) for line in lines[1:]]
    assert all(r["kind"] == "row" for r in rows)
    assert len(rows) == 3 * 8
    # The deferred local 'bare-except' row carries a null verdict + deferred flag.
    local_defer = next(r for r in rows if r["runner"] == "local" and r["label"] == "bare-except")
    assert local_defer["verdict"] is None
    assert local_defer["deferred"] is True
