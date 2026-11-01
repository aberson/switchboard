"""CLI judge entrypoint: --site/--slice equivalence, gating short-circuit, exit-0 contract.

The CLI is the seam a wired SKILL.md drives. The load-bearing guarantees:
  * gated INERT by default — an un-enabled site (or offload off) DEFERS with NO network;
  * exit code is ALWAYS 0 for a well-formed judge invocation (a defer is not an error);
  * stdout is exactly one JSON object the caller parses to decide verdict-vs-defer.

Like test_client, network is stubbed (patch_client) — these tests never call the endpoint.
``run_judge`` accepts an explicit ``config`` so we can drive the gate without env state.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from pathlib import Path

import pytest

from switchboard.cli import INSPECT_SCHEMA_VERSION, INSPECT_STATES, main, run_judge
from switchboard.config import ALLOWED_ROLES, ROLE_PIN_FIELDS, SwitchboardConfig
from switchboard.health import ENDPOINT_STATUSES
from switchboard.metrics import METRICS, Metrics
from tests.conftest import (
    PASS_CONTENT,
    chat_envelope,
    make_json_urlopen,
    make_raising_urlopen,
)

UrlopenStub = Callable[..., object]
ApplyStub = Callable[[UrlopenStub], None]


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``main()`` now calls ``load_config()``; keep every CLI test hermetic from the operator's
    real ``$SWITCHBOARD_CONFIG`` and ``~/.switchboard/config.json``. Tests that exercise the
    loader opt back in by re-setting the env / passing --path (an explicit source beats the
    absent home this fixture installs).
    """
    monkeypatch.delenv("SWITCHBOARD_CONFIG", raising=False)
    monkeypatch.setattr("switchboard.config._default_config_path", lambda: tmp_path / "absent.json")


# --- run_judge: gating short-circuit is inert (no network) -------------------------------


def test_run_judge_defers_when_offload_off() -> None:
    # No patch_client: a network touch would hit an absent endpoint and fail the test.
    cfg = SwitchboardConfig(less_token_mode=False)
    m = Metrics()
    result = run_judge(slice_name="review-deep-style", prompt="judge this", config=cfg, metrics=m)

    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == "disabled"  # type: ignore[typeddict-item]
    assert m.defers["disabled"] == 1


def test_run_judge_defers_when_site_disabled() -> None:
    # less_token_mode ON, but this site is explicitly disabled (the build-step-style case).
    cfg = SwitchboardConfig(less_token_mode=True, enabled_call_sites={"build-step-style": False})
    result = run_judge(slice_name="build-step-style", prompt="judge this", config=cfg)
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == "disabled"  # type: ignore[typeddict-item]


