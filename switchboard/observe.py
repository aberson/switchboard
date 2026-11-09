"""``python -m switchboard observe``: requested-versus-observed receipts for role dispatches.

    python -m switchboard observe --host claude|codex
                                  (--transcript <path> | --latest [--project-dir <dir>])
                                  [--home <dir>] [--registry <path>]

One run reads ONE native host transcript, records which model (and, when the host records one,
which effort) the dispatch actually ran and which agent type the host attributed it to, and
appends one receipt line to ``<home>/.switchboard/receipts.jsonl`` (decision R-D12)::

    {"ts", "host", "role", "agent_type", "requested_model", "requested_effort",
     "observed_model", "observed_effort", "source_locator", "registry_sha256"}

``requested_*`` are the registry row's values for that host when the receipt is made (an exact
ID or ``inherit``), ``registry_sha256`` names the registry bytes they came from, and
``source_locator`` is the absolute transcript path. ``observed_effort`` is ``UNKNOWN`` when the
transcript records no effort.

Attribution never guesses. ``role`` is the registry role ``<role>`` only when the host recorded
the agent type ``role-<role>`` (decision R-D7) and that role has a registry row. A transcript
that records no agent type, records several, or records one that is not a role agent yields
``role: "unattributed"``; ``agent_type`` keeps what the host recorded (``null`` for none) and
``requested_*`` are ``null``. An unattributed receipt is still written; it never joins a row.

Metadata only. Every transcript line is parsed as JSON, but only the keys named below are read;
no message content, prompt, tool input or output is read into a receipt, printed or kept.

Field names. Captured at build time (2026-11-08) from one real transcript per host by a
metadata-only key-shape scan (key paths and value types; values printed only for model, effort
and agent-type keys). The test fixtures under ``tests/fixtures/observe/`` reuse these names
with synthetic content. The transcript paths below keep only their shape: the project folder,
session id, agent id and date are placeholders, not the real ones.

* **Claude** (``--host claude``): Claude Code 2.1.318, entrypoint ``claude-vscode``, subagent
  transcript ``~/.claude/projects/<project>/<session-uuid>/subagents/agent-<agent-id>.jsonl``.
  Each line is one JSON object; the 11 lines with ``"type": "assistant"`` each carry
  ``message.model`` (``"claude-sonnet-5-5"``), a top-level ``effort`` (``"medium"``) and a
  top-level ``attributionAgent`` (``"general-purpose"``, the agent type). Cross-checks from the
  same scan: a user-level custom agent's transcript (2.1.287) records ``attributionAgent`` as
  the agent's own name (``"hookprobe"``); a workflow ``agent({agentType: "Explore"})``
  transcript under ``subagents/workflows/<run>/`` records ``"Explore"``; a fork transcript's
  inherited parent turn has no ``attributionAgent``; and ``message.model`` ``"<synthetic>"``
  marks a host-made message, so such a line is skipped. When an agent type is attributed, only
  the assistant lines carrying it are counted.
* **Codex** (``--host codex``): Codex CLI 0.155.0-alpha.16.3, originator ``codex_vscode``,
  subagent rollout
  ``~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-<timestamp>-<session-uuid>.jsonl``. Each line
  is one JSON object with ``type`` and ``payload``. Line 0 is the thread's own
  ``"type": "session_meta"``: ``payload.source.subagent.thread_spawn.agent_role`` is the agent
  type (``null`` there: no custom agent existed yet) and
  ``payload.subagent_history_start_ordinal`` (``13``) is the 0-based line index where the
  thread's own history starts; the lines before it (the parent's ``session_meta`` on line 1,
  the parent's ``turn_context`` lines) are inherited fork history and are not counted. Each
  ``"type": "turn_context"`` line carries ``payload.model`` (``"gpt-6-astra"``) and
  ``payload.effort`` (``"medium"``). ``payload.cwd`` of the own ``session_meta`` serves
  ``--project-dir``.

When the counted lines record more than one model (or effort), every distinct value is kept in
first-seen order, joined by ``|``, so a mixed run never reads as a match. A transcript whose
counted lines record no model is not evidence of a dispatch: no receipt is written.

``--latest`` picks the most recently modified subagent transcript (a role dispatch is always a
subagent): Claude ``<home>/.claude/projects/<project>/<session>/subagents/**/agent-*.jsonl``
(``--project-dir`` narrows ``<project>`` to that directory's Claude project folder, every
character other than an ASCII letter or digit replaced by ``-``); Codex
``<home>/.codex/sessions/**/rollout-*.jsonl`` whose own ``session_meta`` is a ``thread_spawn``
subagent (``--project-dir`` keeps those whose ``payload.cwd`` is that directory).

``inspect --roles`` shows, per role and host, the last receipt line recorded for them and
compares it with the CURRENT registry row: ``match``, ``mismatch``, ``inherit`` (the row requests
``inherit``, so there is nothing to compare) or ``unknown`` (the receipt has no value). A host
with no receipt shows ``unknown``. A malformed receipt line is skipped and counted, never fatal.

HONEST SCOPE: this module reads transcripts the host already wrote. It dispatches nothing and
proves nothing about dispatches it has not seen; Step R5 runs the live dispatches.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from switchboard.config import CONFIG_DIRECTORY_NAME
from switchboard.generate import AGENT_NAME_PREFIX
from switchboard.registry import (
    ALLOWED_HOSTS,
    INHERIT,
    ROLE_JSON_FIELDS,
    RegistryResult,
    RoleRow,
    load_registry,
)

# --- Receipts (decision R-D12) --------------------------------------------------------------
RECEIPTS_FILENAME = "receipts.jsonl"
# The keys of one receipt line, in write order.
RECEIPT_FIELDS: tuple[str, ...] = (
    "ts",
    "host",
    "role",
    "agent_type",
    "requested_model",
    "requested_effort",
    "observed_model",
    "observed_effort",
    "source_locator",
    "registry_sha256",
)
# The role of a receipt whose dispatch cannot be tied to a registry row.
UNATTRIBUTED = "unattributed"
# ``observed_effort`` when the transcript records no effort.
UNKNOWN_EFFORT = "UNKNOWN"
# Several distinct observed values are joined with this separator.
MULTI_VALUE_SEPARATOR = "|"

# --- The inspect join -----------------------------------------------------------------------
# A host with no receipt for a role.
OBSERVED_UNKNOWN = "unknown"
ObservedStatus = Literal["match", "mismatch", "inherit", "unknown"]
OBSERVED_STATUSES: tuple[ObservedStatus, ...] = get_args(ObservedStatus)
# The keys of one host's ``observed`` object in an inspect row, in order.
OBSERVED_FIELDS: tuple[str, ...] = (
    "model",
    "effort",
    "model_status",
    "effort_status",
    "ts",
    "source_locator",
)
ReceiptsState = Literal["absent", "ok", "invalid"]
RECEIPTS_STATES: tuple[ReceiptsState, ...] = get_args(ReceiptsState)

# --- Claude transcript field names (see the module docstring) -------------------------------
CLAUDE_ENTRY_TYPE = "assistant"
CLAUDE_MODEL_PATH: tuple[str, ...] = ("message", "model")
CLAUDE_EFFORT_FIELD = "effort"
CLAUDE_AGENT_TYPE_FIELD = "attributionAgent"
CLAUDE_SYNTHETIC_MODEL = "<synthetic>"
CLAUDE_PROJECTS_DIRECTORY: tuple[str, ...] = (".claude", "projects")
CLAUDE_SUBAGENT_GLOB = "subagents/**/agent-*.jsonl"

# --- Codex rollout field names (see the module docstring) -----------------------------------
CODEX_SESSION_META_TYPE = "session_meta"
CODEX_TURN_CONTEXT_TYPE = "turn_context"
CODEX_SPAWN_PATH: tuple[str, ...] = ("payload", "source", "subagent", "thread_spawn")
CODEX_AGENT_TYPE_FIELD = "agent_role"
CODEX_HISTORY_START_PATH: tuple[str, ...] = ("payload", "subagent_history_start_ordinal")
CODEX_MODEL_PATH: tuple[str, ...] = ("payload", "model")
CODEX_EFFORT_PATH: tuple[str, ...] = ("payload", "effort")
CODEX_CWD_PATH: tuple[str, ...] = ("payload", "cwd")
CODEX_SESSIONS_DIRECTORY: tuple[str, ...] = (".codex", "sessions")
CODEX_ROLLOUT_GLOB = "**/rollout-*.jsonl"

# A recorded metadata value longer than this, or holding a control character, is not trusted.
_MAX_VALUE_LENGTH = 4096
_SLUG_RE = re.compile(r"[^A-Za-z0-9]")
_BOM = b"\xef\xbb\xbf"


class ObserveInputError(ValueError):
    """Raised when ``observe`` cannot make a receipt; nothing has been written."""


class HomeUnavailableError(ValueError):
    """No home directory can be determined (``Path.home()``, or a ``~`` that cannot expand)."""


# --- Small readers --------------------------------------------------------------------------


def _dig(value: object, path: Sequence[str]) -> object:
    """``value[path[0]][path[1]]...``, or ``None`` when any step is not a JSON object key."""
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _clean(value: object) -> str | None:
    """A recorded metadata string, or ``None`` when it is missing, empty or not trustworthy."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_VALUE_LENGTH:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return None
    return text


