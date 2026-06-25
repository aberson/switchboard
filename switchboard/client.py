"""``local_judge`` — the D1-contract client for the local OpenAI-compatible judge.

Sync. Stdlib-only (``urllib``, no network deps). POSTs a strict-JSON judge request to
``{base_url}/chat/completions`` and returns either a validated verdict or a defer sentinel.

Contract pinned in docs/investigations/switchboard-spike.md (issue #203). Key points:
  * read the verdict from ``choices[0].message.content`` (IGNORE ``reasoning_content``);
  * parse leniently (strip ```json fences, scan first balanced ``{}``) but validate
    strictly (``verdict in {pass, flag}`` AND ``reason`` a non-empty string);
  * defer on ANY of the 7 documented failure conditions;
  * ``max_tokens`` defaults to 800 (general-35b is a reasoning model);
  * when ``less_token_mode`` is OFF (or the call site is disabled), short-circuit to the
    defer sentinel WITHOUT touching the network.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Literal, TypedDict, TypeGuard, cast

from switchboard.config import SwitchboardConfig
from switchboard.metrics import METRICS, Metrics

SYSTEM_PROMPT = (
    "You are a terse code-style judge. You evaluate a small code-style diff and decide "
    "whether it passes review. Respond with ONLY JSON of the exact shape "
    '{"verdict":"pass"|"flag","reason":"<short>"} and nothing else.'
)


class Verdict(TypedDict):
    """A validated judge verdict."""

    verdict: Literal["pass", "flag"]
    reason: str
    _raw: str
    _elapsed_s: float


class Defer(TypedDict):
    """The defer sentinel — the caller routes this judgment to Claude."""

    defer: Literal[True]
    reason: str
    reason_class: str
    _elapsed_s: float


JudgeResult = Verdict | Defer


# Short, stable reason-class strings for the metrics counter (one per documented condition).
RC_DISABLED = "disabled"  # less_token_mode off / call site not enabled (short-circuit)
RC_UNREACHABLE = "unreachable"  # condition 1: connection refused / URLError
RC_TIMEOUT = "timeout"  # condition 2
RC_OS_ERROR = "os_error"  # condition 3: other OSError family
RC_NON_JSON_BODY = "non_json_body"  # condition 4
RC_BAD_ENVELOPE = "bad_envelope"  # condition 5: missing choices[0].message
RC_TRUNCATED = "truncated"  # condition 6: finish_reason=length, no verdict
RC_BAD_VERDICT = "bad_verdict"  # condition 7: unparseable / wrong-shape verdict
RC_CONFIG_ERROR = "config_error"  # judge CLI: load_config() failed -> defer-safe Claude fallback
RC_INPUT_ERROR = "input_error"  # judge CLI: prompt read failed (unreadable --prompt-file/stdin)


def _defer(reason: str, reason_class: str, elapsed: float) -> Defer:
    return {
        "defer": True,
        "reason": reason,
        "reason_class": reason_class,
        "_elapsed_s": elapsed,
    }


def config_error_defer(reason: str) -> Defer:
    """Build the defer sentinel the judge CLI emits when ``load_config()`` fails.

    Kept beside ``_defer`` (not built inline in the CLI) so the Defer sentinel shape has ONE
    source of truth. ``_elapsed_s`` is 0.0 — no network call happened. The CLI pairs this with
    ``METRICS.record_defer(RC_CONFIG_ERROR)`` so config-error defers are counted like any other.
    """
    return _defer(reason, RC_CONFIG_ERROR, 0.0)


def input_error_defer(reason: str) -> Defer:
    """Build the defer sentinel the judge CLI emits when the prompt itself can't be read.

    A provided-but-unreadable ``--prompt-file`` (missing/locked/non-UTF8) or a failed stdin read
    is a well-formed invocation per argparse, so the judge defers rather than crashing — same
    defer-safe contract as ``config_error_defer``. ``_elapsed_s`` is 0.0 — no network call.
    """
    return _defer(reason, RC_INPUT_ERROR, 0.0)


def _extract_json_object(text: str) -> dict[str, object] | None:
    """Pull the first JSON object out of arbitrary model text.

    Lenient: strips ```json fences, then scans for the first balanced ``{ ... }``.
    Returns the parsed dict, or None if nothing valid is found.
    """
    if not text:
        return None

    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)

    for chunk in candidates:
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return cast("dict[str, object]", obj)
        except (json.JSONDecodeError, ValueError):
            pass
        # Scan for the first balanced top-level object.
        depth = 0
        start = -1
        for i, ch in enumerate(chunk):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start != -1:
                        snippet = chunk[start : i + 1]
                        try:
                            obj = json.loads(snippet)
                            if isinstance(obj, dict):
                                return cast("dict[str, object]", obj)
                        except (json.JSONDecodeError, ValueError):
                            start = -1  # keep scanning
    return None


class _RawVerdict(TypedDict):
    """The validated raw object pulled from model output (pre-typing of the literal)."""

    verdict: str
    reason: str


def _valid_verdict(obj: dict[str, object] | None) -> TypeGuard[_RawVerdict]:
    """Pinned verdict shape: verdict in {pass, flag} plus a NON-EMPTY string reason."""
    if not isinstance(obj, dict):
        return False
    reason = obj.get("reason")
    return obj.get("verdict") in {"pass", "flag"} and isinstance(reason, str) and reason != ""


def local_judge(
    prompt: str,
    *,
    config: SwitchboardConfig | None = None,
    cold: bool = False,
    timeout: float | None = None,
    task_class: str | None = None,
    metrics: Metrics | None = None,
) -> JudgeResult:
    """Ask the local model for a strict-JSON judge verdict.

    Args:
        prompt: the diff/code (plus its 'Respond with ONLY JSON: ...' instruction) to judge.
        config: Switchboard config; defaults to ``SwitchboardConfig()`` (spike defaults).
        cold: if True, use the cold timeout (first call cold-loads the model); else warm.
        timeout: explicit override; takes precedence over the cold/warm config timeout.
        task_class: the call site (e.g. ``"style-lens"``). When given, the per-site enable
            gate AND per-site model override from config apply.
        metrics: counter to record into; defaults to the module-level ``METRICS``.

    Returns:
        A validated ``Verdict`` on success, or a ``Defer`` sentinel on any of the 7
        documented failure conditions OR when offload is disabled by config.
    """
    cfg = config if config is not None else SwitchboardConfig()
    mx = metrics if metrics is not None else METRICS

    # --- Short-circuit: offload disabled -> defer WITHOUT calling the endpoint. ----------
    if not cfg.offload_allowed(task_class):
        reason = (
            "less_token_mode is OFF; deferring to Claude"
            if not cfg.less_token_mode
            else f"call site {task_class!r} is not enabled for local offload"
        )
        mx.record_defer(RC_DISABLED)
        return _defer(reason, RC_DISABLED, 0.0)

    model = cfg.model_for(task_class) if task_class is not None else cfg.model
    eff_timeout = (
        timeout if timeout is not None else (cfg.cold_timeout_s if cold else cfg.warm_timeout_s)
    )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": cfg.max_tokens,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg.base_url}/chat/completions",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=eff_timeout) as resp:
            payload_raw = json.loads(resp.read().decode("utf-8"))
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        elapsed = round(time.monotonic() - start, 3)
        rc, label = _classify_transport_error(exc)
        mx.record_defer(rc)
        return _defer(f"{label}: {exc!r}", rc, elapsed)
    except (json.JSONDecodeError, ValueError) as exc:
        elapsed = round(time.monotonic() - start, 3)
        mx.record_defer(RC_NON_JSON_BODY)
        return _defer(f"non-JSON HTTP body: {exc!r}", RC_NON_JSON_BODY, elapsed)

    elapsed = round(time.monotonic() - start, 3)

    if not isinstance(payload_raw, dict):
        mx.record_defer(RC_BAD_ENVELOPE)
        return _defer("response body was not a JSON object", RC_BAD_ENVELOPE, elapsed)
    payload = cast("dict[str, object]", payload_raw)

    msg = _message_of(payload)
    if msg is None:
        mx.record_defer(RC_BAD_ENVELOPE)
        return _defer(
            "unexpected response envelope: missing choices[0].message",
            RC_BAD_ENVELOPE,
            elapsed,
        )
    raw_content = msg.get("content")
    raw = raw_content if isinstance(raw_content, str) else ""
    finish = _finish_reason_of(payload)

    parsed = _extract_json_object(raw)
    if not _valid_verdict(parsed):
        if finish == "length":
            mx.record_defer(RC_TRUNCATED)
            return _defer(
                "response truncated (finish_reason=length) before a verdict; raise max_tokens",
                RC_TRUNCATED,
                elapsed,
            )
        mx.record_defer(RC_BAD_VERDICT)
        return _defer("response did not contain a valid verdict object", RC_BAD_VERDICT, elapsed)

    # parsed is narrowed to _RawVerdict by the _valid_verdict TypeGuard above.
    verdict_val = cast("Literal['pass', 'flag']", parsed["verdict"])
    reason_val = parsed["reason"]
    mx.record_verdict(verdict_val)
    return {
        "verdict": verdict_val,
        "reason": reason_val,
        "_raw": raw,
        "_elapsed_s": elapsed,
    }


def _classify_transport_error(exc: BaseException) -> tuple[str, str]:
    """Map a transport exception to (reason_class, human label) per conditions 1-3."""
    if isinstance(exc, TimeoutError):
        return RC_TIMEOUT, "request timed out"
    if isinstance(exc, urllib.error.URLError):
        # A URLError wrapping a timeout still classifies as timeout.
        if isinstance(exc.reason, TimeoutError):
            return RC_TIMEOUT, "request timed out"
        return RC_UNREACHABLE, "endpoint unreachable/refused"
    # Other OSError family (socket errors not wrapped by urllib).
    return RC_OS_ERROR, "socket/OS error reaching endpoint"


def _message_of(payload: dict[str, object]) -> dict[str, object] | None:
    """Safely pull choices[0].message as a dict, or None if the envelope is malformed."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    msg = first.get("message")
    if not isinstance(msg, dict):
        return None
    return cast("dict[str, object]", msg)


def _finish_reason_of(payload: dict[str, object]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    fr = first.get("finish_reason")
    return fr if isinstance(fr, str) else None
