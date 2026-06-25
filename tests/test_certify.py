"""Slice certification + the staged review-deep-style enable config (Phase B Step 2 / #236).

Three things are pinned here:

  * **Injected-disagreement kill** — drive ``run_shadow`` with a stubbed local judge that
    disagrees with the expected reference on > 20% of verdicted cases and assert it KILLS
    (``report.kill is True``, disagreement > 0.20); the inverse (under 0.20) does NOT kill. This
    reuses the same stubbed-HTTP boundary as ``test_harness`` — the shadow run is the engine the
    bake-off's live-local path delegates to, so the kill rule is exercised end-to-end.
  * **Cert helper end-to-end** — feed ``certify_slice`` a ``BakeoffReport`` where the candidate
    PASSES (-> ``certified`` + a non-None ``recommended_config``) and one where it FAILS / defers
    everything (-> not ``certified`` + ``recommended_config is None``). A do-not-enable is a valid,
    shippable outcome, never an exception.
  * **Staged-config round-trip** — ``load_config`` of the committed
    ``scripts/offload-config.review-deep-style.json`` enables review-deep-style, keeps
    build-step-style off, and pins ``max_tokens == 2000``.

Everything is network-free and home-dir-safe: the bake-off / cert paths are pure, and the only
file touched is the committed repo artifact (resolved via ``Path(__file__)``, never ``Path.home``).
"""

from __future__ import annotations

import io
import json as _json
from collections.abc import Callable
from pathlib import Path

import pytest

from switchboard.bakeoff import (
    BakeoffReport,
    RunnerReport,
    load_suite,
    run_bakeoff,
)
from switchboard.certify import RECOMMENDED_MAX_TOKENS, certify_slice
from switchboard.config import SwitchboardConfig, load_config
from switchboard.harness import ShadowCase, run_shadow
from tests.conftest import (
    FLAG_CONTENT,
    PASS_CONTENT,
    chat_envelope,
)

UrlopenStub = Callable[..., object]
ApplyStub = Callable[[UrlopenStub], None]

ENABLED = SwitchboardConfig(enabled_call_sites={"review-deep-style": True})

# The canonical suite + the committed staged config, resolved relative to the repo (never an
# absolute path, never Path.home). suites/ and scripts/ are siblings of tests/'s parent.
_PKG_PARENT = Path(__file__).resolve().parent.parent
SUITE_PATH = _PKG_PARENT / "suites" / "review-deep-style.json"
STAGED_CONFIG_PATH = _PKG_PARENT / "scripts" / "offload-config.review-deep-style.json"


# --- Injected-disagreement kill via run_shadow -------------------------------------------


def _alternating_urlopen(envelopes: list[dict[str, object]]) -> UrlopenStub:
    """A urlopen stub that returns ``envelopes[i]`` on the i-th call (drives per-case verdicts)."""
    calls = {"i": 0}

    class _Resp:
        def __init__(self, body: bytes) -> None:
            self._b = io.BytesIO(body)

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            self._b.close()

        def read(self) -> bytes:
            return self._b.read()

    def _stub(req: object, timeout: float | None = None) -> _Resp:
        body = _json.dumps(envelopes[calls["i"]]).encode("utf-8")
        calls["i"] += 1
        return _Resp(body)

    return _stub


def test_injected_disagreement_above_threshold_kills(patch_client: ApplyStub) -> None:
    # 5 verdicted cases; the local judge disagrees on 2 (40% > 20%) -> KILL. The stub returns
    # FLAG on the two cases that expect pass; PASS on the rest.
    envelopes = [
        chat_envelope(PASS_CONTENT),  # case 0 expects pass -> agree
        chat_envelope(PASS_CONTENT),  # case 1 expects pass -> agree
        chat_envelope(PASS_CONTENT),  # case 2 expects pass -> agree
        chat_envelope(FLAG_CONTENT),  # case 3 expects pass -> DISAGREE
        chat_envelope(FLAG_CONTENT),  # case 4 expects pass -> DISAGREE
    ]
    patch_client(_alternating_urlopen(envelopes))
    cases = [ShadowCase(f"d{i}", expected="pass", label=f"d{i}") for i in range(5)]
    report = run_shadow(cases, config=ENABLED, task_class="review-deep-style")

    assert report.verdicted == 5
    assert report.disagreements == 2
    assert report.disagreement_rate is not None
    assert report.disagreement_rate > 0.20
    assert report.kill is True
    assert "REVERT" in report.kill_reason