def _ordinal(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _distinct(values: Iterable[str | None]) -> tuple[str, ...]:
    """The non-``None`` values, de-duplicated in first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        if value is not None:
            seen.setdefault(value, None)
    return tuple(seen)


def _entries(path: Path) -> Iterator[tuple[int, dict[str, object] | None]]:
    """``(0-based line index, JSON object or None)`` for every non-blank line of ``path``.

    ``None`` marks a line that is not a JSON object. Raises ``OSError`` when the file cannot be
    opened or read.
    """
    with path.open("rb") as fh:
        for index, raw in enumerate(fh):
            line = raw[len(_BOM) :] if index == 0 and raw.startswith(_BOM) else raw
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except (ValueError, RecursionError):
                yield index, None
                continue
            yield index, entry if isinstance(entry, dict) else None


# --- Transcript parsing ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """What one transcript records: agent type(s), model(s) and effort(s). Metadata only."""

    agent_types: tuple[str, ...]
    models: tuple[str, ...]
    efforts: tuple[str, ...]
    skipped_lines: int

    @property
    def agent_type(self) -> str | None:
        """The recorded agent type(s) joined by ``|``, or ``None`` when none is recorded."""
        return MULTI_VALUE_SEPARATOR.join(self.agent_types) if self.agent_types else None

    @property
    def model(self) -> str | None:
        return MULTI_VALUE_SEPARATOR.join(self.models) if self.models else None

    @property
    def effort(self) -> str:
        return MULTI_VALUE_SEPARATOR.join(self.efforts) if self.efforts else UNKNOWN_EFFORT


def parse_claude_transcript(path: Path) -> Observation:
    """Read a Claude Code transcript's assistant-line metadata. Raises ``OSError``."""
    turns: list[tuple[str | None, str | None, str | None]] = []
    skipped = 0
    for _, entry in _entries(path):
        if entry is None:
            skipped += 1
            continue
        if entry.get("type") != CLAUDE_ENTRY_TYPE:
            continue
        model = _clean(_dig(entry, CLAUDE_MODEL_PATH))
        if model == CLAUDE_SYNTHETIC_MODEL:
            continue
        turns.append(
            (
                _clean(entry.get(CLAUDE_AGENT_TYPE_FIELD)),
                model,
                _clean(entry.get(CLAUDE_EFFORT_FIELD)),
            )
        )
    agent_types = _distinct(agent for agent, _, _ in turns)
    if len(agent_types) == 1:
        # Count only the turns the host attributed to the agent (a fork's inherited turn has none).
        turns = [turn for turn in turns if turn[0] == agent_types[0]]
    return Observation(
        agent_types=agent_types,
        models=_distinct(model for _, model, _ in turns),
        efforts=_distinct(effort for _, _, effort in turns),
        skipped_lines=skipped,
    )


def _codex_agent_type(meta: Mapping[str, object]) -> str | None:
    return _clean(_dig(meta, (*CODEX_SPAWN_PATH, CODEX_AGENT_TYPE_FIELD)))


def parse_codex_rollout(path: Path) -> Observation:
    """Read a Codex rollout's own ``session_meta`` and its own ``turn_context`` metadata.

    Raises ``OSError``, or ``ObserveInputError`` when the file has no ``session_meta`` line.
    """
    meta: dict[str, object] | None = None
    turns: list[tuple[int, str | None, str | None]] = []
    skipped = 0
    for index, entry in _entries(path):
        if entry is None:
            skipped += 1
            continue
        kind = entry.get("type")
        if kind == CODEX_SESSION_META_TYPE and meta is None:
            meta = entry  # the first session_meta is this thread's; a later one is inherited
        elif kind == CODEX_TURN_CONTEXT_TYPE:
            model = _clean(_dig(entry, CODEX_MODEL_PATH))
            turns.append((index, model, _clean(_dig(entry, CODEX_EFFORT_PATH))))
    if meta is None:
        raise ObserveInputError(
            f"{str(path)!r} has no {CODEX_SESSION_META_TYPE!r} line, so it is not a Codex rollout"
        )
    start = _ordinal(_dig(meta, CODEX_HISTORY_START_PATH))
    own = [turn for turn in turns if start is None or turn[0] >= start]
    agent_type = _codex_agent_type(meta)
    return Observation(
        agent_types=() if agent_type is None else (agent_type,),
        models=_distinct(model for _, model, _ in own),
        efforts=_distinct(effort for _, _, effort in own),
        skipped_lines=skipped,
    )


HOST_PARSERS: Mapping[str, Callable[[Path], Observation]] = {
    "claude": parse_claude_transcript,
    "codex": parse_codex_rollout,
}


# --- Finding the latest transcript ----------------------------------------------------------


def claude_project_slug(project_dir: str) -> str:
    """Claude Code's project folder name: every non-alphanumeric character becomes ``-``."""
    return _SLUG_RE.sub("-", os.path.abspath(project_dir))


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(os.path.abspath(a))) == os.path.normcase(
        os.path.normpath(os.path.abspath(b))
    )


