"""Metrics counter + end-to-end metrics accumulation through local_judge."""

from __future__ import annotations

from collections.abc import Callable

from switchboard.client import RC_DISABLED, RC_TRUNCATED, local_judge
from switchboard.config import SwitchboardConfig
from switchboard.metrics import Metrics
from tests.conftest import (
    FLAG_CONTENT,
    PASS_CONTENT,
    TRUNCATED_ENVELOPE,
    chat_envelope,
    make_json_urlopen,
)

ApplyStub = Callable[..., None]


def test_counter_basics() -> None:
    m = Metrics()
    m.record_verdict("pass")
    m.record_verdict("pass")
    m.record_verdict("flag")
    m.record_defer("timeout")

    assert m.total == 4
    assert m.verdict_total == 3
    assert m.defer_total == 1
    assert m.verdicts["pass"] == 2
    assert m.verdicts["flag"] == 1
    assert m.defers["timeout"] == 1


def test_snapshot_shape() -> None:
    m = Metrics()
    m.record_verdict("pass")
    m.record_defer("unreachable")
    snap = m.snapshot()
    assert snap == {
        "total": 2,
        "verdicts": {"pass": 1},
        "defers": {"unreachable": 1},
        "verdict_total": 1,
        "defer_total": 1,
    }


def test_reset() -> None:
    m = Metrics()
    m.record_verdict("pass")
    m.reset()
    assert m.total == 0
    assert m.verdict_total == 0
    assert m.defer_total == 0


def test_metrics_accumulate_across_calls(patch_client: ApplyStub) -> None:
    """The Step-4-harness scenario: a mix of verdicts + defers tallied in one counter."""
    m = Metrics()

    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    local_judge("a", metrics=m)
    patch_client(make_json_urlopen(chat_envelope(FLAG_CONTENT)))
    local_judge("b", metrics=m)
    patch_client(make_json_urlopen(TRUNCATED_ENVELOPE))
    local_judge("c", metrics=m)

    # disabled short-circuit also records (a Claude fall-back happened):
    local_judge("d", config=SwitchboardConfig(less_token_mode=False), metrics=m)

    assert m.total == 4
    assert m.verdict_total == 2
    assert m.verdicts["pass"] == 1
    assert m.verdicts["flag"] == 1
    assert m.defer_total == 2
    assert m.defers[RC_TRUNCATED] == 1
    assert m.defers[RC_DISABLED] == 1


def test_module_level_metrics_used_by_default(patch_client: ApplyStub) -> None:
    from switchboard.metrics import METRICS

    METRICS.reset()
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    local_judge("judge this")  # no metrics= -> uses module default
    assert METRICS.verdicts["pass"] == 1
    METRICS.reset()