def test_injected_disagreement_below_threshold_does_not_kill(patch_client: ApplyStub) -> None:
    # Same engine, 5 cases, exactly 1 disagreement = 20% — at the threshold, NOT above -> no kill
    # (the kill rule is strictly greater-than). Asserts the inverse of the test above.
    envelopes = [
        chat_envelope(PASS_CONTENT),  # agree
        chat_envelope(PASS_CONTENT),  # agree
        chat_envelope(PASS_CONTENT),  # agree
        chat_envelope(PASS_CONTENT),  # agree
        chat_envelope(FLAG_CONTENT),  # the 1 disagreement (expects pass)
    ]
    patch_client(_alternating_urlopen(envelopes))
    cases = [ShadowCase(f"d{i}", expected="pass", label=f"d{i}") for i in range(5)]
    report = run_shadow(cases, config=ENABLED, task_class="review-deep-style")

    assert report.verdicted == 5
    assert report.disagreements == 1
    assert report.disagreement_rate == pytest.approx(0.20)
    assert report.kill is False


# --- Cert helper end-to-end over BakeoffReports ------------------------------------------


def _bakeoff() -> BakeoffReport:
    """The canonical recorded suite: 'local' PASSES (1/7 disagreement), 'weak' FAILS (3/7)."""
    return run_bakeoff(load_suite(SUITE_PATH))


def test_certify_passing_candidate_yields_enable_config() -> None:
    report = _bakeoff()
    verdict = certify_slice(report, "local")

    assert verdict.certified is True
    assert verdict.slice_name == "review-deep-style"
    assert verdict.runner == "local"
    assert verdict.recommended_config is not None
    # The recommended config enables JUST this slice, keeps the reasoning-safe max_tokens, and
    # round-trips through from_mapping into a config that offloads only review-deep-style.
    cfg = SwitchboardConfig.from_mapping(verdict.recommended_config)
    assert cfg.is_call_site_enabled("review-deep-style") is True
    assert cfg.is_call_site_enabled("build-step-style") is False
    assert cfg.max_tokens == RECOMMENDED_MAX_TOKENS
    assert "CERTIFY" in verdict.reason


def test_do_not_enable_is_a_valid_outcome_not_an_error() -> None:
    # 'weak' kills (3/7 disagreement > 20%): a do-not-enable verdict, NOT a raised exception.
    report = _bakeoff()
    verdict = certify_slice(report, "weak")

    assert verdict.certified is False
    assert verdict.recommended_config is None
    assert verdict.disagreement_rate is not None
    assert verdict.disagreement_rate > 0.20
    assert "DO-NOT-ENABLE" in verdict.reason


def _all_defer_report(slice_name: str = "review-deep-style") -> BakeoffReport:
    """A minimal report whose candidate 'local' deferred every case (agreement_rate is None)."""
    candidate = RunnerReport(
        runner="local",
        is_reference=False,
        total=3,
        verdicted=0,
        deferred=3,
        agreements=0,
        disagreements=0,
        agreement_rate=None,
        disagreement_rate=None,
        mean_cost_usd=None,
        mean_latency_s=None,
        kill_threshold=0.20,
        kill=False,  # an all-defer runner cannot kill — which is why "did not kill" is not enough
        kill_reason="no verdicts produced (all deferred)",
    )
    return BakeoffReport(
        slice_name=slice_name,
        reference_runner="opus",
        kill_threshold=0.20,
        n_cases=3,
        runners=(candidate,),
    )


def test_all_defer_candidate_does_not_certify() -> None:
    # The candidate did NOT kill but produced ZERO verdicts: certifying nothing. This is exactly
    # the gap that "did not kill" alone would wrongly pass, so the helper requires a real verdict.
    verdict = certify_slice(_all_defer_report(), "local")
    assert verdict.certified is False
    assert verdict.recommended_config is None
    assert "all deferred" in verdict.reason


def test_certify_unknown_runner_raises() -> None:
    # An absent runner is a CALLER bug (distinct from a runner that ran and did not certify).
    report = _bakeoff()
    with pytest.raises(ValueError, match="not in bake-off report"):
        certify_slice(report, "nonexistent")


# --- Staged enable config round-trip (the committed repo artifact) ------------------------


def test_staged_review_deep_style_config_round_trips() -> None:
    # Resolved relative to the repo via Path(__file__) — never an absolute path, never Path.home.
    cfg, source = load_config(str(STAGED_CONFIG_PATH))

    assert source == f"arg:{STAGED_CONFIG_PATH}"
    assert cfg.is_call_site_enabled("review-deep-style") is True
    assert cfg.is_call_site_enabled("build-step-style") is False
    assert cfg.max_tokens == 2000
    # The certified recommendation and the committed artifact agree on the enable shape — the
    # staged file IS what certify_slice would recommend for this slice.
    recommended = certify_slice(_bakeoff(), "local").recommended_config
    assert recommended is not None
    round_tripped = SwitchboardConfig.from_mapping(recommended)
    assert round_tripped.max_tokens == cfg.max_tokens
    assert round_tripped.is_call_site_enabled("review-deep-style") is True