def _newest_first(paths: Iterable[Path]) -> list[Path]:
    stamped: list[tuple[int, str, Path]] = []
    for path in paths:
        try:
            if path.is_file():
                stamped.append((path.stat().st_mtime_ns, str(path), path))
        except OSError:
            continue
    stamped.sort(reverse=True)
    return [path for _, _, path in stamped]


def _latest_claude(home: Path, project_dir: str | None) -> Path | None:
    root = home.joinpath(*CLAUDE_PROJECTS_DIRECTORY)
    try:
        projects = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return None
    if project_dir is not None:
        slug = os.path.normcase(claude_project_slug(project_dir))
        projects = [entry for entry in projects if os.path.normcase(entry.name) == slug]
    found: list[Path] = []
    for project in projects:
        try:
            found.extend(project.glob(f"*/{CLAUDE_SUBAGENT_GLOB}"))
        except OSError:
            continue
    newest = _newest_first(found)
    return newest[0] if newest else None


def _first_entry(path: Path) -> dict[str, object] | None:
    """The first non-blank line of ``path`` as a JSON object, or ``None``.

    Codex writes the thread's own ``session_meta`` first, so nothing past it is read.
    """
    try:
        with path.open("rb") as fh:
            for raw in fh:
                line = raw.removeprefix(_BOM)
                if not line.strip():
                    continue
                entry = json.loads(line)
                return entry if isinstance(entry, dict) else None
    except (OSError, ValueError, RecursionError):
        return None
    return None


