"""Auto-disable-on-kill: the consumer that reverts a DEPLOYED slice when it kills.

Two layers, both effect-based (assert via the project's own ``load_config`` / the raw config
file, never merely that ``kill`` was computed):

  * unit tests of ``disable_slice_on_kill`` — kill reverts the slice, no-kill is a no-op, OTHER
    slices + top-level fields survive byte-for-value, a model-name-string slice value is handled,
    a schema-invalid config is refused (validate-before-write), the write is ATOMIC (a mid-write
    failure leaves the original intact), and a malformed/missing/non-object config degrades
    gracefully (never crashes the caller);
  * an integration test through the production caller ``monitor_deployed_slice`` — a live
    ``run_shadow`` disagreement forces a real ``kill`` that reaches the disable end-to-end,
    proving the wiring (not just the consumer in isolation).

The live path is driven through the SAME stubbed HTTP boundary as ``test_harness`` (real
captured PASS shape); no network is touched.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from switchboard.config import load_config
from switchboard.harness import ShadowCase, ShadowReport
from switchboard.monitor import disable_slice_on_kill, monitor_deployed_slice
from tests.conftest import PASS_CONTENT, chat_envelope, make_json_urlopen

UrlopenStub = Callable[..., object]
ApplyStub = Callable[[UrlopenStub], None]


# --- Helpers -----------------------------------------------------------------------------


def _report(*, kill: bool) -> ShadowReport:
    """A minimal ShadowReport carrying the given kill bit — the consumer only reads ``.kill``."""
    return ShadowReport(
        total=1,
        verdicted=1,
        deferred=0,
        agreements=0 if kill else 1,
        disagreements=1 if kill else 0,
        agreement_rate=0.0 if kill else 1.0,
        disagreement_rate=1.0 if kill else 0.0,
        quota_saved=1,
        kill_threshold=0.20,
        kill=kill,
        kill_reason="test",
        avg_elapsed_s=None,
    )


def _write_config(path: Path, sites: dict[str, object], **extra: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"enabled_call_sites": sites, **extra}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- Unit: kill reverts the slice; effect asserted via the project's own load_config -------


def test_disable_on_kill_reverts_slice(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path / "config.json", {"target": True})
    result = disable_slice_on_kill(cfg_path, "target", report=_report(kill=True))

    assert result.disabled is True
    assert result.error is None
    # Effect-based: the DEPLOYED config now defers this slice to Claude.
    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.is_call_site_enabled("target") is False


def test_disable_via_bare_kill_bool(tmp_path: Path) -> None:
    # The consumer accepts the kill bool directly (no full ShadowReport on hand).
    cfg_path = _write_config(tmp_path / "config.json", {"target": True})
    result = disable_slice_on_kill(cfg_path, "target", kill=True)

    assert result.disabled is True
    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.is_call_site_enabled("target") is False


# --- Unit: no-kill is a pure no-op --------------------------------------------------------


def test_no_kill_is_noop(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path / "config.json", {"target": True})
    before = cfg_path.read_text(encoding="utf-8")

    result = disable_slice_on_kill(cfg_path, "target", report=_report(kill=False))

    assert result.disabled is False
    assert result.error is None
    # Slice stays enabled and the file is untouched.
    assert cfg_path.read_text(encoding="utf-8") == before
    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.is_call_site_enabled("target") is True


# --- Unit: scoped — every OTHER slice + top-level field preserved byte-for-value -----------


def test_other_slices_and_top_level_fields_preserved(tmp_path: Path) -> None:
    cfg_path = _write_config(
        tmp_path / "config.json",
        {"target": True, "keeper": True},
        less_token_mode=True,
        model="general-35b",
        max_tokens=2000,
        base_url="http://localhost:8080/v1",
        effort={"target": "high", "keeper": "low"},
    )
    raw_before = json.loads(cfg_path.read_text(encoding="utf-8"))

    result = disable_slice_on_kill(cfg_path, "target", report=_report(kill=True))
    assert result.disabled is True

    raw_after = json.loads(cfg_path.read_text(encoding="utf-8"))
    # ONLY the tripped slice flipped; the sibling slice is untouched.
    assert raw_after["enabled_call_sites"]["target"] is False
    assert raw_after["enabled_call_sites"]["keeper"] is True
    # Every other top-level field is preserved byte-for-value.
    for key in ("less_token_mode", "model", "max_tokens", "base_url", "effort"):
        assert raw_after[key] == raw_before[key]
    # And the disabled config still loads + validates.
    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.max_tokens == 2000
    assert reloaded.effort_for("target") == "high"
    assert reloaded.is_call_site_enabled("keeper") is True


# --- Unit: a model-name-string slice value is handled -------------------------------------


def test_model_name_string_slice_value_handled(tmp_path: Path) -> None:
    # An enabled-via-pinned-model slice (str value) must still flip to False; a SIBLING
    # model-string slice must survive with its pinned model intact.
    cfg_path = _write_config(
        tmp_path / "config.json",
        {"target": "general-35b", "keeper": "coder-30b"},
    )
    result = disable_slice_on_kill(cfg_path, "target", report=_report(kill=True))
    assert result.disabled is True

    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.is_call_site_enabled("target") is False
    assert reloaded.is_call_site_enabled("keeper") is True
    assert reloaded.model_for("keeper") == "coder-30b"


# --- Unit: fail-safe — malformed / missing / no-signal degrade, never crash ----------------


def test_missing_config_degrades_gracefully(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    result = disable_slice_on_kill(missing, "target", kill=True)

    assert result.disabled is False
    assert result.error is not None
    assert not missing.exists()  # never conjured a file


def test_malformed_json_degrades_gracefully(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")

    result = disable_slice_on_kill(bad, "target", kill=True)

    assert result.disabled is False
    assert result.error is not None
    # The unreadable file is left exactly as-is (never overwritten with something worse).
    assert bad.read_text(encoding="utf-8") == "{ not valid json"


def test_no_signal_returns_error_without_touching_file(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path / "config.json", {"target": True})
    before = cfg_path.read_text(encoding="utf-8")

    result = disable_slice_on_kill(cfg_path, "target")  # neither report= nor kill=

    assert result.disabled is False
    assert result.error is not None
    assert cfg_path.read_text(encoding="utf-8") == before


def test_schema_invalid_config_refused_and_left_intact(tmp_path: Path) -> None:
    # Valid JSON but SCHEMA-invalid (max_tokens below MIN_MAX_TOKENS): the disable must refuse to
    # persist a config the project's own validator would reject, and leave the file byte-for-byte.
    cfg_path = _write_config(tmp_path / "config.json", {"target": True}, max_tokens=100)
    before = cfg_path.read_text(encoding="utf-8")

    result = disable_slice_on_kill(cfg_path, "target", kill=True)

    assert result.disabled is False
    assert result.error is not None
    assert cfg_path.read_text(encoding="utf-8") == before


def test_atomic_write_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The write must be atomic: if the swap fails AFTER the temp file is written, the ORIGINAL
    # deployed config is preserved byte-for-byte (never truncated) and no temp file is leaked.
    cfg_path = _write_config(tmp_path / "config.json", {"target": True, "keeper": True})
    before = cfg_path.read_text(encoding="utf-8")

    def _boom(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _boom)

    result = disable_slice_on_kill(cfg_path, "target", report=_report(kill=True))

    assert result.disabled is False
    assert result.error is not None
    # Original intact — the in-place truncation footgun is closed.
    assert cfg_path.read_text(encoding="utf-8") == before
    # No leaked temp file beside the config.
    assert list(tmp_path.iterdir()) == [cfg_path]


def test_top_level_not_object_degrades_gracefully(tmp_path: Path) -> None:
    # A valid-JSON but non-object top level (a list) must degrade, not crash or write.
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    before = bad.read_text(encoding="utf-8")

    result = disable_slice_on_kill(bad, "target", kill=True)

    assert result.disabled is False
    assert result.error is not None
    assert bad.read_text(encoding="utf-8") == before


def test_enabled_call_sites_not_object_degrades_gracefully(tmp_path: Path) -> None:
    # enabled_call_sites present but the wrong type (a list) must degrade, not crash or write.
    bad = tmp_path / "config.json"
    bad.write_text(json.dumps({"enabled_call_sites": [1, 2, 3]}), encoding="utf-8")
    before = bad.read_text(encoding="utf-8")

    result = disable_slice_on_kill(bad, "target", kill=True)

    assert result.disabled is False
    assert result.error is not None
    assert bad.read_text(encoding="utf-8") == before


# --- Integration: through the production caller monitor_deployed_slice ---------------------


def test_monitor_deployed_slice_auto_disables_on_kill(
    patch_client: ApplyStub, tmp_path: Path
) -> None:
    # Live run: the stub always verdicts PASS while both cases expect FLAG -> 100% disagreement
    # -> kill. The kill must reach the consumer and disable the DEPLOYED slice end-to-end.
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    cfg_path = _write_config(
        tmp_path / "config.json",
        {"review-deep-style": True, "other-slice": True},
    )
    cases = [
        ShadowCase("diff a", expected="flag", label="a"),
        ShadowCase("diff b", expected="flag", label="b"),
    ]

    report, result = monitor_deployed_slice(
        cases, task_class="review-deep-style", config_path=cfg_path
    )

    assert report.kill is True
    assert result.disabled is True
    # Effect-based end-to-end: the deployed config now defers the tripped slice to Claude...
    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.is_call_site_enabled("review-deep-style") is False
    # ...and the untripped sibling slice is left deployed.
    assert reloaded.is_call_site_enabled("other-slice") is True


def test_monitor_deployed_slice_no_kill_leaves_slice_enabled(
    patch_client: ApplyStub, tmp_path: Path
) -> None:
    # Agreement (stub PASS, case expects pass) -> no kill -> the slice stays deployed.
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    cfg_path = _write_config(tmp_path / "config.json", {"review-deep-style": True})
    cases = [ShadowCase("diff a", expected="pass", label="a")]

    report, result = monitor_deployed_slice(
        cases, task_class="review-deep-style", config_path=cfg_path
    )

    assert report.kill is False
    assert result.disabled is False
    reloaded, _ = load_config(str(cfg_path))
    assert reloaded.is_call_site_enabled("review-deep-style") is True


def test_monitor_broken_config_is_noop_and_leaves_file_intact(tmp_path: Path) -> None:
    # A broken deployed config must degrade WITHOUT crashing: the ConfigError-on-load falls back
    # to the inert all-defer path (cannot kill), so the disable step is a no-op (error=None) and
    # the unreadable file is left exactly as-is. No network stub needed — nothing reaches it.
    bad = tmp_path / "config.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    cases = [ShadowCase("diff a", expected="flag", label="a")]

    report, result = monitor_deployed_slice(cases, task_class="review-deep-style", config_path=bad)

    assert report.kill is False
    assert result.disabled is False
    assert result.error is None  # no-op branch: nothing was attempted against the file
    assert bad.read_text(encoding="utf-8") == "{ not valid json"
