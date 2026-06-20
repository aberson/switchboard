"""Switchboard — local-LLM offload core.

Route cheap judgment calls (style lens, overnight grader, ...) to a local
OpenAI-compatible model; defer to Claude on any failure. See
docs/investigations/switchboard-spike.md for the pinned D1 contract.
"""

from __future__ import annotations

from switchboard.client import (
    Defer,
    JudgeResult,
    Verdict,
    local_judge,
)
from switchboard.config import (
    ConfigError,
    SwitchboardConfig,
)
from switchboard.harness import (
    CaseOutcome,
    ShadowCase,
    ShadowReport,
    run_shadow,
)
from switchboard.health import Health, health, is_warm, warm_up
from switchboard.metrics import METRICS, Metrics

__all__ = [
    "METRICS",
    "CaseOutcome",
    "ConfigError",
    "Defer",
    "Health",
    "JudgeResult",
    "Metrics",
    "ShadowCase",
    "ShadowReport",
    "SwitchboardConfig",
    "Verdict",
    "health",
    "is_warm",
    "local_judge",
    "run_shadow",
    "warm_up",
]
