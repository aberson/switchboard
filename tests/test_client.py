"""local_judge: happy path, all 7 defer conditions, short-circuit, parsing, validation."""

from __future__ import annotations

import json
import socket
import urllib.error
from collections.abc import Callable

import pytest

from switchboard.client import (
    RC_BAD_ENVELOPE,
    RC_BAD_VERDICT,
    RC_DISABLED,
    RC_NON_JSON_BODY,
    RC_OS_ERROR,
    RC_TIMEOUT,
    RC_TRUNCATED,
    RC_UNREACHABLE,
    local_judge,
)
from switchboard.config import SwitchboardConfig
from switchboard.metrics import Metrics
from tests.conftest import (
    FLAG_CONTENT,
    PASS_CONTENT,
    TRUNCATED_ENVELOPE,
    chat_envelope,
    make_json_urlopen,
    make_raising_urlopen,
    make_raw_urlopen,
)

UrlopenStub = Callable[..., object]
ApplyStub = Callable[[UrlopenStub], None]


# --- Happy path: real pass + flag captured shapes ----------------------------------------


def test_pass_verdict(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    m = Metrics()
    result = local_judge("judge this", metrics=m)

    assert result.get("defer") is None
    assert result["verdict"] == "pass"  # type: ignore[typeddict-item]
    assert "type hints" in result["reason"]  # type: ignore[typeddict-item]
    assert m.verdicts["pass"] == 1
    assert m.total == 1


def test_flag_verdict(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(FLAG_CONTENT)))
    m = Metrics()
    result = local_judge("judge this", metrics=m)

    assert result["verdict"] == "flag"  # type: ignore[typeddict-item]
    assert "ambiguous variable name 'l'" in result["reason"]  # type: ignore[typeddict-item]
    assert m.verdicts["flag"] == 1


# --- Defer condition 1: unreachable / connection refused ---------------------------------


def test_defer_unreachable(patch_client: ApplyStub) -> None:
    refused = urllib.error.URLError(ConnectionRefusedError(10061, "actively refused it"))
    patch_client(make_raising_urlopen(refused))
    m = Metrics()
    result = local_judge("judge this", metrics=m)

    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_UNREACHABLE  # type: ignore[typeddict-item]
    assert m.defers[RC_UNREACHABLE] == 1


# --- Defer condition 2: timeout ----------------------------------------------------------


def test_defer_timeout_bare(patch_client: ApplyStub) -> None:
    patch_client(make_raising_urlopen(TimeoutError("timed out")))
    result = local_judge("judge this")
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_TIMEOUT  # type: ignore[typeddict-item]


def test_defer_timeout_wrapped_in_urlerror(patch_client: ApplyStub) -> None:
    # urllib often raises URLError(reason=TimeoutError) for socket timeouts.
    wrapped = urllib.error.URLError(TimeoutError("timed out"))
    patch_client(make_raising_urlopen(wrapped))
    result = local_judge("judge this")
    assert result["reason_class"] == RC_TIMEOUT  # type: ignore[typeddict-item]


# --- Defer condition 3: other OSError family ---------------------------------------------


def test_defer_os_error(patch_client: ApplyStub) -> None:
    patch_client(make_raising_urlopen(socket.gaierror("name resolution failed")))
    m = Metrics()
    result = local_judge("judge this", metrics=m)
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_OS_ERROR  # type: ignore[typeddict-item]
    assert m.defers[RC_OS_ERROR] == 1


# --- Defer condition 4: non-JSON HTTP body -----------------------------------------------


def test_defer_non_json_body(patch_client: ApplyStub) -> None:
    patch_client(make_raw_urlopen(b"<html>502 Bad Gateway</html>"))
    result = local_judge("judge this")
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_NON_JSON_BODY  # type: ignore[typeddict-item]


# --- Defer condition 5: unexpected envelope (missing choices[0].message) ------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "chat.completion"},  # no choices
        {"choices": []},  # empty choices
        {"choices": [{"index": 0}]},  # choice without message
        {"choices": ["not-a-dict"]},  # choice not a dict
        ["not", "an", "object"],  # whole body not an object
    ],
)
def test_defer_bad_envelope(patch_client: ApplyStub, payload: object) -> None:
    patch_client(make_json_urlopen(payload))
    result = local_judge("judge this")
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_BAD_ENVELOPE  # type: ignore[typeddict-item]


# --- Defer condition 6: truncated (finish_reason=length, content empty) ------------------


def test_defer_truncated_real_envelope(patch_client: ApplyStub) -> None:
    # The verbatim spike truncation envelope: content="" + finish_reason="length".
    patch_client(make_json_urlopen(TRUNCATED_ENVELOPE))
    m = Metrics()
    result = local_judge("judge this", metrics=m)
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_TRUNCATED  # type: ignore[typeddict-item]
    assert "max_tokens" in result["reason"]  # type: ignore[typeddict-item]
    assert m.defers[RC_TRUNCATED] == 1


