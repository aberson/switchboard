"""The committed role registry: loader states, validation rules, initial rows, contract drift.

The registry (``registry/models.json``) is the one table of role -> per-host model and effort.
These tests are HERMETIC: the autouse fixture unsets ``$SWITCHBOARD_REGISTRY`` and
``$SWITCHBOARD_CONFIG`` so an operator's environment never selects a different file. Tests
that need a modified registry copy the committed file into ``tmp_path`` and mutate the copy.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import switchboard.config as config_module
import switchboard.registry as registry_module
from switchboard.config import ALLOWED_EFFORT_TIERS
from switchboard.registry import (
    ALLOWED_CODEX_EFFORT_TIERS,
    ALLOWED_HOSTS,
    ALLOWED_ROLES,
    CLAIM_STATUSES,
    HOST_PIN_FIELDS,
    REGISTRY_ENV_VAR,
    REGISTRY_SCHEMA_VERSION,
    REGISTRY_SOURCE_PRECEDENCE,
    REGISTRY_STATES,
    REGISTRY_TOP_LEVEL_FIELDS,
    REJECTED_MODEL_ALIASES,
    REJECTED_MODEL_SUBSTRINGS,
    ROLE_NAME_PATTERN,
    ROLE_OPTIONAL_FIELDS,
    ROLE_ROW_FIELDS,
    load_registry,
)

PROJECT_ROOT = Path(__file__).parents[1]
COMMITTED_REGISTRY = PROJECT_ROOT / "registry" / "models.json"
CONTRACT_PATH = PROJECT_ROOT / "docs" / "observatory-contract.json"

Doc = dict[str, Any]


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(REGISTRY_ENV_VAR, raising=False)
    monkeypatch.delenv("SWITCHBOARD_CONFIG", raising=False)
    monkeypatch.setattr("switchboard.config._default_config_path", lambda: tmp_path / "absent.json")


def _committed() -> Doc:
    data = json.loads(COMMITTED_REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def _write(tmp_path: Path, doc: object, name: str = "models.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --- The committed registry and its initial rows ------------------------------------------


def test_committed_registry_loads_ok_from_the_repo_default() -> None:
    result = load_registry()

    assert result.state == "ok"
    assert result.error is None
    assert result.source == f"repo:{COMMITTED_REGISTRY.resolve()}"
    assert [row.role for row in result.roles] == list(ALLOWED_ROLES)


# The plan's "Registry shape and initial rows" table, row for row.
_PLAN_ROWS: list[tuple[str, bool, str, str, str, str]] = [
    ("builder", False, "inherit", "inherit", "gpt-5.6-sol", "medium"),
    ("reviewer", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("reviewer-style", False, "claude-haiku-5-5", "inherit", "inherit", "inherit"),
    ("research-verifier", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("eval-grader", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("goblin-judge", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("motion-judge", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("diagnosis", False, "claude-opus-5-5", "inherit", "inherit", "inherit"),
    ("author", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("scanner", True, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("researcher", False, "claude-sonnet-5-5", "inherit", "inherit", "inherit"),
    ("extractor", False, "claude-sonnet-5-5", "low", "inherit", "inherit"),
    ("vision-judge", False, "claude-opus-5-5", "inherit", "gpt-5.6-sol", "inherit"),
    ("final-judge", False, "claude-opus-5-5", "inherit", "inherit", "inherit"),
]


def test_committed_rows_match_the_plan_table() -> None:
    rows = load_registry().roles
    actual = [
        (
            row.role,
            row.read_only,
            row.claude.model,
            row.claude.effort,
            row.codex.model,
            row.codex.effort,
            row.claim_id,
        )
        for row in rows
    ]
    # Each row cites its initial claim, ``registry-<role>-initial`` (the plan's shape example).
    assert actual == [(*plan_row, f"registry-{plan_row[0]}-initial") for plan_row in _PLAN_ROWS]


def test_every_committed_row_records_evidence() -> None:
    for row in load_registry().roles:
        assert isinstance(row.evidence, str) and row.evidence.strip(), row.role


# --- Single sources of truth ----------------------------------------------------------------


def test_claude_effort_levels_are_the_config_constant() -> None:
    # One owner: the registry imports config's tier set rather than re-declaring it.
    assert registry_module.ALLOWED_EFFORT_TIERS is config_module.ALLOWED_EFFORT_TIERS
    # The registry imports config's public name, which is the private object measure-twice
    # imports: one compiled regex, one literal.
    assert registry_module.SAFE_NAME_RE is config_module._SAFE_NAME_RE


def test_codex_levels_pin_the_primary_source_finding() -> None:
    # codex-cli 0.147.0 (`codex debug models`) and the official config reference agree on
    # these six. Under them every Claude level is also a Codex level, and ultra is Codex-only.
    assert ALLOWED_CODEX_EFFORT_TIERS == frozenset(
        {"low", "medium", "high", "xhigh", "max", "ultra"}
    )
    assert ALLOWED_EFFORT_TIERS - ALLOWED_CODEX_EFFORT_TIERS == frozenset()
    assert ALLOWED_CODEX_EFFORT_TIERS - ALLOWED_EFFORT_TIERS == frozenset({"ultra"})


# --- Resolution order and the absent state ------------------------------------------------


def test_explicit_path_beats_env_and_env_beats_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    arg_doc = _committed()
    arg_doc["roles"]["reviewer"]["claude"]["model"] = "claude-opus-5-5"
    env_doc = _committed()
    env_doc["roles"]["reviewer"]["claude"]["model"] = "claude-haiku-5-5"
    arg_path = _write(tmp_path, arg_doc, "arg.json")
    env_path = _write(tmp_path, env_doc, "env.json")
    monkeypatch.setenv(REGISTRY_ENV_VAR, str(env_path))

    from_arg = load_registry(str(arg_path))
    from_env = load_registry()

    assert from_arg.source == f"arg:{arg_path}"
    assert {r.role: r for r in from_arg.roles}["reviewer"].claude.model == "claude-opus-5-5"
    assert from_env.source == f"env:{env_path}"
    assert {r.role: r for r in from_env.roles}["reviewer"].claude.model == "claude-haiku-5-5"


def test_empty_env_var_falls_through_to_the_repo_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REGISTRY_ENV_VAR, "")
    assert load_registry().source.startswith("repo:")


@pytest.mark.parametrize("tier", ["arg", "env", "repo"])
def test_missing_selected_file_is_absent_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tier: str
) -> None:
    missing = tmp_path / "nope" / "models.json"
    if tier == "arg":
        result = load_registry(str(missing))
    elif tier == "env":
        monkeypatch.setenv(REGISTRY_ENV_VAR, str(missing))
        result = load_registry()
    else:
        monkeypatch.setattr("switchboard.registry._default_registry_path", lambda: missing)
        monkeypatch.setattr(
            "switchboard.registry._packaged_registry_path", lambda: tmp_path / "pkg" / "none.json"
        )
        result = load_registry()

    assert result.state == "absent"
    assert result.source == f"{tier}:{missing}"
    assert result.roles == ()
    assert result.error is not None and "not found" in result.error


# --- The default: the repository copy first, then the copy packaged in the wheel -----------


def test_checkout_reads_the_repository_copy_even_when_a_packaged_copy_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_doc = _committed()
    repo_doc["roles"]["reviewer"]["claude"]["model"] = "claude-opus-5-5"
    packaged_doc = _committed()
    packaged_doc["roles"]["reviewer"]["claude"]["model"] = "claude-haiku-5-5"
    repo_path = _write(tmp_path, repo_doc, "repo.json")
    packaged_path = _write(tmp_path, packaged_doc, "packaged.json")
    monkeypatch.setattr("switchboard.registry._default_registry_path", lambda: repo_path)
    monkeypatch.setattr("switchboard.registry._packaged_registry_path", lambda: packaged_path)

    result = load_registry()

    # A checkout edit takes effect without a rebuild: the repository copy wins.
    assert result.state == "ok"
    assert result.source == f"repo:{repo_path}"
    assert {r.role: r for r in result.roles}["reviewer"].claude.model == "claude-opus-5-5"


def test_installed_tool_without_a_repository_copy_reads_the_packaged_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packaged_path = _write(tmp_path, _committed(), "packaged.json")
    monkeypatch.setattr(
        "switchboard.registry._default_registry_path", lambda: tmp_path / "no-repo" / "models.json"
    )
    monkeypatch.setattr("switchboard.registry._packaged_registry_path", lambda: packaged_path)

    result = load_registry()

    assert result.state == "ok"
    assert result.source == f"package:{packaged_path}"
    assert [row.role for row in result.roles] == list(ALLOWED_ROLES)


def test_arg_and_env_still_outrank_the_packaged_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packaged_path = _write(tmp_path, _committed(), "packaged.json")
    arg_path = _write(tmp_path, _committed(), "arg.json")
    env_path = _write(tmp_path, _committed(), "env.json")
    monkeypatch.setattr(
        "switchboard.registry._default_registry_path", lambda: tmp_path / "no-repo" / "models.json"
    )
    monkeypatch.setattr("switchboard.registry._packaged_registry_path", lambda: packaged_path)
    monkeypatch.setenv(REGISTRY_ENV_VAR, str(env_path))

    assert load_registry(str(arg_path)).source == f"arg:{arg_path}"
    assert load_registry().source == f"env:{env_path}"


def test_packaged_path_is_the_wheel_force_include_target() -> None:
    # One source of truth: pyproject's force-include maps the committed file to the exact path
    # the resolver reads, relative to the package directory.
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
        wheel = tomllib.load(source)["tool"]["hatch"]["build"]["targets"]["wheel"]
    package_dir = Path(registry_module.__file__).resolve().parent
    target = registry_module._packaged_registry_path().relative_to(package_dir.parent).as_posix()

    assert wheel["force-include"] == {"registry/models.json": target}
    assert (
        registry_module._default_registry_path().relative_to(PROJECT_ROOT.resolve()).as_posix()
        == "registry/models.json"
    )


# --- Validation: every rule is red on garbage ----------------------------------------------

Mutation = Callable[[Doc], None]


def _set(path: tuple[str, ...], value: object) -> Mutation:
    def mutate(doc: Doc) -> None:
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


def _delete(path: tuple[str, ...]) -> Mutation:
    def mutate(doc: Doc) -> None:
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return mutate


_REVIEWER_CLAUDE_MODEL = ("roles", "reviewer", "claude", "model")
_REVIEWER_CLAUDE_EFFORT = ("roles", "reviewer", "claude", "effort")
_REVIEWER_CODEX_MODEL = ("roles", "reviewer", "codex", "model")
_REVIEWER_CODEX_EFFORT = ("roles", "reviewer", "codex", "effort")

# One case per validation branch.
_INVALID: list[tuple[str, Mutation, str]] = [
    # Model IDs: alias, Fable (substring, any case, either host), digitless, unsafe, non-string.
    ("alias", _set(_REVIEWER_CLAUDE_MODEL, "sonnet"), "bare alias"),
    ("fable-any-case-substring", _set(_REVIEWER_CLAUDE_MODEL, "Claude-Fable5-1"), "Fable"),
    ("fable-on-codex", _set(_REVIEWER_CODEX_MODEL, "claude-fable-5-1"), "Fable"),
    ("no-digit", _set(_REVIEWER_CLAUDE_MODEL, "claude-sonnet"), "no digit"),
    ("trailing-newline-model", _set(_REVIEWER_CLAUDE_MODEL, "claude-sonnet-5-5\n"), "unsafe"),
    ("null-model", _set(_REVIEWER_CLAUDE_MODEL, None), "non-empty"),
    # Effort per host.
    ("unknown-effort-claude", _set(_REVIEWER_CLAUDE_EFFORT, "extreme"), "not a claude effort"),
    ("unknown-effort-codex", _set(_REVIEWER_CODEX_EFFORT, "extreme"), "not a codex effort"),
    ("effort-not-string", _set(_REVIEWER_CLAUDE_EFFORT, 3), "non-empty"),
    # Hosts are exactly claude and codex.
    (
        "unknown-host",
        _set(("roles", "reviewer", "copilot"), {"model": "inherit", "effort": "inherit"}),
        "unknown key",
    ),
    ("missing-host", _delete(("roles", "reviewer", "codex")), "missing key"),
    ("host-not-object", _set(("roles", "reviewer", "claude"), "claude-sonnet-5-5"), "object"),
    ("host-extra-key", _set(("roles", "reviewer", "claude", "tier"), "low"), "unknown key"),
    ("host-missing-effort", _delete(("roles", "reviewer", "claude", "effort")), "missing key"),
    # Roles and rows.
    ("unknown-role", _set(("roles", "coordinator"), {}), "unknown role"),
    ("role-underscore", _set(("roles", "reviewer_style"), {}), "must match"),
    ("missing-role", _delete(("roles", "scanner")), "missing role"),
    ("row-not-object", _set(("roles", "reviewer"), "claude"), "must be an object"),
    ("row-bad-claim", _set(("roles", "reviewer", "claim_id"), "bad claim"), "claim_id"),
    ("row-read-only-str", _set(("roles", "scanner", "read_only"), "yes"), "read_only"),
    ("row-empty-description", _set(("roles", "reviewer", "description"), " "), "description"),
    ("row-multiline-description", _set(("roles", "reviewer", "description"), "a\nb"), "one line"),
    ("row-empty-evidence", _set(("roles", "reviewer", "evidence"), ""), "evidence"),
    # Document shape.
    ("schema-version-2", _set(("schema_version",), 2), "schema_version"),
    ("schema-version-bool", _set(("schema_version",), True), "schema_version"),
    ("top-level-extra", _set(("pins",), {}), "unknown registry key"),
    ("roles-not-object", _set(("roles",), ["reviewer"]), "roles must be an object"),
]


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [pytest.param(m, n, id=case) for case, m, n in _INVALID],
)
def test_invalid_registry_is_reported_as_invalid(
    tmp_path: Path, mutate: Mutation, needle: str
) -> None:
    doc = _committed()
    mutate(doc)
    result = load_registry(str(_write(tmp_path, doc)))

    assert result.state == "invalid"
    assert result.roles == ()
    assert result.error is not None
    assert needle in result.error


def test_effort_is_checked_against_each_hosts_own_levels(tmp_path: Path) -> None:
    # The primary proof, on the SHIPPED constants: ``ultra`` is a Codex level Claude lacks (see
    # the pin test above), so one value is invalid on a Claude row and valid on a Codex row.
    # ``max`` is the representative Claude acceptance; ``ultra`` the representative Codex one.
    def registry_with(host: str, level: str) -> str:
        doc = _committed()
        doc["roles"]["reviewer"][host]["effort"] = level
        return str(_write(tmp_path, doc, f"{host}-{level}.json"))

    claude_ultra = load_registry(registry_with("claude", "ultra"))

    assert claude_ultra.state == "invalid"
    assert claude_ultra.error is not None
    assert "'ultra' is a codex effort level that claude lacks" in claude_ultra.error
    assert load_registry(registry_with("codex", "ultra")).state == "ok"
    assert load_registry(registry_with("claude", "max")).state == "ok"


def test_future_divergence_guard_claude_only_level_on_a_codex_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Guard for a FUTURE divergence, not for today's data.

    Under the shipped constants every Claude level is also a Codex level, so no row can carry a
    Claude-only level on Codex yet. If Claude later gains a level Codex lacks, the same per-host
    rule must reject it on a Codex row. The Codex set is narrowed here to simulate that day:
    ``max`` becomes a Claude-only level.
    """
    monkeypatch.setattr(
        "switchboard.registry.ALLOWED_CODEX_EFFORT_TIERS",
        frozenset({"low", "medium", "high", "xhigh"}),
    )
    doc = _committed()
    doc["roles"]["reviewer"]["codex"]["effort"] = "max"

    result = load_registry(str(_write(tmp_path, doc)))

    assert result.state == "invalid"
    assert result.error is not None
    assert "'max' is a claude effort level that codex lacks" in result.error


