"""CLI judge entrypoint: --site/--slice equivalence, gating short-circuit, exit-0 contract.

The CLI is the seam a wired SKILL.md drives. The load-bearing guarantees:
  * gated INERT by default — an un-enabled site (or offload off) DEFERS with NO network;
  * exit code is ALWAYS 0 for a well-formed judge invocation (a defer is not an error);
  * stdout is exactly one JSON object the caller parses to decide verdict-vs-defer.

Like test_client, network is stubbed (patch_client) — these tests never call the endpoint.
``run_judge`` accepts an explicit ``config`` so we can drive the gate without env state.
"""

from __future__ import annotations

import copy
import json
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from switchboard.cli import (
    INSPECT_SCHEMA_VERSION,
    INSPECT_STATES,
    build_inspect_report,
    build_roles_report,
    main,
    run_judge,
)
from switchboard.config import SwitchboardConfig
from switchboard.health import ENDPOINT_STATUSES
from switchboard.metrics import METRICS, Metrics
from switchboard.observe import INSPECT_ROLE_FIELDS
from switchboard.registry import (
    ALLOWED_HOSTS,
    ALLOWED_ROLES,
    HOST_PIN_FIELDS,
    REGISTRY_ENV_VAR,
    REGISTRY_STATES,
    ROLE_JSON_FIELDS,
)
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
    absent home this fixture installs). ``inspect`` also reads ``~/.switchboard/receipts.jsonl``,
    so ``Path.home()``, ``HOME`` and ``USERPROFILE`` point at an empty temporary home too (the
    same three patches as ``tests/test_generate.py`` and ``tests/test_observe.py``).
    """
    monkeypatch.delenv("SWITCHBOARD_CONFIG", raising=False)
    monkeypatch.delenv(REGISTRY_ENV_VAR, raising=False)
    monkeypatch.setattr("switchboard.config._default_config_path", lambda: tmp_path / "absent.json")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))


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


def test_observatory_contract_matches_inspect_runtime_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract_path = Path(__file__).parents[1] / "docs" / "observatory-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    inspect_contract = contract["inspect"]
    monkeypatch.setattr("switchboard.cli.health", lambda config: _offline_health())

    assert inspect_contract["schema_version"] == INSPECT_SCHEMA_VERSION == 3
    assert inspect_contract["states"] == list(INSPECT_STATES)
    assert inspect_contract["endpoint_statuses"] == list(ENDPOINT_STATUSES)
    assert inspect_contract["registry_states"] == list(REGISTRY_STATES)
    # Key sets of the real reports, not copies: a field added to either report fails here.
    assert inspect_contract["report_fields"] == list(build_inspect_report().to_json())
    assert inspect_contract["roles_view_fields"] == list(build_roles_report())
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
    # An inspect row is the registry row plus its per-host observed value (Step R3).
    assert inspect_contract["role_fields"] == list(INSPECT_ROLE_FIELDS)
    assert INSPECT_ROLE_FIELDS == (*ROLE_JSON_FIELDS, "observed")
    assert inspect_contract["role_host_fields"] == list(HOST_PIN_FIELDS)
    row = build_roles_report()["roles"][0]  # type: ignore[index]
    assert list(row) == inspect_contract["role_fields"]
    for host in ALLOWED_HOSTS:
        assert list(row[host]) == inspect_contract["role_host_fields"]
    # No receipts in the (empty, temporary) home: every host reads unknown, never a value.
    assert row["observed"] == dict.fromkeys(ALLOWED_HOSTS, inspect_contract["observed_unknown"])
    assert list(build_inspect_report().to_json()["roles"][0]) == inspect_contract["role_fields"]  # type: ignore[index]


# --- inspect --roles --json: the committed registry table for an external driver ----------

_COMMITTED_REGISTRY = Path(__file__).parents[1] / "registry" / "models.json"
_CONTRACT = json.loads(
    (Path(__file__).parents[1] / "docs" / "observatory-contract.json").read_text(encoding="utf-8")
)["inspect"]


def _registry_doc() -> dict[str, Any]:
    doc = json.loads(_COMMITTED_REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return copy.deepcopy(doc)


def _write_registry(tmp_path: Path, doc: object, name: str = "models.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _no_probe(config: SwitchboardConfig) -> object:
    raise AssertionError(f"inspect --roles must not probe the endpoint: {config}")


def _roles_json(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    rc = main(["inspect", "--roles", "--json", *argv])
    report = json.loads(capsys.readouterr().out)
    assert isinstance(report, dict)
    return rc, report


def test_inspect_roles_json_prints_the_committed_registry_without_probe_or_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A broken config must not matter: the roles view reads only the registry.
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(broken))
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc, report = _roles_json(capsys)

    assert rc == 0
    assert report["schema_version"] == INSPECT_SCHEMA_VERSION == 3
    assert report["view"] == "roles"
    assert report["registry_state"] == "ok"
    assert report["source"] == f"repo:{_COMMITTED_REGISTRY.resolve()}"
    assert report["error"] is None
    assert [row["role"] for row in report["roles"]] == list(ALLOWED_ROLES)


def _invalid_registry(tmp_path: Path) -> Path:
    """The one invalid registry the CLI tests share: a bare alias on one row.

    The validation rules themselves are covered in test_registry.py; the CLI tests ask only
    whether an invalid registry reaches each read view as data.
    """
    doc = _registry_doc()
    doc["roles"]["reviewer"]["claude"]["model"] = "sonnet"
    return _write_registry(tmp_path, doc, name="invalid-models.json")


def test_inspect_roles_json_reports_an_invalid_registry_as_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red-on-garbage at the read verb: a bad row surfaces as invalid with exit 0, never as an
    # empty table that a driver would read as "nothing pinned".
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc, report = _roles_json(capsys, "--registry", str(_invalid_registry(tmp_path)))

    assert rc == 0
    assert report["registry_state"] == "invalid"
    assert report["schema_version"] == 3
    assert report["roles"] == []
    assert "bare alias" in report["error"]


def test_inspect_roles_json_reports_an_absent_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.json"
    rc, report = _roles_json(capsys, "--registry", str(missing))

    assert rc == 0
    assert report["registry_state"] == "absent"
    assert report["source"] == f"arg:{missing}"
    assert report["roles"] == []
    assert "not found" in report["error"]


def test_inspect_roles_human_output_lists_every_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc = main(["inspect", "--roles"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "registry: ok" in out
    assert "  registry source: " in out
    for role in ALLOWED_ROLES:
        assert f"role={role} " in out
    assert "role=builder claude=inherit/inherit codex=gpt-5.6-sol/medium" in out


def test_inspect_roles_human_output_reports_invalid_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["inspect", "--roles", "--registry", str(_invalid_registry(tmp_path))])
    out = capsys.readouterr().out

    assert rc == 0
    assert "registry: invalid" in out
    assert "  registry error: " in out
    assert "role=" not in out


def test_plain_inspect_text_prints_the_registry_even_when_config_is_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The human render of the full inspect report: a broken config must not hide the registry
    # lines or the role table (no early return in the config-error branch).
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    rc = main(["inspect", "--path", str(broken)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "== switchboard inspect ==" in out
    assert "  state: invalid" in out
    assert "  config error: " in out
    assert "  registry: ok" in out
    assert f"  registry source: repo:{_COMMITTED_REGISTRY.resolve()}" in out
    for role in ALLOWED_ROLES:
        assert f"role={role} " in out


def test_full_inspect_json_carries_the_registry_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "active.json"
    config.write_text(
        json.dumps({"enabled_call_sites": {"review-deep-style": True}}), encoding="utf-8"
    )
    monkeypatch.setattr("switchboard.cli.health", lambda config: _offline_health())

    rc = main(["inspect", "--json", "--path", str(config)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["schema_version"] == INSPECT_SCHEMA_VERSION
    assert sorted(report) == sorted(_CONTRACT["report_fields"])
    assert report["registry_state"] == "ok"
    assert report["registry_error"] is None
    assert [row["role"] for row in report["roles"]] == list(ALLOWED_ROLES)
    assert any("Role rows are requested registry values" in line for line in report["limitations"])
    # The registry never changes the per-site effective model: sites still use the default.
    assert report["sites"][0]["effective_model"] == "coder-30b"


def test_full_inspect_keeps_config_and_registry_failures_separate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("switchboard.cli.health", _no_probe)

    # Invalid config, ok registry: the role table is still reported.
    rc = main(["inspect", "--json", "--path", str(broken)])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert report["state"] == "invalid"
    assert report["registry_state"] == "ok"
    assert len(report["roles"]) == len(ALLOWED_ROLES)

    # Absent config, invalid registry: config facts survive and the registry error is named.
    monkeypatch.setattr("switchboard.cli.health", lambda config: _offline_health())
    rc = main(["inspect", "--json", "--registry", str(_invalid_registry(tmp_path))])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert report["state"] == "absent"
    assert report["registry_state"] == "invalid"
    assert report["roles"] == []
    assert report["registry_error"]


# --- The retired config keys: roles and claims are unknown keys now ------------------------


@pytest.mark.parametrize("key", ["roles", "claims"])
def test_config_subcommand_fails_on_a_retired_key_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str
) -> None:
    path = tmp_path / "retired.json"
    path.write_text(
        json.dumps({"enabled_call_sites": {"review-deep-style": True}, key: {}}),
        encoding="utf-8",
    )

    rc = main(["config", "--path", str(path)])
    captured = capsys.readouterr()

    assert rc != 0
    assert captured.out == ""
    assert "unknown config key" in captured.err
    assert repr(key) in captured.err


def test_judge_with_a_retired_roles_config_still_defers_exit_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "retired.json"
    path.write_text(
        json.dumps(
            {
                "enabled_call_sites": {"review-deep-style": True},
                "roles": {"reviewer": {"provider": "claude", "model": None}},
                "claims": {"c1": "MEASURED"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SWITCHBOARD_CONFIG", str(path))

    rc = main(["judge", "--site", "review-deep-style", "--prompt", "judge this"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)

    assert rc == 0
    assert out["defer"] is True
    assert out["reason_class"] == "config_error"
    assert "roles" in captured.err


def test_config_subcommand_report_has_no_roles_or_claims(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["config"])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "roles" not in report
    assert "claims" not in report
