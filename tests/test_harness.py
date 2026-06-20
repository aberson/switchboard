"""Shadow-mode harness: agreement, quota-saved, defer handling, and the kill criterion.

Uses the same stubbed HTTP boundary as test_client (real captured PASS/FLAG shapes). The
harness must: count quota saved from real verdicts only, treat defers as fall-backs (not
disagreements), and KILL when local-vs-expected disagreement exceeds the threshold. The
inert-by-default path (offload off -> all defer, quota 0, no kill) is a first-class test.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from switchboard.config import SwitchboardConfig
from switchboard.harness import DEFAULT_KILL_THRESHOLD, ShadowCase, run_shadow
from switchboard.metrics import Metrics
from tests.conftest import (
    FLAG_CONTENT,
    PASS_CONTENT,
    chat_envelope,
    make_json_urlopen,
    make_raising_urlopen,
)

UrlopenStub = Callable[..., object]
ApplyStub = Callable[[UrlopenStub], None]

ENABLED = SwitchboardConfig(enabled_call_sites={"style-lens": True})


# --- All-agree: every local verdict matches expected -> high agreement, no kill ----------


def test_all_agree_full_quota_saved(patch_client: ApplyStub) -> None:
    # Stub always returns PASS; both cases expect pass -> 100% agreement, 2 quota saved.
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    cases = [
        ShadowCase("diff a", expected="pass", label="a"),
        ShadowCase("diff b", expected="pass", label="b"),
    ]
    report = run_shadow(cases, config=ENABLED, task_class="style-lens")

    assert report.total == 2
    assert report.verdicted == 2
    assert report.deferred == 0
    assert report.agreements == 2
    assert report.agreement_rate == 1.0
    assert report.quota_saved == 2
    assert report.kill is False


# --- Disagreement above threshold -> KILL ------------------------------------------------


def test_disagreement_above_threshold_kills(patch_client: ApplyStub) -> None:
    # Stub always returns PASS; both cases expect FLAG -> 100% disagreement -> kill.
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    cases = [
        ShadowCase("diff a", expected="flag"),
        ShadowCase("diff b", expected="flag"),
    ]
    report = run_shadow(cases, config=ENABLED, task_class="style-lens")

    assert report.verdicted == 2
    assert report.agreements == 0
    assert report.disagreement_rate == 1.0
    assert report.kill is True
    assert "REVERT" in report.kill_reason


def test_disagreement_below_threshold_does_not_kill() -> None:
    # 4 cases, 1 disagreement = 25% > 20% default -> would kill. Use a looser threshold so
    # the SAME data does NOT kill, proving the threshold is honored. We drive verdicts via
    # alternating stub responses through a per-call counter.
    import switchboard.client as client_mod

    responses = [
        chat_envelope(PASS_CONTENT),  # agree (expect pass)
        chat_envelope(PASS_CONTENT),  # agree
        chat_envelope(PASS_CONTENT),  # agree
        chat_envelope(FLAG_CONTENT),  # disagree (expect pass)
    ]
    calls = {"i": 0}

    import io
    import json as _json

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
        body = _json.dumps(responses[calls["i"]]).encode("utf-8")
        calls["i"] += 1
        return _Resp(body)

    import urllib.request

    orig = urllib.request.urlopen
    urllib.request.urlopen = _stub  # type: ignore[assignment]
    try:
        cases = [ShadowCase(f"d{i}", expected="pass") for i in range(4)]
        report = run_shadow(
            cases, config=ENABLED, task_class="style-lens", kill_threshold=0.30
        )
    finally:
        urllib.request.urlopen = orig  # type: ignore[assignment]

    assert client_mod  # imported for clarity that we drive the real client
    assert report.verdicted == 4
    assert report.disagreements == 1
    assert report.disagreement_rate == 0.25
    assert report.kill is False  # 25% <= 30% threshold


# --- Defers are NOT disagreements: they fall back to Claude, save no quota ---------------


def test_defers_excluded_from_agreement_and_quota(patch_client: ApplyStub) -> None:
    # Endpoint refuses every call -> every case DEFERS. No verdicts, no quota saved, no kill.
    import urllib.error

    refused = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    patch_client(make_raising_urlopen(refused))
    cases = [ShadowCase("a", expected="pass"), ShadowCase("b", expected="flag")]
    report = run_shadow(cases, config=ENABLED, task_class="style-lens")

    assert report.deferred == 2
    assert report.verdicted == 0
    assert report.agreement_rate is None
    assert report.quota_saved == 0
    assert report.kill is False
    assert "all deferred" in report.kill_reason


# --- Inert by default: offload OFF -> all defer, no network, quota 0, no kill -------------


def test_inert_when_offload_off() -> None:
    # No patch_client: a network touch would fail. less_token_mode OFF must short-circuit.
    cfg = SwitchboardConfig(less_token_mode=False)
    cases = [ShadowCase("a", expected="pass"), ShadowCase("b", expected="flag")]
    report = run_shadow(cases, config=cfg, task_class="style-lens")

    assert report.deferred == 2
    assert report.verdicted == 0
    assert report.quota_saved == 0
    assert report.kill is False
    for o in report.outcomes:
        assert o.reason_class == "disabled"


def test_inert_when_site_disabled() -> None:
    cfg = SwitchboardConfig(enabled_call_sites={"build-step-style": False})
    cases = [ShadowCase("a", expected="pass")]
    report = run_shadow(cases, config=cfg, task_class="build-step-style")
    assert report.deferred == 1
    assert report.quota_saved == 0


# --- Metrics isolation + quota-accounting consistency ------------------------------------


def test_uses_isolated_metrics_by_default(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    report = run_shadow(
        [ShadowCase("a", expected="pass")], config=ENABLED, task_class="style-lens"
    )
    # A fresh internal counter -> quota_saved reflects only this run's single verdict.
    assert report.quota_saved == 1


def test_explicit_metrics_threaded_through(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    m = Metrics()
    run_shadow(
        [ShadowCase("a", expected="pass")],
        config=ENABLED,
        task_class="style-lens",
        metrics=m,
    )
    assert m.verdict_total == 1


# --- Validation + report rendering -------------------------------------------------------


def test_bad_kill_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        run_shadow([], kill_threshold=1.5)


def test_summary_lines_render(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    report = run_shadow(
        [ShadowCase("a", expected="pass")], config=ENABLED, task_class="style-lens"
    )
    lines = report.summary_lines()
    joined = "\n".join(lines)
    assert "quota saved:" in joined
    assert "KILL:" in joined


def test_default_threshold_constant() -> None:
    assert DEFAULT_KILL_THRESHOLD == 0.20
