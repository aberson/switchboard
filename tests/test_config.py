"""SwitchboardConfig: defaults, validation, gating logic."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from switchboard.config import (
    ALLOWED_EFFORT_TIERS,
    ALLOWED_TOP_LEVEL_FIELDS,
    CONFIG_DIRECTORY_NAME,
    CONFIG_FILENAME,
    CONFIG_SOURCE_PRECEDENCE,
    DEFAULT_BASE_URL,
    DEFAULT_COLD_TIMEOUT_S,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_WARM_TIMEOUT_S,
    ENV_VAR,
    MIN_MAX_TOKENS,
    ConfigError,
    SwitchboardConfig,
)

CONTRACT_PATH = Path(__file__).parents[1] / "docs" / "observatory-contract.json"


def test_defaults_match_pinned_contract() -> None:
    cfg = SwitchboardConfig()
    assert cfg.base_url == DEFAULT_BASE_URL == "http://localhost:8080/v1"
    assert cfg.model == DEFAULT_MODEL == "coder-30b"
    assert cfg.cold_timeout_s == 540.0
    assert cfg.warm_timeout_s == 60.0
    assert cfg.max_tokens == DEFAULT_MAX_TOKENS == 800
    assert cfg.max_tokens >= MIN_MAX_TOKENS
    assert cfg.less_token_mode is True


def test_base_url_and_model_configurable() -> None:
    # Override with a NON-default model so this still proves `model` is configurable
    # (coder-30b is now the default — see test_defaults_match_pinned_contract).
    cfg = SwitchboardConfig(base_url="http://localhost:9090/v1", model="general-35b")
    assert cfg.base_url == "http://localhost:9090/v1"
    assert cfg.model == "general-35b"


# --- Validation: max_tokens floor (the #1 footgun) ---------------------------------------


def test_max_tokens_below_floor_rejected() -> None:
    with pytest.raises(ConfigError, match="max_tokens"):
        SwitchboardConfig(max_tokens=50)


def test_max_tokens_at_floor_ok() -> None:
    assert SwitchboardConfig(max_tokens=600).max_tokens == 600


def test_max_tokens_bool_rejected() -> None:
    with pytest.raises(ConfigError):
        SwitchboardConfig(max_tokens=True)  # type: ignore[arg-type]


# --- Validation: base_url path-safety ----------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://localhost/v1",  # wrong scheme
        "localhost:8080/v1",  # no scheme
        "http://localhost:8080/v1; rm -rf /",  # injection chars
        "http://localhost:8080/../etc",  # traversal
        "",  # empty
    ],
)
def test_bad_base_url_rejected(bad_url: str) -> None:
    with pytest.raises(ConfigError, match="base_url"):
        SwitchboardConfig(base_url=bad_url)


def test_good_https_url_ok() -> None:
    cfg = SwitchboardConfig(base_url="https://judge.internal:8443/v1")
    assert cfg.base_url == "https://judge.internal:8443/v1"


# --- Validation: model / task_class names ------------------------------------------------


@pytest.mark.parametrize("bad_model", ["", "model name with spaces", "model/../x", "a;b"])
def test_bad_model_name_rejected(bad_model: str) -> None:
    with pytest.raises(ConfigError):
        SwitchboardConfig(model=bad_model)


def test_bad_task_class_name_rejected() -> None:
    with pytest.raises(ConfigError, match="task_class"):
        SwitchboardConfig(enabled_call_sites={"bad task class": True})


def test_bad_call_site_value_type_rejected() -> None:
    with pytest.raises(ConfigError, match="bool or model name"):
        SwitchboardConfig(enabled_call_sites={"style-lens": 123})  # type: ignore[dict-item]


def test_bad_call_site_model_override_rejected() -> None:
    with pytest.raises(ConfigError):
        SwitchboardConfig(enabled_call_sites={"style-lens": "bad model name"})


# --- Validation: timeouts ----------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, "60", True])
def test_bad_warm_timeout_rejected(bad: object) -> None:
    with pytest.raises(ConfigError, match="warm_timeout_s"):
        SwitchboardConfig(warm_timeout_s=bad)  # type: ignore[arg-type]


# --- Gating logic ------------------------------------------------------------------------


def test_offload_allowed_mode_off() -> None:
    cfg = SwitchboardConfig(less_token_mode=False, enabled_call_sites={"s": True})
    assert cfg.offload_allowed() is False
    assert cfg.offload_allowed("s") is False


def test_offload_allowed_no_task_class() -> None:
    assert SwitchboardConfig().offload_allowed() is True


def test_call_site_enable_map() -> None:
    cfg = SwitchboardConfig(
        enabled_call_sites={
            "style-lens": True,
            "grader": False,
            "audit": "coder-30b",
        }
    )
    assert cfg.is_call_site_enabled("style-lens") is True
    assert cfg.is_call_site_enabled("grader") is False
    assert cfg.is_call_site_enabled("audit") is True  # model-string opts in
    assert cfg.is_call_site_enabled("unknown") is False  # default-deny


def test_model_for_override() -> None:
    cfg = SwitchboardConfig(enabled_call_sites={"audit": "coder-30b", "style": True})
    assert cfg.model_for("audit") == "coder-30b"
    assert cfg.model_for("style") == "coder-30b"  # falls back to default
    assert cfg.model_for("unknown") == "coder-30b"


def test_config_is_frozen() -> None:
    cfg = SwitchboardConfig()
    with pytest.raises((AttributeError, TypeError)):
        cfg.model = "x"  # type: ignore[misc]


# --- effort dimension (Phase B / Step B3) ------------------------------------------------
# HONEST SCOPE: switchboard stores + validates + round-trips ``effort`` but does NOT act on
# it (no live consumer this phase). These tests cover validation + the read-only accessor;
# there is intentionally no "effort changes a request" test because no such behavior exists.


def test_effort_defaults_to_empty() -> None:
    assert SwitchboardConfig().effort == {}


def test_effort_accepts_allowed_tiers() -> None:
    cfg = SwitchboardConfig(effort={"review-deep-style": "low", "skill-iterate-grader": "high"})
    assert cfg.effort_for("review-deep-style") == "low"
    assert cfg.effort_for("skill-iterate-grader") == "high"


def test_effort_for_unset_task_class_is_none() -> None:
    cfg = SwitchboardConfig(effort={"review-deep-style": "low"})
    assert cfg.effort_for("never-configured") is None
    assert SwitchboardConfig().effort_for("anything") is None


@pytest.mark.parametrize("tier", sorted(ALLOWED_EFFORT_TIERS))
def test_every_allowed_tier_is_accepted(tier: str) -> None:
    cfg = SwitchboardConfig(effort={"slice": tier})
    assert cfg.effort_for("slice") == tier


def test_allowed_effort_tiers_pinned() -> None:
    # Pin the tier set so a silent expansion/contraction is a conscious, reviewed change.
    assert ALLOWED_EFFORT_TIERS == {"low", "medium", "high", "xhigh", "max"}


@pytest.mark.parametrize("bad_tier", ["lowest", "LOW", "", "extreme", "1"])
def test_effort_unknown_tier_rejected(bad_tier: str) -> None:
    with pytest.raises(ConfigError, match="effort"):
        SwitchboardConfig(effort={"slice": bad_tier})


def test_effort_non_str_tier_rejected() -> None:
    with pytest.raises(ConfigError, match="effort"):
        SwitchboardConfig(effort={"slice": 1})  # type: ignore[dict-item]


def test_effort_bad_task_class_name_rejected() -> None:
    with pytest.raises(ConfigError, match="task_class"):
        SwitchboardConfig(effort={"bad task class": "low"})


# --- Step 72: producer-owned observatory fixture fails on config/path/default drift -------


def test_observatory_contract_matches_config_runtime_facts() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    config = contract["config"]
    defaults = SwitchboardConfig()

    assert contract["schema_version"] == 2
    assert config["directory_name"] == CONFIG_DIRECTORY_NAME
    assert config["filename"] == CONFIG_FILENAME
    assert config["environment_variable"] == ENV_VAR
    assert [item["label"] for item in config["source_precedence"]] == list(CONFIG_SOURCE_PRECEDENCE)
    assert config["fields"] == [field.name for field in fields(SwitchboardConfig)]
    assert set(config["fields"]) == ALLOWED_TOP_LEVEL_FIELDS
    assert config["defaults"] == {
        "less_token_mode": defaults.less_token_mode,
        "enabled_call_sites": defaults.enabled_call_sites,
        "effort": defaults.effort,
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "cold_timeout_s": DEFAULT_COLD_TIMEOUT_S,
        "warm_timeout_s": DEFAULT_WARM_TIMEOUT_S,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }
    validation = config["validation"]
    assert validation["max_tokens_minimum"] == MIN_MAX_TOKENS
    assert validation["allowed_effort_tiers"] == sorted(ALLOWED_EFFORT_TIERS)
    assert validation["retired_fields"] == ["roles", "claims"]
    assert not set(validation["retired_fields"]) & ALLOWED_TOP_LEVEL_FIELDS
    # The role fields left config for the registry section (tests/test_registry.py).
    assert not {"allowed_roles", "role_pin_fields", "claim_statuses"} & set(validation)


# --- Retired role pin table: roles and claims moved to the committed registry -------------


@pytest.mark.parametrize("key", ["roles", "claims"])
def test_retired_roles_and_claims_keys_are_unknown(key: str) -> None:
    # A config still carrying the pre-registry table fails by name, never silently ignored.
    with pytest.raises(ConfigError, match="unknown config key") as exc:
        SwitchboardConfig.from_mapping({"less_token_mode": True, key: {}})
    assert repr(key) in str(exc.value)