def test_evidence_is_optional(tmp_path: Path) -> None:
    doc = _committed()
    del doc["roles"]["reviewer"]["evidence"]
    result = load_registry(str(_write(tmp_path, doc)))
    assert result.state == "ok"
    assert {r.role: r for r in result.roles}["reviewer"].evidence is None


def test_rows_report_in_vocabulary_order_whatever_the_file_order(tmp_path: Path) -> None:
    doc = _committed()
    doc["roles"] = dict(reversed(list(doc["roles"].items())))
    result = load_registry(str(_write(tmp_path, doc)))
    assert [row.role for row in result.roles] == list(ALLOWED_ROLES)


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        (b"{not json", "could not read registry"),
        (b"\xff\xfe not utf-8", "could not read registry"),
        (b"[1, 2]", "must be a JSON object"),
        (
            b'{"schema_version": 1, "schema_version": 1, "roles": {}}',
            "duplicate key 'schema_version'",
        ),
        # json raises a plain ValueError (not JSONDecodeError) for an int literal past
        # sys.get_int_max_str_digits() (default 4300).
        pytest.param(
            b'{"schema_version": ' + b"1" * 5000 + b"}",
            "could not read registry",
            id="int-past-digit-limit",
        ),
    ],
)
def test_unreadable_or_malformed_file_is_invalid(
    tmp_path: Path, payload: bytes, needle: str
) -> None:
    path = tmp_path / "models.json"
    path.write_bytes(payload)
    result = load_registry(str(path))
    assert result.state == "invalid"
    assert result.error is not None and needle in result.error


