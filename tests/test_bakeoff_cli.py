"""Integration tests for the ``bakeoff`` CLI through its production entrypoint.

``run_bakeoff_cli`` + ``_bakeoff_summary_line`` are what ``python -m switchboard bakeoff``
actually invokes (cli.main routes ``args.command == "bakeoff"`` straight into
``run_bakeoff_cli``). These tests exercise that production function end-to-end against the
committed canonical suite — the new-component-needs-an-integration-test-through-the-caller
discipline (code-quality.md). The harness internals are unit-tested in test_bakeoff.py; here
we pin the CLI contract: exit codes, the two written artifacts, and the grep-able summary line.
"""

from __future__ import annotations

import io
from pathlib import Path

from switchboard.cli import run_bakeoff_cli

# The committed canonical suite lives next to the package (switchboard/suites/), resolved
# relative to this file so the test is location-independent (no hardcoded absolute path).
SUITE_PATH = Path(__file__).resolve().parent.parent / "suites" / "review-deep-style.json"


def test_run_bakeoff_cli_good_suite_writes_outputs_and_summary(tmp_path: Path) -> None:
    out = io.StringIO()
    rc = run_bakeoff_cli(suite_path=str(SUITE_PATH), output_dir=str(tmp_path), stdout=out)

    # Success exit code.
    assert rc == 0

    # Both artifacts land in the output dir.
    report_md = tmp_path / "report.md"
    scores_jsonl = tmp_path / "scores.jsonl"
    assert report_md.is_file()
    assert scores_jsonl.is_file()
    assert report_md.read_text(encoding="utf-8").strip()  # non-empty
    assert scores_jsonl.read_text(encoding="utf-8").strip()  # non-empty

    summary = out.getvalue().strip()
    # The grep-able summary names the slice + the pass/fail roll-up.
    assert "slice=review-deep-style" in summary
    assert "pass=1" in summary  # local PASSES
    assert "fail=1" in summary  # weak FAILS
    # Per-candidate gates appear inside the [ ... ] block.
    assert "local=PASS" in summary
    assert "weak=FAIL" in summary
    # The reference runner (opus) is EXCLUDED from the candidate roll-up: 3 runners total but
    # only 2 candidates, and opus must not carry a PASS/FAIL gate token in the summary.
    assert "candidates=2" in summary
    assert "runners=3" in summary
    assert "opus=" not in summary


def test_run_bakeoff_cli_malformed_suite_returns_2_and_writes_nothing(tmp_path: Path) -> None:
    # A structurally-broken suite (valid JSON, but no cases) is an input defect: the documented
    # contract is exit 2 and NO output files written.
    bad_suite = tmp_path / "broken-suite.json"
    bad_suite.write_text('{"slice": "x"}', encoding="utf-8")

    out_dir = tmp_path / "out"
    out = io.StringIO()
    rc = run_bakeoff_cli(suite_path=str(bad_suite), output_dir=str(out_dir), stdout=out)

    assert rc == 2
    # No report / scores written, and the summary line was never printed.
    assert not (out_dir / "report.md").exists()
    assert not (out_dir / "scores.jsonl").exists()
    assert out.getvalue() == ""


def test_run_bakeoff_cli_invalid_json_returns_2_and_writes_nothing(tmp_path: Path) -> None:
    # Outright invalid JSON is also an input defect -> exit 2, no output.
    bad_suite = tmp_path / "not-json.json"
    bad_suite.write_text("{ this is not json", encoding="utf-8")

    out_dir = tmp_path / "out"
    out = io.StringIO()
    rc = run_bakeoff_cli(suite_path=str(bad_suite), output_dir=str(out_dir), stdout=out)

    assert rc == 2
    assert not (out_dir / "report.md").exists()
    assert not (out_dir / "scores.jsonl").exists()
    assert out.getvalue() == ""
