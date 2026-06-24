"""Switchboard — local-LLM offload core.

Route cheap judgment calls (style lens, overnight grader, ...) to a local
OpenAI-compatible model; defer to Claude on any failure. See
docs/investigations/switchboard-spike.md for the pinned D1 contract.
"""

from __future__ import annotations

from switchboard.bakeoff import (
    BakeoffError,
    BakeoffReport,
    CaseRow,
    RunnerReport,
    Suite,
    SuiteCase,
    load_suite,
    run_bakeoff,
)
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
    AgreementVerdict,
    CaseOutcome,
    ShadowCase,
    ShadowReport,
    aggregate_agreement,
    run_shadow,
)
from switchboard.health import Health, health, is_warm, warm_up
from switchboard.metrics import METRICS, Metrics

__all__ = [
    "METRICS",
    "AgreementVerdict",
    "BakeoffError",
    "BakeoffReport",
    "CaseOutcome",
    "CaseRow",
    "ConfigError",
    "Defer",
    "Health",
    "JudgeResult",
    "Metrics",
    "RunnerReport",
    "ShadowCase",
    "ShadowReport",
    "Suite",
    "SuiteCase",
    "SwitchboardConfig",
    "Verdict",
    "aggregate_agreement",
    "health",
    "is_warm",
    "load_suite",
    "local_judge",
    "run_bakeoff",
    "run_shadow",
    "warm_up",
]
