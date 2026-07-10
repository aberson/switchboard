"""Auto-disable-on-kill — ACT on a deployed slice's kill signal, don't just report it.

Decided 2026-07-06 (issue #261): ``run_shadow`` / ``run_live_local_runner`` compute
``kill = disagreement_rate > kill_threshold`` — the SIGNAL only. Until now nothing acted on
it; reverting a deployed slice was a manual operator action (delete ``~/.switchboard/
config.json``). That was judged wrong: on ``kill=True`` production must AUTO-DISABLE the
offending slice so a confident-but-wrong local judge stops costing verdict quality the moment
its disagreement trips the threshold.

This module is the consumer of that signal:

  * ``disable_slice_on_kill`` — the deterministic, fail-safe consumer. On ``kill=True`` it flips
    ``enabled_call_sites[task_class]`` to ``False`` in the deployed config file (reverting JUST
    that slice to defer-to-Claude), preserving every OTHER slice and every OTHER top-level field
    byte-for-value; on no-kill it is a pure no-op. A malformed/missing/unwritable config degrades
    gracefully (never crashes the caller), matching switchboard's defer-safe contract.

  * ``monitor_deployed_slice`` — the intended production entry point for the consumer. NOTE:
    this is UNWIRED GROUNDWORK — nothing invokes it yet (no ``monitor`` CLI subcommand, no
    scheduler/daemon), so the auto-disable is NOT live until a standing invocation is wired in
    B2b (issue #237). It composes the existing live ``run_shadow`` disagreement evaluation with
    the new consumer, ready for that caller.

Stdlib ``json`` only — switchboard is zero-dependency (``pyproject.toml`` ``dependencies = []``).
The config rewrite is a SURGICAL edit of the raw parsed JSON (only the tripped slice's value
changes), NOT a ``SwitchboardConfig`` round-trip — so no default field is materialized and no
other value can drift. There is no ``SwitchboardConfig -> mapping`` serializer to reuse (none
exists by design), and inventing one would be exactly the byte-for-value drift risk this avoids.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from switchboard.config import ConfigError, SwitchboardConfig, load_config
from switchboard.harness import (
    DEFAULT_KILL_THRESHOLD,
    ShadowCase,
    ShadowReport,
    run_shadow,
)
from switchboard.metrics import Metrics


@dataclass(frozen=True, slots=True)
class AutoDisableResult:
    """The outcome of an auto-disable attempt — the indicator a caller acts on.

    ``disabled`` is the single load-bearing bit: ``True`` iff this call reverted the slice to
    defer-to-Claude in the config file. ``reason`` is a human one-liner (kill vs no-op vs why it
    could not act); ``error`` is ``None`` on a clean run and carries the failure detail when a
    malformed/missing/unwritable config forced a graceful degrade instead of a write.
    """

    disabled: bool
    task_class: str
    config_path: str
    reason: str
    error: str | None = None


def disable_slice_on_kill(
    config_path: str | Path,
    task_class: str,
    *,
    report: ShadowReport | None = None,
    kill: bool | None = None,
) -> AutoDisableResult:
    """Disable ``task_class`` in the deployed config IFF the run killed; else no-op.

    The kill signal comes from exactly one of ``report`` (a ``ShadowReport`` — its ``.kill`` is
    read) or ``kill`` (the bare bool). On ``kill=True`` this reverts ONLY ``task_class`` to
    ``False`` in the config at ``config_path``, leaving every other slice and every other
    top-level field byte-for-value; on ``kill=False`` it writes nothing.

    Fail-safe: a missing / non-JSON / non-object / unwritable config, or a mutation that would
    fail the project's own validator, degrades to ``disabled=False`` with ``error`` set — the
    file is never crashed-through and never overwritten with something worse.

    Args:
        config_path: the deployed config file to revert the slice in.
        task_class: the tripped slice name (e.g. ``"review-deep-style"``).
        report: the shadow run whose ``.kill`` decides the action (preferred).
        kill: the bare kill bool, when a full report is not on hand.

    Returns:
        An ``AutoDisableResult`` whose ``disabled`` bit says whether the slice was reverted.
    """
    path_str = str(config_path)

    if report is not None:
        should_kill = report.kill
    elif kill is not None:
        should_kill = kill
    else:
        return AutoDisableResult(
            disabled=False,
            task_class=task_class,
            config_path=path_str,
            reason="no kill signal supplied — pass report= or kill=",
            error="no-signal",
        )

    if not should_kill:
        return AutoDisableResult(
            disabled=False,
            task_class=task_class,
            config_path=path_str,
            reason=f"kill=False for {task_class!r}; slice left as-is (no-op)",
        )

    return _revert_slice(path_str, task_class)


def _revert_slice(path_str: str, task_class: str) -> AutoDisableResult:
    """Surgically flip ``task_class`` to ``False`` in the config file, fail-safe throughout."""
    p = Path(path_str)

    def _fail(reason: str, error: str) -> AutoDisableResult:
        return AutoDisableResult(
            disabled=False,
            task_class=task_class,
            config_path=path_str,
            reason=reason,
            error=error,
        )

    try:
        raw_text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(
            f"could not read deployed config {path_str!r}; slice NOT disabled",
            str(exc),
        )
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return _fail(
            f"deployed config {path_str!r} is not valid JSON; slice NOT disabled",
            str(exc),
        )
    if not isinstance(raw, dict):
        return _fail(
            f"deployed config {path_str!r} is not a JSON object; slice NOT disabled",
            f"top-level is {type(raw).__name__}, expected object",
        )
    raw_dict = cast("dict[str, object]", raw)

    sites_obj = raw_dict.get("enabled_call_sites", {})
    if not isinstance(sites_obj, dict):
        return _fail(
            f"enabled_call_sites in {path_str!r} is not an object; slice NOT disabled",
            f"enabled_call_sites is {type(sites_obj).__name__}, expected object",
        )

    # Surgical edit: copy the map and flip ONLY this slice to False. Every other slice (whether
    # its value is a bool or a pinned model-name string) is carried through untouched, and every
    # other top-level field is preserved byte-for-value because we mutate the raw parsed dict.
    new_sites = dict(cast("dict[str, object]", sites_obj))
    new_sites[task_class] = False
    mutated: dict[str, object] = dict(raw_dict)
    mutated["enabled_call_sites"] = new_sites

    # Fail-safe: never persist a config the project's own loader would reject. Validate the
    # mutated mapping through the SAME validator load_config uses before writing — if the
    # deployed file had already drifted invalid, degrade rather than overwrite it.
    try:
        SwitchboardConfig.from_mapping(mutated)
    except ConfigError as exc:
        return _fail(
            f"refusing to write {path_str!r}: disabled config fails validation; slice NOT disabled",
            str(exc),
        )

    try:
        _atomic_write(p, json.dumps(mutated, indent=2) + "\n")
    except OSError as exc:
        return _fail(
            f"could not write deployed config {path_str!r}; slice NOT disabled",
            str(exc),
        )

    return AutoDisableResult(
        disabled=True,
        task_class=task_class,
        config_path=path_str,
        reason=(
            f"kill=True for {task_class!r}: reverted slice to defer-to-Claude "
            f"(enabled_call_sites[{task_class!r}]=false) in {path_str!r}"
        ),
    )


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically: temp file in the SAME dir, then ``os.replace``.

    A same-directory (hence same-volume) ``os.replace`` is atomic on both Windows and POSIX, so
    a concurrent reader (or a reader after a crash) never observes a torn/partial config — it
    sees either the whole OLD file or the whole NEW one. An in-place ``write_text`` truncates the
    target first, so a crash / ENOSPC mid-write would leave the deployed config empty or partial,
    destroying every other slice's enablement — precisely what this avoids.

    On ANY failure the ORIGINAL file is left untouched (we only ever ``os.replace`` a fully
    written temp over it) and the temp file is removed, so nothing is leaked.
    """
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        # Never touch the original on failure; never leak the temp file.
        tmp.unlink(missing_ok=True)
        raise


