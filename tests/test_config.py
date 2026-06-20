"""SwitchboardConfig: defaults, validation, gating logic."""

from __future__ import annotations

import pytest

from switchboard.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    MIN_MAX_TOKENS,
    ConfigError,
    SwitchboardConfig,
)


def test_defaults_match_pinned_contract() -> None:
    cfg = SwitchboardConfig()
    assert cfg.base_url == DEFAULT_BASE_URL == "http://localhost:8080/v1"
    assert cfg.model == DEFAULT_MODEL == "general-35b"
    assert cfg.cold_timeout_s == 540.0
    assert cfg.warm_timeout_s == 60.0
    assert cfg.max_tokens == DEFAULT_MAX_TOKENS == 800
    assert cfg.max_tokens >= MIN_MAX_TOKENS
    assert cfg.less_token_mode is True


def test_base_url_and_model_configurable() -> None:
    cfg = SwitchboardConfig(base_url="http://localhost:9090/v1", model="coder-30b")
    assert cfg.base_url == "http://localhost:9090/v1"
    assert cfg.model == "coder-30b"


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
    assert cfg.model_for("style") == "general-35b"  # falls back to default
    assert cfg.model_for("unknown") == "general-35b"


def test_config_is_frozen() -> None:
    cfg = SwitchboardConfig()
    with pytest.raises((AttributeError, TypeError)):
        cfg.model = "x"  # type: ignore[misc]
