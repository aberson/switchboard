"""In-process counter for local-judge calls.

The Step 4 validation harness reads this to prove quota saved: every offloaded call that
returns a real verdict is a Claude call avoided; every defer is a fall-back to Claude.

This is a deliberately simple, single-process, in-memory counter (no persistence, no
locking beyond the GIL). If concurrency is ever added at the call site, wrap increments in
a lock — the spike's sync design means calls are infrequent and serial today.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Metrics:
    """Counts of local-judge outcomes.

    * ``total`` — every ``local_judge`` invocation that reached the metrics layer.
    * ``verdicts`` — calls that returned a validated verdict, keyed by ``pass`` / ``flag``.
    * ``defers`` — calls that returned the defer sentinel, keyed by a short reason class.
    """

    total: int = 0
    verdicts: Counter[str] = field(default_factory=Counter)
    defers: Counter[str] = field(default_factory=Counter)

    def record_verdict(self, verdict: str) -> None:
        self.total += 1
        self.verdicts[verdict] += 1

    def record_defer(self, reason_class: str) -> None:
        self.total += 1
        self.defers[reason_class] += 1

    @property
    def verdict_total(self) -> int:
        return sum(self.verdicts.values())

    @property
    def defer_total(self) -> int:
        return sum(self.defers.values())

    def snapshot(self) -> dict[str, object]:
        """A plain-dict view for logging / the validation harness."""
        return {
            "total": self.total,
            "verdicts": dict(self.verdicts),
            "defers": dict(self.defers),
            "verdict_total": self.verdict_total,
            "defer_total": self.defer_total,
        }

    def reset(self) -> None:
        self.total = 0
        self.verdicts.clear()
        self.defers.clear()


# Module-level default counter. Callers that want isolation pass their own Metrics into
# local_judge(metrics=...).
METRICS = Metrics()