def _latest_codex(home: Path, project_dir: str | None) -> Path | None:
    root = home.joinpath(*CODEX_SESSIONS_DIRECTORY)
    try:
        rollouts = _newest_first(root.glob(CODEX_ROLLOUT_GLOB)) if root.is_dir() else []
    except OSError:
        return None
    for path in rollouts:  # newest first: the first match is the latest
        meta = _first_entry(path)
        if meta is None or meta.get("type") != CODEX_SESSION_META_TYPE:
            continue
        if not isinstance(_dig(meta, CODEX_SPAWN_PATH), dict):
            continue  # not a spawned subagent thread
        if project_dir is not None:
            cwd = _clean(_dig(meta, CODEX_CWD_PATH))
            if cwd is None or not _same_path(cwd, project_dir):
                continue
        return path
    return None


def latest_transcript(host: str, home: Path, project_dir: str | None) -> Path:
    """The most recently modified subagent transcript for ``host``.

    Raises ``ObserveInputError`` when there is none.
    """
    if host == "claude":
        found = _latest_claude(home, project_dir)
        where = home.joinpath(*CLAUDE_PROJECTS_DIRECTORY)
        if project_dir is not None:
            where = where / claude_project_slug(project_dir)
    else:
        found = _latest_codex(home, project_dir)
        where = home.joinpath(*CODEX_SESSIONS_DIRECTORY)
    if found is None:
        scope = "" if project_dir is None else f" for project {project_dir!r}"
        raise ObserveInputError(
            f"no {host} subagent transcript found under {str(where)!r}{scope}; no receipt written"
        )
    return found


