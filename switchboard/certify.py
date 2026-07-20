"""Slice certification — turn a B1 bake-off result into a shippable enable/do-not-enable verdict.

The bake-off (``bakeoff.py``) answers "did the candidate runner agree with the reference often
enough to not KILL?" — a per-runner ``RunnerReport.kill`` plus rates. This module turns that raw
scoring into the ONE decision Phase B2b actually acts on: *may we enable this slice for local
offload, and if so, with what config?*

A slice is CERTIFIED for a candidate runner iff BOTH hold:

  * the candidate did NOT kill (``RunnerReport.kill is False`` — disagreement rate at or under the
    suite's kill_threshold); AND
  * the candidate actually produced verdicts (``agreement_rate is not None``). An all-defer runner
    proves nothing — it never offloaded a single call, so there is no evidence it is safe. "Did not
    kill" alone is a vacuous pass for an all-defer runner (you cannot kill what never judged), which
    is exactly why the verdicted-something check is a SEPARATE, required condition.

A **DO-NOT-ENABLE verdict is a valid, shippable outcome — NOT an error**. The whole point of the
bake-off gate is to be able to say "this slice is not safe to offload yet" cheaply and
deterministically; that answer ships as a ``CertVerdict`` with ``certified=False`` and a
``recommended_config`` of ``None``, never as a raised exception. Callers branch on ``.certified``.

When certified, ``recommended_config`` is the minimal config mapping that enables JUST this slice
(and nothing else), with ``max_tokens`` pinned to a reasoning-model-safe floor — the exact shape
``SwitchboardConfig.from_mapping`` accepts, so an operator (or a test) can round-trip it straight
into ``~/.switchboard/config.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

from switchboard.bakeoff import BakeoffReport, RunnerReport
from switchboard.config import DEFAULT_MAX_TOKENS

# A single-slice enable config pins a higher ceiling than the 800 default. 2000 is the
# operator-verified value from the Phase 1.5 live smoke against general-35b (a reasoning model
# whose reasoning_content + answer fit comfortably under it). coder-30b (the current default) is
# non-reasoning and needs far less, but 2000 is retained as safe headroom pending a coder-30b
# live re-capture (#237). Kept >= the config floor so from_mapping never rejects it.
RECOMMENDED_MAX_TOKENS = 2000
assert RECOMMENDED_MAX_TOKENS >= DEFAULT_MAX_TOKENS  # noqa: S101


@dataclass(frozen=True, slots=True)
class CertVerdict:
    """The shippable certification decision for one slice + one candidate runner.

    ``certified`` is the single bit a caller acts on. ``recommended_config`` is the minimal
    enable-this-slice config when certified, else ``None``. ``reason`` is a human one-liner that
    states explicitly whether this is a certify (safe to enable) or a do-not-enable (a valid,
    non-error outcome) and why. Rates/threshold are carried through verbatim from the bake-off so
    the verdict is self-describing without re-opening the report.
    """

    slice_name: str
    runner: str
    certified: bool
    agreement_rate: float | None
    disagreement_rate: float | None
    kill_threshold: float
    reason: str
    recommended_config: dict[str, object] | None


def _enable_config_for(slice_name: str) -> dict[str, object]:
    """The minimal config mapping that enables ONLY ``slice_name`` for local offload.

    Shaped to satisfy ``SwitchboardConfig.from_mapping``: ``less_token_mode`` ON (the global
    gate), exactly this one call site enabled, and ``max_tokens`` lifted to the reasoning-safe
    ceiling. Other slices are simply absent — ``is_call_site_enabled`` is disabled-by-default for
    any task_class not in the map, so we do not need to list them as ``False`` here.
    """
    return {
        "less_token_mode": True,
        "enabled_call_sites": {slice_name: True},
        "max_tokens": RECOMMENDED_MAX_TOKENS,
    }


def _find_runner(report: BakeoffReport, runner: str) -> RunnerReport:
    for r in report.runners:
        if r.runner == runner:
            return r
    present = sorted(r.runner for r in report.runners)
    raise ValueError(f"runner {runner!r} not in bake-off report (runners present: {present})")


def certify_slice(report: BakeoffReport, runner: str) -> CertVerdict:
    """Decide whether ``runner`` is certified to offload ``report``'s slice locally.

    Deterministic and pure: the verdict is a function of the bake-off report alone (no network, no
    clock, no model), so the same report always yields the same ``CertVerdict``.

    CERTIFIED iff the candidate did NOT kill AND it actually verdicted at least one case (an
    all-defer runner is never certified — it offloaded nothing, so there is no evidence). On a
    certify, ``recommended_config`` is the minimal mapping that enables JUST this slice; on a
    do-not-enable it is ``None``.

    A do-not-enable result is a VALID, shippable outcome — this never raises for a "failed"
    candidate. It raises ``ValueError`` only when ``runner`` is not present in the report at all
    (a caller bug), distinct from a runner that ran and did not certify.
    """
    rr = _find_runner(report, runner)

    verdicted_something = rr.agreement_rate is not None
    certified = (not rr.kill) and verdicted_something

    if certified:
        reason = (
            f"CERTIFY: {runner!r} agreed with the reference on the {report.slice_name!r} slice "
            f"({rr.agreements}/{rr.verdicted} verdicted, disagreement "
            f"{_pct(rr.disagreement_rate)} <= threshold {rr.kill_threshold:.0%}) — safe to enable."
        )
        recommended: dict[str, object] | None = _enable_config_for(report.slice_name)
    elif not verdicted_something:
        reason = (
            f"DO-NOT-ENABLE (valid outcome): {runner!r} produced NO verdicts on the "
            f"{report.slice_name!r} slice (all deferred) — no evidence it is safe to offload. "
            "Not an error; the slice simply stays on Claude."
        )
        recommended = None
    else:
        reason = (
            f"DO-NOT-ENABLE (valid outcome): {runner!r} KILLED on the {report.slice_name!r} slice "
            f"(disagreement {_pct(rr.disagreement_rate)} > threshold {rr.kill_threshold:.0%}) — "
            "offloading would degrade verdict quality. Not an error; the slice stays on Claude."
        )
        recommended = None

    return CertVerdict(
        slice_name=report.slice_name,
        runner=runner,
        certified=certified,
        agreement_rate=rr.agreement_rate,
        disagreement_rate=rr.disagreement_rate,
        kill_threshold=rr.kill_threshold,
        reason=reason,
        recommended_config=recommended,
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"