def test_duplicate_role_key_is_invalid_not_last_wins(tmp_path: Path) -> None:
    text = COMMITTED_REGISTRY.read_text(encoding="utf-8")
    # Append a second "reviewer" row: json would silently keep only the last one.
    dup = text.replace('"roles": {', '"roles": {\n    "reviewer": {},', 1)
    path = tmp_path / "models.json"
    path.write_text(dup, encoding="utf-8")
    result = load_registry(str(path))
    assert result.state == "invalid"
    assert result.error is not None and "duplicate key 'reviewer'" in result.error


def test_a_utf8_bom_is_not_invalid(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_bytes(b"\xef\xbb\xbf" + COMMITTED_REGISTRY.read_bytes())
    assert load_registry(str(path)).state == "ok"


def test_a_directory_is_invalid(tmp_path: Path) -> None:
    result = load_registry(str(tmp_path))
    assert result.state == "invalid"


# --- The production entry point: ``python -m switchboard`` ---------------------------------


def test_python_dash_m_inspect_roles_json_reads_the_committed_registry() -> None:
    # INTEGRATION through the real process entry (``__main__`` -> cli.main -> load_registry ->
    # repo default), run from switchboard/ exactly as the operator does.
    env = {k: v for k, v in os.environ.items() if k not in {REGISTRY_ENV_VAR}}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "switchboard", "inspect", "--roles", "--json"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["schema_version"] == 3
    assert report["registry_state"] == "ok"
    assert [row["role"] for row in report["roles"]] == list(ALLOWED_ROLES)
    for row in report["roles"]:
        for host in ALLOWED_HOSTS:
            assert sorted(row[host]) == sorted(HOST_PIN_FIELDS)


# --- Observatory contract: the registry section fails on any field change ------------------


def _registry_contract_drift(contract: Doc) -> list[str]:
    """One message per registry contract fact that disagrees with the runtime constants."""
    section = contract.get("registry", {})
    validation = section.get("validation", {})
    expected: dict[str, object] = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "environment_variable": REGISTRY_ENV_VAR,
        "default_path": (
            registry_module._default_registry_path().relative_to(PROJECT_ROOT.resolve()).as_posix()
        ),
        "fields": list(REGISTRY_TOP_LEVEL_FIELDS),
        "hosts": list(ALLOWED_HOSTS),
        "host_fields": list(HOST_PIN_FIELDS),
        "row_fields": list(ROLE_ROW_FIELDS),
        "optional_row_fields": sorted(ROLE_OPTIONAL_FIELDS),
        "roles": list(ALLOWED_ROLES),
        "claim_statuses": list(CLAIM_STATUSES),
        "states": list(REGISTRY_STATES),
        "source_precedence": list(REGISTRY_SOURCE_PRECEDENCE),
    }
    drift: list[str] = []
    for key, want in expected.items():
        got = section.get(key)
        if key == "source_precedence" and isinstance(got, list):
            got = [item.get("label") for item in got if isinstance(item, dict)]
        if got != want:
            drift.append(f"registry.{key}: contract={got!r} runtime={want!r}")
    expected_validation: dict[str, object] = {
        "claude_effort_levels": sorted(ALLOWED_EFFORT_TIERS),
        "codex_effort_levels": sorted(ALLOWED_CODEX_EFFORT_TIERS),
        "rejected_model_aliases": list(REJECTED_MODEL_ALIASES),
        "rejected_model_substrings": list(REJECTED_MODEL_SUBSTRINGS),
        "role_name_pattern": ROLE_NAME_PATTERN,
        "inherit": registry_module.INHERIT,
    }
    for key, want in expected_validation.items():
        if validation.get(key) != want:
            drift.append(f"registry.validation.{key}: contract={validation.get(key)!r}")
    return drift


def _contract() -> Doc:
    data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_observatory_contract_registry_section_matches_runtime() -> None:
    assert _registry_contract_drift(_contract()) == []


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("registry", "row_fields"), ["description", "read_only", "claude", "codex"]),
        _set(("registry", "hosts"), ["claude", "codex", "copilot"]),
        _set(("registry", "host_fields"), ["model", "effort", "tier"]),
        _set(("registry", "schema_version"), 2),
        _set(("registry", "states"), ["absent", "invalid", "valid"]),
        _set(("registry", "roles"), [*ALLOWED_ROLES, "grader"]),
        _set(("registry", "environment_variable"), "SWITCHBOARD_MODELS"),
        _set(("registry", "validation", "codex_effort_levels"), ["high", "low", "medium"]),
        _delete(("registry", "claim_statuses")),
    ],
)
def test_registry_contract_drift_guard_fails_on_any_field_change(mutate: Mutation) -> None:
    # Red-on-garbage: the comparison must FAIL on a drifted copy, or it proves nothing.
    contract = _contract()
    mutate(contract)
    assert _registry_contract_drift(contract) != []
