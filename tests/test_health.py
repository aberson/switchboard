"""health / is_warm / warm_up probes against a stubbed /models endpoint."""

from __future__ import annotations

import urllib.error
from collections.abc import Callable

from switchboard.config import SwitchboardConfig
from switchboard.health import endpoint_status, health, is_warm, warm_up
from tests.conftest import (
    MODELS_BODY,
    PASS_CONTENT,
    chat_envelope,
    make_json_urlopen,
    make_raising_urlopen,
    make_raw_urlopen,
)

ApplyStub = Callable[..., None]


def test_health_reachable_lists_models(patch_health: ApplyStub) -> None:
    patch_health(make_json_urlopen(MODELS_BODY))
    h = health()
    assert h["reachable"] is True
    assert h["models"] == ["coder-30b", "general-35b"]
    assert h["model_served"] is True
    assert h["error"] is None


def test_health_unreachable(patch_health: ApplyStub) -> None:
    patch_health(make_raising_urlopen(urllib.error.URLError(ConnectionRefusedError())))
    h = health()
    assert h["reachable"] is False
    assert h["models"] == []
    assert h["model_served"] is False
    assert h["error"] is not None


def test_health_non_json_body(patch_health: ApplyStub) -> None:
    patch_health(make_raw_urlopen(b"<html>down</html>"))
    h = health()
    assert h["reachable"] is True
    assert h["models"] == []
    assert h["error"] is not None


def test_health_model_not_served(patch_health: ApplyStub) -> None:
    patch_health(make_json_urlopen(MODELS_BODY))
    h = health(SwitchboardConfig(model="phantom-model"))
    assert h["reachable"] is True
    assert h["model_served"] is False


def test_endpoint_status_keeps_offline_and_missing_model_distinct(patch_health: ApplyStub) -> None:
    patch_health(make_raising_urlopen(urllib.error.URLError(ConnectionRefusedError())))
    assert endpoint_status(health()) == "offline"

    patch_health(make_json_urlopen(MODELS_BODY))
    result = health(SwitchboardConfig(model="phantom-model"))
    assert endpoint_status(result) == "online-model-missing"


def test_is_warm_true(patch_health: ApplyStub) -> None:
    patch_health(make_json_urlopen(MODELS_BODY))
    assert is_warm() is True


def test_is_warm_false_when_down(patch_health: ApplyStub) -> None:
    patch_health(make_raising_urlopen(urllib.error.URLError(ConnectionRefusedError())))
    assert is_warm() is False


def test_warm_up_lands_verdict(patch_client: ApplyStub) -> None:
    # warm_up calls local_judge, which uses the CLIENT's urlopen (not health's).
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    assert warm_up() is True


def test_warm_up_defers_when_down(patch_client: ApplyStub) -> None:
    patch_client(make_raising_urlopen(urllib.error.URLError(ConnectionRefusedError())))
    assert warm_up() is False