def monitor_deployed_slice(
    cases: Sequence[ShadowCase],
    *,
    task_class: str,
    config_path: str | Path,
    kill_threshold: float = DEFAULT_KILL_THRESHOLD,
    metrics: Metrics | None = None,
) -> tuple[ShadowReport, AutoDisableResult]:
    """Evaluate a DEPLOYED slice's live disagreement and auto-disable it on kill.

    This is the production entry point the ``disable_slice_on_kill`` consumer is wired into. No
    standing "monitor a deployed slice" daemon exists yet (issue #261), so — per the
    least-invasive correct choice — this function IS that live-run boundary: it composes the
    existing live ``run_shadow`` disagreement evaluation with the new consumer, rather than
    injecting a config-file write into the otherwise side-effect-free ``harness`` / ``bakeoff``
    scoring modules.

    Steps:
      1. Load the deployed config from ``config_path`` (the same ``load_config`` the judge hot
         path uses, so the live run sees the real gating + endpoint).
      2. Run the live shadow comparison for ``task_class`` over ``cases``.
      3. Hand the resulting ``ShadowReport`` to ``disable_slice_on_kill`` — on ``kill=True`` the
         slice is reverted to defer-to-Claude in the deployed file; on ``kill=False`` nothing is
         written.

    Fail-safe end-to-end: a broken/absent deployed config degrades WITHOUT crashing the caller. A
    ``ConfigError`` on load is swallowed and the live run falls back to the inert all-defer path
    (``config=None`` → the slice is disabled-by-default → every case defers → ``verdicted=0`` →
    ``kill=False``); ``disable_slice_on_kill`` then takes its no-op branch and writes nothing
    (``disabled=False``, ``error=None``). The unreadable config is left exactly as it was — the
    monitor never mutates a config it could not first understand.

    Args:
        cases: the prompt + expected-Claude-verdict set to shadow-compare live for this slice.
        task_class: the DEPLOYED slice to monitor and (on kill) disable (e.g.
            ``"review-deep-style"``).
        config_path: the deployed config file — read for the live gating/endpoint and rewritten
            in place (atomically) if the slice kills.
        kill_threshold: disagreement ceiling among verdicted cases (default 0.20).
        metrics: counter to record the live run into; defaults to a fresh isolated one.

    Returns:
        ``(report, result)`` — the live ``ShadowReport`` and the ``AutoDisableResult``.
    """
    try:
        config, _ = load_config(str(config_path))
    except ConfigError:
        # A broken deployed config must not crash the monitor: run_shadow with config=None takes
        # the inert all-defer path (no network, verdicted=0 -> cannot kill), so the disable step
        # then takes its no-op branch (disabled=False, error=None) and the config is left as-is.
        config = None

    report = run_shadow(
        cases,
        config=config,
        kill_threshold=kill_threshold,
        task_class=task_class,
        metrics=metrics,
    )
    result = disable_slice_on_kill(config_path, task_class, report=report)
    return report, result
