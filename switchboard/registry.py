"""Switchboard model registry: the committed role -> per-host model and effort table.

The registry is ``switchboard/registry/models.json`` (schema v1), committed so git history is
the swap audit trail (decision R-P1). One row per role names, for each host (``claude`` and
``codex``), an exact model ID or ``inherit`` and an effort level or ``inherit``, plus the
measure-twice ``claim_id`` the row cites. ``inherit`` means no key is written for that host,
so the host resolves exactly as it does today.

Resolution order (first hit wins): an explicit ``--registry <path>``, then the
``$SWITCHBOARD_REGISTRY`` environment variable, then the repo default. Loading never raises:
a missing file is the ``absent`` state and any read, parse, or validation failure is the
``invalid`` state, each carried as data with an error string (``load_registry``).

HONEST SCOPE: this module reads and validates the table. Nothing here dispatches by role or
writes a host file; ``inspect --roles`` renders the requested values only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from switchboard.config import ALLOWED_EFFORT_TIERS, SAFE_NAME_RE

REGISTRY_SCHEMA_VERSION = 1
REGISTRY_ENV_VAR = "SWITCHBOARD_REGISTRY"
REGISTRY_DIRECTORY_NAME = "registry"
REGISTRY_FILENAME = "models.json"
# Public contract facts used by the observatory fixture and its drift test.
REGISTRY_SOURCE_PRECEDENCE: tuple[str, ...] = ("arg", "env", "repo")
RegistryState = Literal["absent", "invalid", "ok"]
REGISTRY_STATES: tuple[RegistryState, ...] = ("absent", "invalid", "ok")
# The only keys the registry document may carry at its top level.
REGISTRY_TOP_LEVEL_FIELDS: tuple[str, ...] = ("schema_version", "roles")

# The value that means "write no key; the host resolves as it does today".
INHERIT = "inherit"

# --- Role vocabulary (decision R-D4) --------------------------------------------------------
# The roles the registry must define, exactly. Order is the stable order ``parse_roles``
# reports in. Adding or removing a role is a reviewed change here plus a row in models.json.
ALLOWED_ROLES: tuple[str, ...] = (
    "builder",
    "reviewer",
    "reviewer-style",
    "research-verifier",
    "eval-grader",
    "goblin-judge",
    "motion-judge",
    "diagnosis",
    "author",
    "scanner",
    "researcher",
    "extractor",
    "vision-judge",
    "final-judge",
)
# Role names are kebab-case, matching measure-twice tags (``reviewer-style``).
ROLE_NAME_PATTERN = "^[a-z][a-z0-9-]*$"
_ROLE_NAME_RE = re.compile(ROLE_NAME_PATTERN)

# The hosts a row pins, exactly (Copilot is not a registry host: decision R-P3).
ALLOWED_HOSTS: tuple[str, ...] = ("claude", "codex")
# The keys of one host pin; both are required.
HOST_PIN_FIELDS: tuple[str, ...] = ("model", "effort")
# The keys one role row may carry, in report order. Every key is required except ``evidence``.
ROLE_ROW_FIELDS: tuple[str, ...] = (
    "description",
    "read_only",
    *ALLOWED_HOSTS,
    "claim_id",
    "evidence",
)
ROLE_OPTIONAL_FIELDS: frozenset[str] = frozenset({"evidence"})

# Evidence states a cited claim can be in. Mirrors measure-twice's ledger ``ClaimStatus``
# (switchboard is zero-dependency, so it cannot import it; measure-twice imports switchboard).
CLAIM_STATUSES: tuple[str, ...] = ("MEASURED", "PARTIAL", "ASSERTED", "STALE")

# --- Model ID rules (decisions R-D3 and R-P7) -----------------------------------------------
# A bare alias moves silently when a new model ships, which is an unbenchmarked swap.
REJECTED_MODEL_ALIASES: tuple[str, ...] = ("haiku", "sonnet", "opus", "fable")
# Fable is never pinned: the operator starts Fable by hand and nothing here dispatches it. Any
# model value containing one of these (case-insensitive) is invalid, so ``claude-fable-5-1``,
# ``fable-5`` and ``claude-fable5-1`` all fail, not only the ``claude-fable-`` prefix.
REJECTED_MODEL_SUBSTRINGS: tuple[str, ...] = ("fable",)

# --- Effort levels per host (decision R-P6) -------------------------------------------------
# Codex ``model_reasoning_effort`` values. Sources, both read 2026-11-08:
#   * the installed codex-cli 0.147.0: ``codex debug models`` (the bundled model catalog)
#     advertises, as the union of every model's ``supported_reasoning_levels``: low, medium,
#     high, xhigh, max, ultra (gpt-5.6-sol and gpt-5.6-terra advertise all six; gpt-5.5 and
#     older stop at xhigh). Its app-server schema types the config value as "a non-empty
#     reasoning effort value advertised by the model", so the CLI itself does not enumerate it.
#   * the official config reference (https://learn.chatgpt.com/docs/config-file/config-reference,
#     redirected from developers.openai.com/codex/config-reference), ``model_reasoning_effort``:
#     "Reasoning effort advertised by the selected model, such as `low`, `medium`, `high`,
#     `xhigh`, `max`, or `ultra`. Available levels depend on the model and client."
# Claude rows use ``ALLOWED_EFFORT_TIERS`` (switchboard.config); the two lists stay separate.
ALLOWED_CODEX_EFFORT_TIERS: frozenset[str] = frozenset(
    {"low", "medium", "high", "xhigh", "max", "ultra"}
)


class RegistryError(ValueError):
    """Raised when a registry document fails validation."""


def _host_effort_levels(host: str) -> frozenset[str]:
    """The effort levels ``host`` accepts besides ``inherit``, read at call time."""
    if host == "claude":
        return ALLOWED_EFFORT_TIERS
    return ALLOWED_CODEX_EFFORT_TIERS


@dataclass(frozen=True, slots=True)
class HostPin:
    """One host's requested model and effort for a role; either may be ``inherit``."""

    model: str
    effort: str

    def to_json(self) -> dict[str, str]:
        return {"model": self.model, "effort": self.effort}