# --- Receipts -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Receipt:
    """One requested-versus-observed record (one line of ``receipts.jsonl``)."""

    ts: str
    host: str
    role: str
    agent_type: str | None
    requested_model: str | None
    requested_effort: str | None
    observed_model: str
    observed_effort: str
    source_locator: str
    registry_sha256: str | None

    def to_json(self) -> dict[str, str | None]:
        return {field: getattr(self, field) for field in RECEIPT_FIELDS}


def receipts_path(home: Path) -> Path:
    return home / CONFIG_DIRECTORY_NAME / RECEIPTS_FILENAME


def _utc_now() -> str:
    """The receipt timestamp; factored out so tests can pin it."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def append_receipt(path: Path, receipt: Receipt) -> None:
    """Append ``receipt`` as one JSON line. Raises ``OSError``.

    A previous torn write (no trailing newline) is closed first, so the new line stays whole.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = b""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        size = 0
    if size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                prefix = b"\n"
    line = json.dumps(receipt.to_json(), ensure_ascii=True) + "\n"
    with path.open("ab") as fh:
        fh.write(prefix + line.encode("ascii"))
        fh.flush()
        os.fsync(fh.fileno())


def _receipt_text(entry: Mapping[str, object], field: str) -> str:
    value = entry[field]
    if not isinstance(value, str) or _clean(value) is None:
        raise ValueError(field)
    return value


def _receipt_optional(entry: Mapping[str, object], field: str) -> str | None:
    value = entry[field]
    if value is None:
        return None
    return _receipt_text(entry, field)


def _parse_receipt(entry: object) -> Receipt | None:
    """A receipt from one parsed line, or ``None`` when the line is not a valid receipt.

    Every ``RECEIPT_FIELDS`` key is required (extra keys are ignored); ``agent_type``,
    ``requested_*`` and ``registry_sha256`` may be null, the rest are one-line strings.
    """
    if not isinstance(entry, dict) or any(field not in entry for field in RECEIPT_FIELDS):
        return None
    try:
        receipt = Receipt(
            ts=_receipt_text(entry, "ts"),
            host=_receipt_text(entry, "host"),
            role=_receipt_text(entry, "role"),
            agent_type=_receipt_optional(entry, "agent_type"),
            requested_model=_receipt_optional(entry, "requested_model"),
            requested_effort=_receipt_optional(entry, "requested_effort"),
            observed_model=_receipt_text(entry, "observed_model"),
            observed_effort=_receipt_text(entry, "observed_effort"),
            source_locator=_receipt_text(entry, "source_locator"),
            registry_sha256=_receipt_optional(entry, "registry_sha256"),
        )
    except ValueError:
        return None
    return receipt if receipt.host in ALLOWED_HOSTS else None


@dataclass(frozen=True, slots=True)
class ReceiptLog:
    """The receipts file as read by ``inspect``: valid receipts in file order, and what failed."""

    path: Path | None
    state: ReceiptsState
    receipts: tuple[Receipt, ...]
    error: str | None


def load_receipts(home: Path) -> ReceiptLog:
    """Read ``<home>/.switchboard/receipts.jsonl``. Never raises.

    A missing file is ``absent``. One that cannot be read is ``invalid`` with no receipts. A
    readable file is ``ok``; malformed lines in it are skipped and counted in ``error``.
    """
    path = receipts_path(home)
    try:
        if not path.exists():
            return ReceiptLog(path=path, state="absent", receipts=(), error=None)
        receipts: list[Receipt] = []
        skipped = 0
        for _, entry in _entries(path):
            receipt = _parse_receipt(entry)
            if receipt is None:
                skipped += 1
            else:
                receipts.append(receipt)
    except OSError as exc:
        return ReceiptLog(
            path=path, state="invalid", receipts=(), error=f"could not read receipts: {exc}"
        )
    error = None if skipped == 0 else f"{skipped} malformed receipt line(s) skipped"
    return ReceiptLog(path=path, state="ok", receipts=tuple(receipts), error=error)


def latest_receipts(receipts: Iterable[Receipt]) -> dict[tuple[str, str], Receipt]:
    """``{(role, host): the last receipt for them}``; unattributed receipts never join a row."""
    latest: dict[tuple[str, str], Receipt] = {}
    for receipt in receipts:
        if receipt.role != UNATTRIBUTED:
            latest[(receipt.role, receipt.host)] = receipt
    return latest


