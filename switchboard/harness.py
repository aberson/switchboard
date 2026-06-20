"""Shadow-mode validation harness — prove the offload saves quota WITHOUT degrading quality.

This is the D5 keystone (switchboard-plan.md "Validation / instrumentation"). The
`small_sample_validation_inert_fix` lesson is the spine: instrument the trigger, measure
the real effect, and be ready to REVERT if the offload either never fires or quietly hurts.

Shadow mode, the honest version: for a set of judge prompts each carrying the **expected**
verdict (the Claude judgment — supplied as a label; we do NOT call Claude here), run the
LOCAL judge over all of them and compare local-vs-expected. From that we compute:

  * **agreement rate** — of the cases the local judge actually VERDICTED (pass/flag), how
    many matched the expected Claude verdict. This is the quality signal.
  * **quota saved** — every local verdict is one Claude judge call AVOIDED (a defer is a
    fall-back to Claude, so it saves nothing). Read straight from the metrics counter.
  * **kill criterion** — if the local-vs-expected DISAGREEMENT rate among verdicted cases
    exceeds a configurable threshold, the run returns ``kill=True`` (revert the offload).

A `Defer` is NOT a disagreement: it is the client correctly handing the judgment back to
Claude (model down, truncated, wrong-shaped). It costs no quota and risks no quality, so it
is excluded from the agreement denominator and tracked on its own. The danger this harness
exists to catch is a CONFIDENT-BUT-WRONG local verdict, not a defer.

Nothing here calls Claude or the network directly: it drives ``local_judge`` (which the
unit tests stub) and reads the shared ``Metrics`` counter. The one live measurement is an
operator-run script, not part of the test suite.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from switchboard.client import JudgeResult, local_judge
from switchboard.config import SwitchboardConfig
from switchboard.metrics import Metrics

# The local-vs-expected disagreement ceiling. Above this (among VERDICTED cases) the offload
# is degrading quality faster than it saves quota -> revert. 0.20 = tolerate up to 20%
# disagreement on a fuzzy style judgment; tighten per call site as real data accrues.
DEFAULT_KILL_THRESHOLD = 0.20


@dataclass(frozen=True)
class ShadowCase:
    """One judge prompt plus the expected (Claude) verdict to shadow-compare against.

    ``expected`` is the label a Claude judge would have produced — supplied by the operator
    from a real run, NOT computed here. ``label`` is a short human id for the report.
    """

    prompt: str
    expected: Literal["pass", "flag"]
    label: str = ""
    cold: bool = False


@dataclass(frozen=True)
class CaseOutcome:
    """The per-case shadow result."""

    label: str
    expected: Literal["pass", "flag"]
    # The local verdict, or None when the local judge DEFERRED (fell back to Claude).
    local_verdict: Literal["pass", "flag"] | None
    deferred: bool
    agreed: bool  # local_verdict == expected (False whenever deferred)
    reason_class: str  # the defer reason_class, or "" for a verdict
    elapsed_s: float


@dataclass(frozen=True)
class ShadowReport:
    """The aggregate shadow-mode result + the kill verdict."""

    total: int
    verdicted: int  # cases the local judge returned a real verdict for
    deferred: int  # cases the local judge handed back to Claude
    agreements: int  # of verdicted cases, how many matched expected
    disagreements: int
    agreement_rate: float | None  # agreements / verdicted, or None if nothing verdicted
    disagreement_rate: float | None
    quota_saved: int  # Claude judge calls avoided == verdicted count
    kill_threshold: float
    kill: bool  # revert the offload: disagreement_rate > kill_threshold
    kill_reason: str
    avg_elapsed_s: float | None
    outcomes: list[CaseOutcome] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        """A compact, non-truncated text summary for the operator report."""
        ar = "n/a" if self.agreement_rate is None else f"{self.agreement_rate:.0%}"
        dr = "n/a" if self.disagreement_rate is None else f"{self.disagreement_rate:.0%}"
        avg = "n/a" if self.avg_elapsed_s is None else f"{self.avg_elapsed_s:.1f}s"
        return [
            f"cases:           {self.total}",
            f"verdicted:       {self.verdicted}  (local judge produced a pass/flag)",
            f"deferred:        {self.deferred}  (fell back to Claude — no quota saved, no risk)",
            f"agreement:       {self.agreements}/{self.verdicted}  ({ar})",
            f"disagreement:    {self.disagreements}/{self.verdicted}  ({dr})",
            f"quota saved:     {self.quota_saved} Claude judge call(s) avoided",
            f"avg local call:  {avg}",
            f"kill threshold:  {self.kill_threshold:.0%} disagreement",
            f"KILL:            {self.kill}  ({self.kill_reason})",
        ]


def _verdict_of(result: JudgeResult) -> Literal["pass", "flag"] | None:
    """Pull the verdict from a JudgeResult, or None if it deferred."""
    if result.get("defer") is True:
        return None
    # Not a defer -> it is a Verdict; verdict is "pass" | "flag".
    return result["verdict"]  # type: ignore[typeddict-item]


def run_shadow(
    cases: Sequence[ShadowCase],
    *,
    config: SwitchboardConfig | None = None,
    kill_threshold: float = DEFAULT_KILL_THRESHOLD,
    task_class: str | None = None,
    metrics: Metrics | None = None,
) -> ShadowReport:
    """Run every case through the LOCAL judge and shadow-compare to the expected verdict.

    Args:
        cases: the prompt + expected-Claude-verdict set.
        config: switchboard config (gating + endpoint); defaults to ``SwitchboardConfig()``.
            When offload is OFF or ``task_class`` is disabled, every case DEFERS (no network),
            quota_saved is 0, and the run cannot kill — exactly the inert-by-default behavior.
        kill_threshold: disagreement ceiling among verdicted cases (default 0.20).
        task_class: the call site to gate/route as (e.g. ``"review-deep-style"``).
        metrics: a fresh counter to measure THIS run in isolation; defaults to a new one so
            the harness's quota number reflects only its own cases.

    Returns:
        A ``ShadowReport`` with agreement, quota saved, and the kill verdict.
    """
    if not 0.0 <= kill_threshold <= 1.0:
        raise ValueError(f"kill_threshold must be in [0, 1], got {kill_threshold!r}")

    mx = metrics if metrics is not None else Metrics()
    outcomes: list[CaseOutcome] = []

    for case in cases:
        result = local_judge(
            case.prompt,
            config=config,
            cold=case.cold,
            task_class=task_class,
            metrics=mx,
        )
        local = _verdict_of(result)
        deferred = local is None
        agreed = (not deferred) and local == case.expected
        reason_class = "" if not deferred else str(result.get("reason_class", ""))
        elapsed = float(result.get("_elapsed_s", 0.0))
        outcomes.append(
            CaseOutcome(
                label=case.label or f"case-{len(outcomes)}",
                expected=case.expected,
                local_verdict=local,
                deferred=deferred,
                agreed=agreed,
                reason_class=reason_class,
                elapsed_s=elapsed,
            )
        )

    verdicted = sum(1 for o in outcomes if not o.deferred)
    deferred_count = sum(1 for o in outcomes if o.deferred)
    agreements = sum(1 for o in outcomes if o.agreed)
    disagreements = verdicted - agreements

    agreement_rate = (agreements / verdicted) if verdicted else None
    disagreement_rate = (disagreements / verdicted) if verdicted else None

    # Quota saved == Claude calls avoided == the number of real local verdicts. The metrics
    # counter's verdict_total is the same number through an independent path; assert they
    # agree so a future drift between "outcome" accounting and the counter is caught.
    quota_saved = mx.verdict_total
    assert quota_saved == verdicted, (  # noqa: S101
        f"quota accounting drift: metrics verdict_total={quota_saved} != verdicted={verdicted}"
    )

    if disagreement_rate is None:
        kill = False
        kill_reason = "no verdicts produced (all deferred) — nothing to judge, cannot kill"
    elif disagreement_rate > kill_threshold:
        kill = True
        kill_reason = (
            f"disagreement {disagreement_rate:.0%} > threshold {kill_threshold:.0%} "
            f"— REVERT offload for this slice"
        )
    else:
        kill = False
        kill_reason = f"disagreement {disagreement_rate:.0%} <= threshold {kill_threshold:.0%}"

    elapsed_values = [o.elapsed_s for o in outcomes if not o.deferred]
    avg_elapsed = (sum(elapsed_values) / len(elapsed_values)) if elapsed_values else None

    return ShadowReport(
        total=len(outcomes),
        verdicted=verdicted,
        deferred=deferred_count,
        agreements=agreements,
        disagreements=disagreements,
        agreement_rate=agreement_rate,
        disagreement_rate=disagreement_rate,
        quota_saved=quota_saved,
        kill_threshold=kill_threshold,
        kill=kill,
        kill_reason=kill_reason,
        avg_elapsed_s=avg_elapsed,
        outcomes=outcomes,
    )