# --- Defer condition 7: unparseable / wrong-shape verdict --------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "I think this looks fine to me, no JSON here.",  # no JSON at all
        '{"verdict":"maybe","reason":"unsure"}',  # verdict not in {pass,flag}
        '{"verdict":"pass"}',  # missing reason
        '{"verdict":"pass","reason":""}',  # empty reason rejected
        '{"verdict":"pass","reason":42}',  # reason not a string
        '{"reason":"no verdict key"}',  # missing verdict
    ],
)
def test_defer_bad_verdict(patch_client: ApplyStub, content: str) -> None:
    patch_client(make_json_urlopen(chat_envelope(content)))  # finish_reason=stop
    result = local_judge("judge this")
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_BAD_VERDICT  # type: ignore[typeddict-item]


# --- less_token_mode OFF / disabled call site: short-circuit, NO network -----------------


def test_short_circuit_mode_off_does_not_call_network() -> None:
    # No patch_client: if the client touched urllib it would hit a real (absent) endpoint.
    # The short-circuit must return before any network attempt.
    cfg = SwitchboardConfig(less_token_mode=False)
    m = Metrics()
    result = local_judge("judge this", config=cfg, metrics=m)

    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_DISABLED  # type: ignore[typeddict-item]
    assert result["_elapsed_s"] == 0.0  # type: ignore[typeddict-item]
    assert "less_token_mode is OFF" in result["reason"]  # type: ignore[typeddict-item]
    assert m.defers[RC_DISABLED] == 1


def test_short_circuit_disabled_call_site() -> None:
    cfg = SwitchboardConfig(less_token_mode=True, enabled_call_sites={"style-lens": True})
    # "grader" is not in the map -> disabled by default.
    result = local_judge("judge this", config=cfg, task_class="grader")
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == RC_DISABLED  # type: ignore[typeddict-item]
    assert "not enabled" in result["reason"]  # type: ignore[typeddict-item]


def test_enabled_call_site_calls_network(patch_client: ApplyStub) -> None:
    cfg = SwitchboardConfig(enabled_call_sites={"style-lens": True})
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    result = local_judge("judge this", config=cfg, task_class="style-lens")
    assert result["verdict"] == "pass"  # type: ignore[typeddict-item]


# --- Lenient parsing: fenced + prose-wrapped JSON ----------------------------------------


def test_parse_fenced_json(patch_client: ApplyStub) -> None:
    fenced = f"```json\n{PASS_CONTENT}\n```"
    patch_client(make_json_urlopen(chat_envelope(fenced)))
    result = local_judge("judge this")
    assert result["verdict"] == "pass"  # type: ignore[typeddict-item]


def test_parse_prose_wrapped_json(patch_client: ApplyStub) -> None:
    prose = f"Sure, here is my verdict: {FLAG_CONTENT} — let me know if you need more."
    patch_client(make_json_urlopen(chat_envelope(prose)))
    result = local_judge("judge this")
    assert result["verdict"] == "flag"  # type: ignore[typeddict-item]
    assert "ambiguous variable name 'l'" in result["reason"]  # type: ignore[typeddict-item]


def test_reasoning_content_is_ignored_for_verdict(patch_client: ApplyStub) -> None:
    # A valid verdict in content, and a DIFFERENT (wrong) verdict in reasoning_content.
    # The contract: read content, ignore reasoning_content.
    env = chat_envelope(
        PASS_CONTENT,
        reasoning_content='{"verdict":"flag","reason":"this is reasoning, ignore me"}',
    )
    patch_client(make_json_urlopen(env))
    result = local_judge("judge this")
    assert result["verdict"] == "pass"  # type: ignore[typeddict-item]
    assert "type hints" in result["reason"]  # type: ignore[typeddict-item]


# --- request body honors the contract ----------------------------------------------------


def test_request_body_matches_contract(
    monkeypatch: pytest.MonkeyPatch, patch_client: ApplyStub
) -> None:
    captured: dict[str, object] = {}

    def _capturing(req: object, timeout: float | None = None):  # type: ignore[no-untyped-def]
        captured["data"] = req.data  # type: ignore[attr-defined]
        captured["url"] = req.full_url  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        from tests.conftest import _FakeResponse

        return _FakeResponse(json.dumps(chat_envelope(PASS_CONTENT)).encode("utf-8"))

    monkeypatch.setattr("switchboard.client.urllib.request.urlopen", _capturing)

    cfg = SwitchboardConfig()
    local_judge("the diff to judge", config=cfg)

    assert captured["url"] == f"{cfg.base_url}/chat/completions"
    body = json.loads(captured["data"])  # type: ignore[arg-type]
    assert body["model"] == "coder-30b"
    assert body["temperature"] == 0
    assert body["max_tokens"] == 800
    assert body["max_tokens"] >= 600
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "the diff to judge"
    # warm timeout by default
    assert captured["timeout"] == cfg.warm_timeout_s


def test_cold_flag_uses_cold_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _capturing(req: object, timeout: float | None = None):  # type: ignore[no-untyped-def]
        captured["timeout"] = timeout
        from tests.conftest import _FakeResponse

        return _FakeResponse(json.dumps(chat_envelope(PASS_CONTENT)).encode("utf-8"))

    monkeypatch.setattr("switchboard.client.urllib.request.urlopen", _capturing)
    cfg = SwitchboardConfig()
    local_judge("x", config=cfg, cold=True)
    assert captured["timeout"] == cfg.cold_timeout_s