def field_status(requested: str, observed: str) -> ObservedStatus:
    """Compare one requested value with one observed value."""
    if requested == INHERIT:
        return "inherit"
    if observed == UNKNOWN_EFFORT:
        return "unknown"
    return "match" if requested == observed else "mismatch"


@dataclass(frozen=True, slots=True)
class HostObserved:
    """One host's last receipt for a role, compared with the current registry row."""

    model: str
    effort: str
    model_status: ObservedStatus
    effort_status: ObservedStatus
    ts: str
    source_locator: str

    def to_json(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in OBSERVED_FIELDS}


def observed_for(
    row: RoleRow, host: str, latest: Mapping[tuple[str, str], Receipt]
) -> HostObserved | None:
    """``row``'s last receipt on ``host`` against the row's current pin, or ``None``."""
    receipt = latest.get((row.role, host))
    if receipt is None:
        return None
    pin = row.host(host)
    return HostObserved(
        model=receipt.observed_model,
        effort=receipt.observed_effort,
        model_status=field_status(pin.model, receipt.observed_model),
        effort_status=field_status(pin.effort, receipt.observed_effort),
        ts=receipt.ts,
        source_locator=receipt.source_locator,
    )


def observed_json(row: RoleRow, latest: Mapping[tuple[str, str], Receipt]) -> dict[str, object]:
    """The ``observed`` value of one inspect row: per host, the last receipt or ``unknown``."""
    out: dict[str, object] = {}
    for host in ALLOWED_HOSTS:
        observed = observed_for(row, host, latest)
        out[host] = OBSERVED_UNKNOWN if observed is None else observed.to_json()
    return out


# The keys of one inspect role row: the registry row's keys, then ``observed``.
INSPECT_ROLE_FIELDS: tuple[str, ...] = (*ROLE_JSON_FIELDS, "observed")


def inspect_role_rows(rows: Iterable[RoleRow], log: ReceiptLog) -> list[dict[str, object]]:
    """The inspect role rows: each registry row plus its per-host ``observed`` value."""
    latest = latest_receipts(log.receipts)
    return [{**row.to_json(), "observed": observed_json(row, latest)} for row in rows]


def _expand_user(text: str, hint: str) -> Path:
    """``Path(text).expanduser()``, raising ``HomeUnavailableError`` when ``~`` cannot expand.

    The message names ``text`` and ends in ``hint``, the way to avoid the expansion.
    """
    try:
        return Path(text).expanduser()
    except RuntimeError as exc:
        raise HomeUnavailableError(
            f"could not expand {text!r}: could not determine the home directory ({exc}); {hint}"
        ) from exc


def resolve_home(home: str | None) -> Path:
    """``--home``, else the user's home directory, as an absolute path.

    Raises ``HomeUnavailableError`` when the home directory cannot be determined, either for
    the default or for a ``--home`` that starts with ``~``. ``pathlib`` raises a bare
    ``RuntimeError`` for this case (no home environment variable and no account entry); this
    function and ``_expand_user`` convert it to that named ``ValueError`` (like
    ``ObserveInputError`` and ``registry.RegistryError``), so callers report it as data
    instead of a traceback.
    """
    if home is not None:
        return _expand_user(home, "give --home as a full path").absolute()
    try:
        base = Path.home()
    except RuntimeError as exc:
        raise HomeUnavailableError(
            f"could not determine the home directory ({exc}); pass --home <dir>"
        ) from exc
    return base.absolute()


def load_home_receipts(home: str | None) -> ReceiptLog:
    """``load_receipts`` for ``--home`` (else the user's home). Never raises.

    A home directory that cannot be determined is reported like an unreadable receipts log:
    ``invalid``, no receipts, the reason in ``error``, and no ``path`` (``None``; the only
    ``ReceiptLog`` without one, since there is no file).
    """
    try:
        home_dir = resolve_home(home)
    except HomeUnavailableError as exc:
        return ReceiptLog(path=None, state="invalid", receipts=(), error=str(exc))
    return load_receipts(home_dir)


# --- One observe run (cli.py prints it and maps it to an exit code) -------------------------


@dataclass(frozen=True, slots=True)
class ObserveResult:
    """A receipt ready to append, where it goes, and the advisories for stderr."""

    receipt: Receipt
    transcript: Path
    receipts_path: Path
    advisories: tuple[str, ...]