def test_run_judge_routes_local_when_site_enabled(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    cfg = SwitchboardConfig(enabled_call_sites={"review-deep-style": True})
    m = Metrics()
    result = run_judge(slice_name="review-deep-style", prompt="judge this", config=cfg, metrics=m)
    assert result["verdict"] == "pass"  # type: ignore[typeddict-item]
    assert m.verdicts["pass"] == 1


# --- main(): exit-0 contract + one-JSON-object stdout ------------------------------------


def test_main_disabled_site_exits_0_prints_defer(capsys: pytest.CaptureFixture[str]) -> None:
    # Default config: no call sites enabled, so any --site defers without network. Exit 0.
    rc = main(["judge", "--site", "review-deep-style", "--prompt", "judge this"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defer"] is True
    assert out["reason_class"] == "disabled"


def test_main_slice_alias_equivalent_to_site(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["judge", "--slice", "review-deep-style", "--prompt", "x"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defer"] is True


def test_main_requires_exactly_one_of_site_or_slice() -> None:
    # Neither given -> argparse usage error (a caller bug, distinct from a defer).
    with pytest.raises(SystemExit) as exc:
        main(["judge", "--prompt", "x"])
    assert exc.value.code != 0


def test_main_site_and_slice_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["judge", "--site", "a", "--slice", "b", "--prompt", "x"])
    assert exc.value.code != 0


def test_main_stdout_is_single_json_object(capsys: pytest.CaptureFixture[str]) -> None:
    main(["judge", "--site", "review-deep-style", "--prompt", "x"])
    out = capsys.readouterr().out
    # Exactly one JSON object then a trailing newline — the caller does json.loads(out).
    assert out.endswith("\n")
    json.loads(out)  # raises if not exactly one object


def test_read_prompt_precedence_prompt_over_file(tmp_path: pytest.TempPathFactory) -> None:
    from switchboard.cli import _read_prompt

    p = tmp_path / "prompt.txt"  # type: ignore[operator]
    p.write_text("from-file", encoding="utf-8")
    # Explicit --prompt wins over --prompt-file.
    assert _read_prompt(str(p), "from-string") == "from-string"
    assert _read_prompt(str(p), None) == "from-file"


# --- Step 2: defer-safe config load on the judge hot path --------------------------------


def test_main_judge_missing_config_defers_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A broken (missing) $SWITCHBOARD_CONFIG must NOT crash the judge: stdout gets a
    # config_error defer, exit is 0, and a non-empty warning goes to stderr (not stdout).
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(tmp_path / "missing.json"))
    rc = main(["judge", "--site", "review-deep-style", "--prompt", "x"])
    assert rc == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)  # exactly one JSON object on stdout
    assert out["defer"] is True
    assert out["reason_class"] == "config_error"
    assert captured.err.strip() != ""  # warning went to stderr


def test_main_judge_malformed_config_defers_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(bad))
    rc = main(["judge", "--site", "review-deep-style", "--prompt", "x"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["reason_class"] == "config_error"


def test_main_judge_config_error_records_metric(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The config_error defer is counted into the module METRICS like every other defer reason.
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(tmp_path / "missing.json"))
    before = METRICS.defers["config_error"]
    main(["judge", "--site", "review-deep-style", "--prompt", "x"])
    assert METRICS.defers["config_error"] == before + 1


def test_main_judge_missing_prompt_file_defers_safely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A provided-but-missing --prompt-file is well-formed per argparse, so the judge must defer
    # (exit 0, one JSON object on stdout) rather than crash with a traceback.
    rc = main(["judge", "--site", "review-deep-style", "--prompt-file", str(tmp_path / "nope.txt")])
    assert rc == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["defer"] is True
    assert out["reason_class"] == "input_error"
    assert captured.err.strip() != ""  # warning to stderr


def test_main_judge_bad_encoding_prompt_file_defers_safely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "prompt-bad-utf8.txt"
    bad.write_bytes(b"\xff\xfe not valid utf-8")
    rc = main(["judge", "--site", "review-deep-style", "--prompt-file", str(bad)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defer"] is True
    assert out["reason_class"] == "input_error"


def test_main_loaded_config_reaches_local_judge(
    patch_client: ApplyStub,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # INTEGRATION through the production caller (main -> load_config -> run_judge -> local_judge).
    # A config file ENABLES review-deep-style; the network is stubbed to RAISE URLError. If the
    # loaded config reached local_judge and flipped offload_allowed, we get PAST the disabled
    # short-circuit and hit the network -> defer reason_class == "unreachable" (NOT "disabled").
    # If the wiring were broken (config not threaded through), the default config would short-
    # circuit with "disabled" — so asserting "unreachable" proves the seam end-to-end.
    cfgfile = tmp_path / "on.json"
    cfgfile.write_text(
        json.dumps({"enabled_call_sites": {"review-deep-style": True}}), encoding="utf-8"
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(cfgfile))
    patch_client(make_raising_urlopen(urllib.error.URLError("connection refused")))
    rc = main(["judge", "--site", "review-deep-style", "--prompt", "x"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defer"] is True
    assert out["reason_class"] == "unreachable"  # reached the network => config was applied


# --- Step 2: the `config` subcommand (loud pre-flight) -----------------------------------


def test_config_subcommand_valid_exits_0_reports_source_and_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfgfile = tmp_path / "cfg.json"
    cfgfile.write_text(
        json.dumps({"enabled_call_sites": {"review-deep-style": True}}), encoding="utf-8"
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(cfgfile))
    rc = main(["config"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == f"env:{cfgfile}"
    assert report["offload_active"] is True
    assert "review-deep-style" in report["enabled_sites"]


def test_config_subcommand_broken_exits_nonzero_with_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(tmp_path / "missing.json"))
    rc = main(["config"])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""


def test_config_subcommand_defaults_when_unset(capsys: pytest.CaptureFixture[str]) -> None:
    # autouse _isolate_config unsets env + points home at an absent file => "defaults".
    rc = main(["config"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == "defaults"
    assert report["offload_active"] is False


def test_config_subcommand_reports_off_when_less_token_mode_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfgfile = tmp_path / "off.json"
    cfgfile.write_text(
        json.dumps({"less_token_mode": False, "enabled_call_sites": {"review-deep-style": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(cfgfile))
    rc = main(["config"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["offload_active"] is False
    assert report["enabled_sites"] == []


def test_config_subcommand_path_validates_specific_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --path validates an arbitrary file (D5): check /offload-scan's output before installing.
    cfgfile = tmp_path / "candidate.json"
    cfgfile.write_text(
        json.dumps({"enabled_call_sites": {"skill-iterate-grader": True}}), encoding="utf-8"
    )
    rc = main(["config", "--path", str(cfgfile)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == f"arg:{cfgfile}"
    assert "skill-iterate-grader" in report["enabled_sites"]


def test_config_subcommand_path_broken_file_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["config", "--path", str(tmp_path / "nope.json")])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""


# --- Step 71: inspect distinguishes config and bounded endpoint states ------------------


def _offline_health() -> dict[str, object]:
    return {
        "reachable": False,
        "models": [],
        "model_served": False,
        "error": "connection refused",
    }


def test_inspect_json_marks_absent_config_without_calling_it_zero_activity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("switchboard.cli.health", lambda config: _offline_health())
    rc = main(["inspect", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["state"] == "absent"
    assert report["config_state"] == "absent"
    assert report["source"] == "defaults"
    assert report["offload_active"] is False
    assert report["endpoint_status"] == "offline"


def test_inspect_json_reports_invalid_config_without_a_health_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(invalid))

    def should_not_probe(config: SwitchboardConfig) -> dict[str, object]:
        raise AssertionError(f"invalid config must not probe endpoint: {config}")

    monkeypatch.setattr("switchboard.cli.health", should_not_probe)
    rc = main(["inspect", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["state"] == "invalid"
    assert report["source"] == f"env:{invalid}"
    assert report["offload_active"] is None
    assert report["endpoint_status"] == "not-probed"
    assert report["error"]


def test_inspect_json_distinguishes_inactive_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "inactive.json"
    config.write_text(
        json.dumps({"less_token_mode": False, "enabled_call_sites": {"review-deep-style": True}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(config))
    monkeypatch.setattr(
        "switchboard.cli.health",
        lambda config: {
            "reachable": True,
            "models": ["coder-30b"],
            "model_served": True,
            "error": None,
        },
    )
    rc = main(["inspect", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["state"] == "inactive"
    assert report["offload_active"] is False
    assert report["sites"][0]["site_enabled"] is True
    assert report["sites"][0]["offload_allowed"] is False


def test_inspect_json_distinguishes_active_offline_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "active.json"
    config.write_text(
        json.dumps({"enabled_call_sites": {"review-deep-style": True}}), encoding="utf-8"
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(config))
    monkeypatch.setattr("switchboard.cli.health", lambda config: _offline_health())
    rc = main(["inspect", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["state"] == "active-offline"
    assert report["offload_active"] is True
    assert report["endpoint_status"] == "offline"


def test_inspect_json_reports_effective_model_effort_and_active_online_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "online.json"
    config.write_text(
        json.dumps(
            {
                "enabled_call_sites": {"review-deep-style": "pinned-model"},
                "effort": {"review-deep-style": "high"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(config))
    monkeypatch.setattr(
        "switchboard.cli.health",
        lambda config: {
            "reachable": True,
            "models": ["pinned-model"],
            "model_served": True,
            "error": None,
        },
    )
    rc = main(["inspect", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["state"] == "active-online"
    site = report["sites"][0]
    assert site["configured_model"] == "pinned-model"
    assert site["default_model"] == "coder-30b"
    assert site["effective_model"] == "pinned-model"
    assert site["effort_hint"] == "high"
    assert "not bake-off certification" in report["limitations"][0]


def test_observatory_contract_matches_inspect_runtime_shape() -> None:
    contract_path = Path(__file__).parents[1] / "docs" / "observatory-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    inspect_contract = contract["inspect"]

    assert inspect_contract["schema_version"] == INSPECT_SCHEMA_VERSION
    assert inspect_contract["states"] == list(INSPECT_STATES)
    assert inspect_contract["endpoint_statuses"] == list(ENDPOINT_STATUSES)
    assert inspect_contract["site_fields"] == [
        "site",
        "configured_value",
        "configured_model",
        "default_model",
        "effective_model",
        "site_enabled",
        "offload_allowed",
        "effort_hint",
    ]
    assert inspect_contract["role_fields"] == [
        "role",
        "configured",
        *ROLE_PIN_FIELDS,
        "claim_status",
    ]


# --- inspect --roles --json: report-only role pin table for an external driver -------------

_ROLES_CONFIG = {
    "less_token_mode": True,
    "enabled_call_sites": {"review-deep-style": True},
    "claims": {"lens-style-claim": "PARTIAL"},
    "roles": {
        "lens": {
            "provider": "local",
            "model": "other-local-model",
            "tier": "low",
            "claim_id": "lens-style-claim",
        },
        "driver": {"provider": None, "model": None, "tier": None, "claim_id": None},
    },
}


def _write_roles_config(tmp_path: Path, data: object = None) -> Path:
    path = tmp_path / "roles.json"
    path.write_text(json.dumps(_ROLES_CONFIG if data is None else data), encoding="utf-8")
    return path


def _no_probe(config: SwitchboardConfig) -> object:
    raise AssertionError(f"inspect --roles must not probe the endpoint: {config}")


def test_inspect_roles_json_prints_resolved_table_without_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_roles_config(tmp_path)
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc = main(["inspect", "--roles", "--json", "--path", str(path)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    contract = json.loads(
        (Path(__file__).parents[1] / "docs" / "observatory-contract.json").read_text(
            encoding="utf-8"
        )
    )["inspect"]
    assert sorted(report) == sorted(contract["roles_view_fields"])
    assert report["schema_version"] == INSPECT_SCHEMA_VERSION
    assert report["view"] == "roles"
    assert report["config_state"] == "valid"
    assert report["source"] == f"arg:{path}"
    assert report["error"] is None
    assert [row["role"] for row in report["roles"]] == list(ALLOWED_ROLES)
    for row in report["roles"]:
        assert sorted(row) == sorted(contract["role_fields"])

    by_role = {row["role"]: row for row in report["roles"]}
    assert by_role["lens"] == {
        "role": "lens",
        "configured": True,
        "provider": "local",
        "model": "other-local-model",
        "tier": "low",
        "claim_id": "lens-style-claim",
        "claim_status": "PARTIAL",
    }
    assert by_role["driver"]["configured"] is True
    assert by_role["driver"]["model"] is None
    # Unconfigured role: all null, and the default local model is NOT substituted.
    assert by_role["builder"] == {
        "role": "builder",
        "configured": False,
        "provider": None,
        "model": None,
        "tier": None,
        "claim_id": None,
        "claim_status": None,
    }


def test_inspect_roles_json_absent_config_is_all_null(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("switchboard.cli.health", _no_probe)
    rc = main(["inspect", "--roles", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["config_state"] == "absent"
    assert report["source"] == "defaults"
    assert all(row["configured"] is False and row["model"] is None for row in report["roles"])


@pytest.mark.parametrize(
    ("bad", "needle"),
    [
        ({"roles": {"reviewer": {"claim_id": "missing-claim"}}}, "names no claim"),
        ({"roles": {"coordinator": {}}}, "unknown role"),
    ],
)
def test_inspect_roles_json_reports_invalid_pins_as_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bad: dict[str, object],
    needle: str,
) -> None:
    # Red-on-garbage at the read verb: a bad pin surfaces as invalid, never as an empty
    # table that a driver would read as "nothing pinned".
    path = _write_roles_config(tmp_path, bad)
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc = main(["inspect", "--roles", "--json", "--path", str(path)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["config_state"] == "invalid"
    assert report["roles"] == []
    assert needle in report["error"]


def test_inspect_roles_human_output_lists_every_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_roles_config(tmp_path)
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc = main(["inspect", "--roles", "--path", str(path)])
    out = capsys.readouterr().out

    assert rc == 0
    for role in ALLOWED_ROLES:
        assert f"role={role} " in out
    assert "role=lens provider=local model=other-local-model tier=low" in out


def test_full_inspect_json_carries_roles_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_roles_config(tmp_path)
    monkeypatch.setattr("switchboard.cli.health", lambda config: _offline_health())

    rc = main(["inspect", "--json", "--path", str(path)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["schema_version"] == INSPECT_SCHEMA_VERSION
    assert [row["role"] for row in report["roles"]] == list(ALLOWED_ROLES)
    assert any("Role pins are report-only" in line for line in report["limitations"])
    # The role pin never changes the per-site effective model: sites still use the default.
    assert report["sites"][0]["effective_model"] == "coder-30b"


def test_config_subcommand_round_trips_roles_and_claims(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_roles_config(tmp_path)
    rc = main(["config", "--path", str(path)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["roles"] == _ROLES_CONFIG["roles"]
    assert report["claims"] == _ROLES_CONFIG["claims"]


def test_judge_ignores_role_pins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # local_judge must not act on roles: a lens pin naming another model leaves the request
    # model, timeout, and verdict path exactly as the site config dictates.
    path = _write_roles_config(tmp_path)
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(path))
    captured: dict[str, object] = {}

    def _capturing(req: object, timeout: float | None = None):  # type: ignore[no-untyped-def]
        captured["body"] = json.loads(req.data)  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        from tests.conftest import _FakeResponse

        return _FakeResponse(json.dumps(chat_envelope(PASS_CONTENT)).encode("utf-8"))

    monkeypatch.setattr("switchboard.client.urllib.request.urlopen", _capturing)

    rc = main(["judge", "--site", "review-deep-style", "--prompt", "judge this"])
    result = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert result["verdict"] == "pass"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "coder-30b"
    assert captured["timeout"] == SwitchboardConfig().warm_timeout_s
