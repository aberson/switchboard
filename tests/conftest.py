"""Shared test fixtures: real captured response shapes + a stubbed HTTP boundary.

Every shape below is copied VERBATIM from docs/investigations/switchboard-spike.md so the
tests exercise the real model's envelope, not an invented one. Tests NEVER make live
network calls — they monkeypatch ``urllib.request.urlopen``.
"""

from __future__ import annotations

import io
import json
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

import pytest

# --- Real captured envelopes (verbatim from the spike doc) -------------------------------

# PASS case content (spike doc lines 97-99). The model emits strict JSON in `content`.
PASS_CONTENT = (
    '{"verdict":"pass","reason":"Adding type hints improves clarity and follows modern '
    'Python conventions."}'
)

# FLAG case content (spike doc lines 120-122).
FLAG_CONTENT = (
    '{"verdict":"flag","reason":"Replaces idiomatic built-in with verbose manual loop and '
    "uses ambiguous variable name 'l'.\"}"
)


def chat_envelope(
    content: str,
    *,
    finish_reason: str = "stop",
    reasoning_content: str = "",
    model: str = "Qwen3.6-35B-A3B-IQ3_S.gguf",
) -> dict[str, Any]:
    """A chat.completion envelope mirroring the spike's real shape (lines 58-63)."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return {
        "choices": [{"finish_reason": finish_reason, "index": 0, "message": message}],
        "object": "chat.completion",
        "model": model,
    }


# The verbatim truncation envelope: content="" + reasoning_content filled +
# finish_reason="length" (spike doc lines 58-63).
TRUNCATED_ENVELOPE = chat_envelope(
    "",
    finish_reason="length",
    reasoning_content="Here's a thinking process:\n\n1.  **Analyze User Input:** ...",
)

# The verbatim /models body (spike doc line 20).
MODELS_BODY = {
    "data": [
        {"id": "coder-30b", "object": "model", "created": 1781921855, "owned_by": "llama-swap"},
        {"id": "general-35b", "object": "model", "created": 1781921855, "owned_by": "llama-swap"},
    ],
    "object": "list",
}


# --- Stub HTTP boundary -------------------------------------------------------------------


class _FakeResponse:
    """Minimal context-manager standing in for an http.client.HTTPResponse."""

    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self._buf.close()

    def read(self) -> bytes:
        return self._buf.read()


UrlopenStub = Callable[..., _FakeResponse]


def make_json_urlopen(payload: object) -> UrlopenStub:
    """A urlopen stub that returns ``payload`` json-encoded for any request."""

    def _urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    return _urlopen


def make_raw_urlopen(body: bytes) -> UrlopenStub:
    """A urlopen stub that returns arbitrary raw bytes (e.g. non-JSON body)."""

    def _urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(body)

    return _urlopen


def make_raising_urlopen(exc: BaseException) -> UrlopenStub:
    """A urlopen stub that raises ``exc`` (transport-error conditions)."""

    def _urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        raise exc

    return _urlopen


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[UrlopenStub], None]]:
    """Patch urllib.request.urlopen with a stub of the caller's choosing.

    client.py and health.py both call ``urllib.request.urlopen`` (the shared stdlib
    object), so patching it once covers both. Named ``patch_client`` for the call sites.
    """

    def _apply(stub: UrlopenStub) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", stub)

    yield _apply


# Health probes use the same shared urllib.request.urlopen — one fixture covers both.
@pytest.fixture
def patch_health(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[UrlopenStub], None]]:
    """Patch urllib.request.urlopen for health-module tests (same shared object)."""

    def _apply(stub: UrlopenStub) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", stub)

    yield _apply
