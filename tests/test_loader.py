"""Unit tests for the config loader: ``from_mapping`` + ``load_config`` resolution order.

These tests are HERMETIC: the ``hermetic`` fixture unsets ``$SWITCHBOARD_CONFIG`` and points
the home-default helper at a guaranteed-absent path under ``tmp_path``, so a real
``~/.switchboard/config.json`` on the dev machine can never pollute a run (risk-table line:
"Hermetic tests vs. a real home config"). Tests opt back in by ``setenv`` / writing the home
file / passing an explicit path. No network is touched — the loader is pure file/env IO.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from switchboard.config import (
    ALLOWED_TOP_LEVEL_FIELDS,
    ENV_VAR,
    ConfigError,
    SwitchboardConfig,
    load_config,
)


@pytest.fixture
def hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Isolate ``load_config`` from the real environment + real ``~/.switchboard``.

    Returns the (initially absent) home-default path so home-tier tests can write to it.
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    home = tmp_path / "home" / ".switchboard" / "config.json"
    monkeypatch.setattr("switchboard.config._default_config_path", lambda: home)
    return home


def _write(p: Path, data: object) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# --- ALLOWED_TOP_LEVEL_FIELDS: one source of truth ---------------------------------------


def test_allowed_top_level_fields_is_exactly_the_known_field_set() -> None:
    # Hardcoded canary — NOT `== {f.name for f in fields(...)}`, which is tautological since
    # ALLOWED_TOP_LEVEL_FIELDS is DEFINED as that comprehension. If a field is added/removed,
    # this fails, forcing a conscious update of the producer (/offload-scan) and consumers.
    # The cross-module one-source-of-truth check (offload-scan test imports this constant)
    # lands in Step 3 (#219).
    assert ALLOWED_TOP_LEVEL_FIELDS == {
        "less_token_mode",
        "enabled_call_sites",
        "effort",
        "base_url",
        "model",
        "cold_timeout_s",
        "warm_timeout_s",
        "max_tokens",
    }


# --- from_mapping -------------------------------------------------------------------------


def test_from_mapping_constructs_valid_config() -> None:
    cfg = SwitchboardConfig.from_mapping(
        {"less_token_mode": True, "enabled_call_sites": {"review-deep-style": True}}
    )
    assert cfg.is_call_site_enabled("review-deep-style")
    assert cfg.less_token_mode is True


def test_from_mapping_unknown_key_raises_config_error() -> None:
    with pytest.raises(ConfigError) as exc:
        SwitchboardConfig.from_mapping({"enabledd_call_sites": {}})
    # The clean ConfigError names the offending key (vs the raw TypeError from **kwargs).
    assert "enabledd_call_sites" in str(exc.value)


def test_from_mapping_propagates_value_validation() -> None:
    # Known key, bad value: __post_init__ still runs and raises ConfigError.
    with pytest.raises(ConfigError):
        SwitchboardConfig.from_mapping({"max_tokens": 100})


# --- load_config: resolution order -------------------------------------------------------


def test_load_config_returns_defaults_when_nothing_set(hermetic: Path) -> None:
    cfg, source = load_config()
    assert source == "defaults"
    assert cfg == SwitchboardConfig()  # byte-identical to today's inert behavior


def test_load_config_reads_env_file(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfgfile = _write(tmp_path / "env.json", {"enabled_call_sites": {"review-deep-style": True}})
    monkeypatch.setenv(ENV_VAR, str(cfgfile))
    cfg, source = load_config()
    assert source == f"env:{cfgfile}"
    assert cfg.is_call_site_enabled("review-deep-style")


def test_load_config_env_missing_file_raises(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "does-not-exist.json"))
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_env_malformed_json_raises(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(bad))
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_env_non_object_json_raises(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A JSON list is valid JSON but not a config object.
    bad = _write(tmp_path / "list.json", [1, 2, 3])
    monkeypatch.setenv(ENV_VAR, str(bad))
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_env_unknown_key_raises(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = _write(tmp_path / "unknown.json", {"bogus": 1})
    monkeypatch.setenv(ENV_VAR, str(bad))
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_reads_home_default(hermetic: Path) -> None:
    _write(hermetic, {"enabled_call_sites": {"skill-iterate-grader": True}})
    cfg, source = load_config()
    assert source == f"home:{hermetic}"
    assert cfg.is_call_site_enabled("skill-iterate-grader")


def test_load_config_env_beats_home(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write(hermetic, {"enabled_call_sites": {"home-site": True}})
    envfile = _write(tmp_path / "env.json", {"enabled_call_sites": {"env-site": True}})
    monkeypatch.setenv(ENV_VAR, str(envfile))
    cfg, source = load_config()
    assert source == f"env:{envfile}"
    assert cfg.is_call_site_enabled("env-site")
    assert not cfg.is_call_site_enabled("home-site")


def test_load_config_explicit_arg_beats_env(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argfile = _write(tmp_path / "arg.json", {"enabled_call_sites": {"arg-site": True}})
    envfile = _write(tmp_path / "env.json", {"enabled_call_sites": {"env-site": True}})
    monkeypatch.setenv(ENV_VAR, str(envfile))
    cfg, source = load_config(str(argfile))
    assert source == f"arg:{argfile}"
    assert cfg.is_call_site_enabled("arg-site")
    assert not cfg.is_call_site_enabled("env-site")


def test_load_config_explicit_arg_missing_raises(hermetic: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "absent.json"))


def test_load_config_empty_env_var_falls_through_to_defaults(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty env var means "unset" — fall through (do not treat "" as a path).
    monkeypatch.setenv(ENV_VAR, "")
    cfg, source = load_config()
    assert source == "defaults"
    assert cfg == SwitchboardConfig()


def test_load_config_env_invalid_utf8_raises(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Invalid UTF-8 bytes raise UnicodeDecodeError on read; load_config MUST wrap it as
    # ConfigError — the defer-safety contract is that the judge hot path catches ONLY
    # ConfigError, so any other exception escaping here would crash the judge.
    bad = tmp_path / "bad-utf8.json"
    bad.write_bytes(b"\xff\xfe not valid utf-8")
    monkeypatch.setenv(ENV_VAR, str(bad))
    with pytest.raises(ConfigError):
        load_config()


def test_load_config_explicit_arg_beats_home(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # All three tiers present: the explicit arg must win over both env and home.
    _write(hermetic, {"enabled_call_sites": {"home-site": True}})
    envfile = _write(tmp_path / "env.json", {"enabled_call_sites": {"env-site": True}})
    argfile = _write(tmp_path / "arg.json", {"enabled_call_sites": {"arg-site": True}})
    monkeypatch.setenv(ENV_VAR, str(envfile))
    cfg, source = load_config(str(argfile))
    assert source == f"arg:{argfile}"
    assert cfg.is_call_site_enabled("arg-site")
    assert not cfg.is_call_site_enabled("env-site")
    assert not cfg.is_call_site_enabled("home-site")


def test_load_config_file_value_validation_raises(
    hermetic: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Full path file -> from_mapping -> __post_init__: a below-floor max_tokens must raise
    # ConfigError through load_config (not just through from_mapping directly).
    bad = _write(tmp_path / "lowtok.json", {"max_tokens": 100})
    monkeypatch.setenv(ENV_VAR, str(bad))
    with pytest.raises(ConfigError):
        load_config()