def _attribute(
    agent_types: Sequence[str], registry: RegistryResult
) -> tuple[RoleRow | None, str | None]:
    """The registry row the host attributed the dispatch to, or ``None`` with the reason."""
    if not agent_types:
        return None, "the transcript records no agent type"
    if len(agent_types) > 1:
        listed = ", ".join(repr(agent) for agent in agent_types)
        return None, f"the transcript records {len(agent_types)} agent types ({listed})"
    agent = agent_types[0]
    rows = {row.role: row for row in registry.roles}
    if agent.startswith(AGENT_NAME_PREFIX):
        row = rows.get(agent[len(AGENT_NAME_PREFIX) :])
        if row is not None:
            return row, None
    return None, (
        f"agent type {agent!r} is not the agent of a registry role ({AGENT_NAME_PREFIX}<role>)"
    )


def prepare_observation(
    *,
    host: str,
    transcript: str | None,
    latest: bool,
    project_dir: str | None,
    home: str | None,
    registry_path: str | None,
) -> ObserveResult:
    """Load the registry, find and read the transcript, and build its receipt. Writes nothing.

    Raises ``ObserveInputError`` (its message is the one advisory line) when the registry is
    not ok, the home cannot be determined or is not a directory, a ``~`` in ``--transcript``
    cannot be expanded, no transcript is found or readable, or the counted lines record no
    model.
    """
    if host not in HOST_PARSERS:
        raise ObserveInputError(f"unknown host {host!r}; allowed: {list(ALLOWED_HOSTS)}")
    registry = load_registry(registry_path)
    if registry.state != "ok":
        raise ObserveInputError(
            f"registry is {registry.state} ({registry.source}): {registry.error}; "
            "no receipt written"
        )
    try:
        home_dir = resolve_home(home)
    except HomeUnavailableError as exc:
        raise ObserveInputError(f"{exc}; no receipt written") from exc
    if not home_dir.is_dir():
        raise ObserveInputError(f"home {str(home_dir)!r} is not a directory; no receipt written")
    if latest:
        path = latest_transcript(host, home_dir, project_dir)
    elif transcript is not None:
        try:
            path = _expand_user(transcript, "give --transcript as a full path")
        except HomeUnavailableError as exc:
            raise ObserveInputError(f"{exc}; no receipt written") from exc
    else:
        raise ObserveInputError("give --transcript <path> or --latest; no receipt written")
    path = path.absolute()
    if not path.is_file():
        raise ObserveInputError(f"transcript {str(path)!r} is not a file; no receipt written")
    try:
        observation = HOST_PARSERS[host](path)
    except OSError as exc:
        raise ObserveInputError(
            f"could not read transcript {str(path)!r}: {exc}; no receipt written"
        ) from exc
    observed_model = observation.model
    if observed_model is None:
        raise ObserveInputError(
            f"transcript {str(path)!r} records no {host} model metadata, so it is not evidence "
            "of a dispatch; no receipt written"
        )

    advisories: list[str] = []
    if observation.skipped_lines:
        advisories.append(f"{observation.skipped_lines} unparseable transcript line(s) skipped")
    row, why_unattributed = _attribute(observation.agent_types, registry)
    if row is None:
        advisories.append(f"{why_unattributed}; the receipt is {UNATTRIBUTED} (no role is guessed)")
    if len(observation.models) > 1:
        advisories.append(
            f"the counted lines record {len(observation.models)} models; observed_model lists "
            f"them all ({observed_model})"
        )
    if len(observation.efforts) > 1:
        advisories.append(
            f"the counted lines record {len(observation.efforts)} efforts; observed_effort "
            f"lists them all ({observation.effort})"
        )
    pin = None if row is None else row.host(host)
    receipt = Receipt(
        ts=_utc_now(),
        host=host,
        role=UNATTRIBUTED if row is None else row.role,
        agent_type=observation.agent_type,
        requested_model=None if pin is None else pin.model,
        requested_effort=None if pin is None else pin.effort,
        observed_model=observed_model,
        observed_effort=observation.effort,
        source_locator=str(path),
        registry_sha256=registry.sha256,
    )
    return ObserveResult(
        receipt=receipt,
        transcript=path,
        receipts_path=receipts_path(home_dir),
        advisories=tuple(advisories),
    )