@dataclass(frozen=True, slots=True)
class RoleRow:
    """One validated registry row: the role's per-host pins and the claim it cites."""

    role: str
    description: str
    read_only: bool
    claude: HostPin
    codex: HostPin
    claim_id: str
    evidence: str | None

    def host(self, name: str) -> HostPin:
        """The pin for host ``name`` (one of ``ALLOWED_HOSTS``)."""
        if name == "claude":
            return self.claude
        if name == "codex":
            return self.codex
        raise KeyError(name)

    def to_json(self) -> dict[str, object]:
        return {
            "role": self.role,
            "description": self.description,
            "read_only": self.read_only,
            "claude": self.claude.to_json(),
            "codex": self.codex.to_json(),
            "claim_id": self.claim_id,
            "evidence": self.evidence,
        }


# The key set of one ``inspect --roles --json`` row, in order.
ROLE_JSON_FIELDS: tuple[str, ...] = ("role", *ROLE_ROW_FIELDS)


def _validate_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{label} must be a non-empty string, got {value!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise RegistryError(f"{label} must be one line with no control characters")
    return value


def _validate_model(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{label} must be a non-empty string, got {value!r}")
    if value == INHERIT:
        return value
    # fullmatch, not config.py's .match: the pattern's "$" also matches before a trailing "\n".
    if not SAFE_NAME_RE.fullmatch(value):
        raise RegistryError(
            f"{label} {value!r} contains unsafe characters "
            f"(allowed: letters, digits, '.', '_', '-')"
        )
    lowered = value.lower()
    if lowered in REJECTED_MODEL_ALIASES:
        raise RegistryError(
            f"{label} {value!r} is a bare alias; use an exact model ID or {INHERIT!r}"
        )
    if any(marker in lowered for marker in REJECTED_MODEL_SUBSTRINGS):
        # Decision R-P7: the operator starts Fable by hand; the registry never dispatches it.
        raise RegistryError(
            f"{label} {value!r} names a Fable model; a registry row may not pin a Fable model"
        )
    if not any(ch.isdigit() for ch in value):
        raise RegistryError(
            f"{label} {value!r} has no digit, so it is not an exact model ID; "
            f"use an exact ID or {INHERIT!r}"
        )
    return value


def _validate_effort(host: str, value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{label} must be a non-empty string, got {value!r}")
    if value == INHERIT:
        return value
    levels = _host_effort_levels(host)
    if value in levels:
        return value
    allowed = [INHERIT, *sorted(levels)]
    for other in ALLOWED_HOSTS:
        if other != host and value in _host_effort_levels(other):
            raise RegistryError(
                f"{label} {value!r} is a {other} effort level that {host} lacks; "
                f"{host} accepts {allowed}"
            )
    raise RegistryError(f"{label} {value!r} is not a {host} effort level; allowed: {allowed}")


def _parse_host_pin(role: str, host: str, pin: object) -> HostPin:
    label = f"roles[{role!r}].{host}"
    if not isinstance(pin, dict):
        raise RegistryError(f"{label} must be an object of model and effort, got {pin!r}")
    unknown = sorted(set(pin) - set(HOST_PIN_FIELDS))
    if unknown:
        raise RegistryError(
            f"{label} has unknown key(s) {unknown}; allowed: {list(HOST_PIN_FIELDS)}"
        )
    missing = [key for key in HOST_PIN_FIELDS if key not in pin]
    if missing:
        raise RegistryError(f"{label} is missing key(s) {missing}")
    return HostPin(
        model=_validate_model(pin["model"], f"{label}.model"),
        effort=_validate_effort(host, pin["effort"], f"{label}.effort"),
    )


def _parse_row(role: str, row: object) -> RoleRow:
    label = f"roles[{role!r}]"
    if not isinstance(row, dict):
        raise RegistryError(f"{label} must be an object, got {row!r}")
    unknown = sorted(set(row) - set(ROLE_ROW_FIELDS))
    if unknown:
        raise RegistryError(
            f"{label} has unknown key(s) {unknown}; allowed: {list(ROLE_ROW_FIELDS)} "
            f"(the hosts are exactly {list(ALLOWED_HOSTS)})"
        )
    missing = [key for key in ROLE_ROW_FIELDS if key not in ROLE_OPTIONAL_FIELDS and key not in row]
    if missing:
        raise RegistryError(f"{label} is missing key(s) {missing}")

    read_only = row["read_only"]
    if not isinstance(read_only, bool):
        raise RegistryError(f"{label}.read_only must be a bool, got {read_only!r}")
    claim_id = row["claim_id"]
    if not isinstance(claim_id, str) or not SAFE_NAME_RE.fullmatch(claim_id):
        raise RegistryError(
            f"{label}.claim_id must be a non-empty name of letters, digits, '.', '_' or '-', "
            f"got {claim_id!r}"
        )
    evidence = row.get("evidence")
    return RoleRow(
        role=role,
        description=_validate_text(row["description"], f"{label}.description"),
        read_only=read_only,
        claude=_parse_host_pin(role, "claude", row["claude"]),
        codex=_parse_host_pin(role, "codex", row["codex"]),
        claim_id=claim_id,
        evidence=None if evidence is None else _validate_text(evidence, f"{label}.evidence"),
    )


def parse_roles(document: object) -> tuple[RoleRow, ...]:
    """Validate a parsed registry document; return one row per ``ALLOWED_ROLES`` entry.

    Rows come back in ``ALLOWED_ROLES`` order whatever the file order. Pure: no model or effort
    is substituted for ``inherit``. Raises ``RegistryError`` naming the first failing value.
    """
    if not isinstance(document, dict):
        raise RegistryError(f"registry must be a JSON object, got {type(document).__name__}")
    unknown = sorted(set(document) - set(REGISTRY_TOP_LEVEL_FIELDS))
    if unknown:
        raise RegistryError(
            f"unknown registry key(s): {unknown}; allowed: {list(REGISTRY_TOP_LEVEL_FIELDS)}"
        )
    version = document.get("schema_version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != REGISTRY_SCHEMA_VERSION
    ):
        raise RegistryError(
            f"registry schema_version must be {REGISTRY_SCHEMA_VERSION}, got {version!r}"
        )
    roles = document.get("roles")
    if not isinstance(roles, dict):
        raise RegistryError(f"registry roles must be an object of role -> row, got {roles!r}")

    rows: dict[str, RoleRow] = {}
    for role, row in roles.items():
        if not isinstance(role, str) or not _ROLE_NAME_RE.fullmatch(role):
            raise RegistryError(f"role name {role!r} must match {ROLE_NAME_PATTERN}")
        if role not in ALLOWED_ROLES:
            raise RegistryError(f"unknown role {role!r}; allowed: {list(ALLOWED_ROLES)}")
        rows[role] = _parse_row(role, row)
    missing = [role for role in ALLOWED_ROLES if role not in rows]
    if missing:
        raise RegistryError(f"registry is missing role(s) {missing}")
    return tuple(rows[role] for role in ALLOWED_ROLES)


@dataclass(frozen=True, slots=True)
class RegistryResult:
    """The outcome of ``load_registry``: a state, the selected source, and rows when ok."""

    state: RegistryState
    source: str
    roles: tuple[RoleRow, ...]
    error: str | None


def _default_registry_path() -> Path:
    """The committed repo default, ``switchboard/registry/models.json``.

    Factored into its own function so tests can monkeypatch it.
    """
    return Path(__file__).resolve().parent.parent / REGISTRY_DIRECTORY_NAME / REGISTRY_FILENAME


def _resolve_registry_source(path: str | None = None) -> tuple[str, str]:
    """Return ``(source_label, candidate)`` by precedence without opening the file."""
    if path is not None:
        return f"arg:{path}", path
    env_path = os.environ.get(REGISTRY_ENV_VAR)
    if env_path:
        return f"env:{env_path}", env_path
    default = str(_default_registry_path())
    return f"repo:{default}", default


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """``json`` keeps the last of two equal keys; a duplicated role must fail instead."""
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise RegistryError(f"duplicate key {key!r} in registry")
        out[key] = value
    return out


def load_registry(path: str | None = None) -> RegistryResult:
    """Resolve, read, and validate the registry. Never raises.

    Resolution order (first hit wins):

      1. explicit ``path`` (``--registry``)   -> source ``"arg:<path>"``
      2. ``$SWITCHBOARD_REGISTRY``            -> source ``"env:<path>"``
      3. the committed repo default           -> source ``"repo:<path>"``

    A selected file that does not exist is ``absent``; one that cannot be read, is not JSON, or
    fails validation is ``invalid``. Both carry an error string and no rows.
    """
    source, candidate = _resolve_registry_source(path)
    p = Path(candidate)
    try:
        exists = p.exists()
    except (OSError, ValueError) as exc:
        return RegistryResult(
            state="invalid", source=source, roles=(), error=f"could not stat registry: {exc}"
        )
    if not exists:
        return RegistryResult(
            state="absent",
            source=source,
            roles=(),
            error=f"registry file not found: {candidate!r}",
        )
    try:
        # utf-8-sig: a BOM (PowerShell 5.1 ``Set-Content -Encoding utf8`` adds one) is not an
        # invalid registry.
        with p.open(encoding="utf-8-sig") as fh:
            document = json.load(fh, object_pairs_hook=_reject_duplicate_keys)
        roles = parse_roles(document)
    except RegistryError as exc:
        return RegistryResult(state="invalid", source=source, roles=(), error=str(exc))
    except (OSError, ValueError, RecursionError) as exc:
        # ValueError covers UnicodeDecodeError, json.JSONDecodeError and the plain ValueError
        # json raises for an integer literal past ``sys.get_int_max_str_digits()``.
        return RegistryResult(
            state="invalid",
            source=source,
            roles=(),
            error=f"could not read registry {candidate!r}: {exc}",
        )
    return RegistryResult(state="ok", source=source, roles=roles, error=None)
