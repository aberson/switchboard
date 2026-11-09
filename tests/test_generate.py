"""``python -m switchboard apply``: role-file generation under the ownership ledger (Step R2).

Every test drives the production entry point ``switchboard.cli.main(["apply", ...])`` (and one
drives the real ``python -m switchboard`` process) over a temporary home. The autouse fixture
also points ``Path.home()``, ``HOME`` and ``USERPROFILE`` at that temporary home, unsets the
registry and Claude override variables, and runs from a temporary project with its own git
root, so nothing here can read or write the real ``~/.claude``, ``~/.codex`` or
``~/.switchboard``.

Generated files are parsed back independently of the emitters: the TOML with ``tomllib`` and
the YAML frontmatter with the small subset reader below.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import switchboard.generate as generate_module
import switchboard.registry as registry_module
from switchboard.cli import main
from switchboard.generate import (
    HOST_AGENT_DIRECTORIES,
    HOST_FILE_SUFFIXES,
    PROVENANCE_MARKER,
    SUBAGENT_OVERRIDE_ENV_VARS,
    FilePlan,
    LedgerEntry,
    render_claude,
)
from switchboard.registry import (
    ALLOWED_HOSTS,
    ALLOWED_ROLES,
    REGISTRY_ENV_VAR,
    RoleRow,
    load_registry,
)

PROJECT_ROOT = Path(__file__).parents[1]
COMMITTED_REGISTRY = PROJECT_ROOT / "registry" / "models.json"
N_FILES = len(ALLOWED_ROLES) * len(ALLOWED_HOSTS)
# The program prefix of every apply advisory line on stderr (the user-visible contract).
ADVISORY = "switchboard apply: "

Doc = dict[str, Any]
Tree = dict[str, tuple[bytes | None, int]]


@dataclass(frozen=True)
class Env:
    root: Path
    home: Path
    project: Path


# --- tests drive main() over a temporary home (this fixture) ---------------------------------


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Env]:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    for name in (*SUBAGENT_OVERRIDE_ENV_VARS, REGISTRY_ENV_VAR, "SWITCHBOARD_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(project)
    yield Env(root=tmp_path, home=home, project=project)


# --- Helpers ---------------------------------------------------------------------------------


def _apply(
    env: Env,
    capsys: pytest.CaptureFixture[str],
    *args: str,
    registry: Path | None = COMMITTED_REGISTRY,
    home: Path | None = None,
) -> tuple[int, str, str]:
    argv = ["apply", "--home", str(home if home is not None else env.home)]
    if registry is not None:
        argv += ["--registry", str(registry)]
    rc = main([*argv, *args])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _tree(root: Path) -> Tree:
    """Every path under ``root`` with its bytes and mtime (directories: ``None``, 0)."""
    out: Tree = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not path.is_symlink():
            out[rel] = (path.read_bytes(), path.stat().st_mtime_ns)
        else:
            out[rel] = (None, 0)
    return out


def _committed() -> Doc:
    data = json.loads(COMMITTED_REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def _write_registry(env: Env, doc: object, name: str = "models.json") -> Path:
    path = env.root / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _rows(registry: Path = COMMITTED_REGISTRY) -> tuple[RoleRow, ...]:
    result = load_registry(str(registry))
    assert result.state == "ok", result.error
    return result.roles


def _claude_path(home: Path, role: str) -> Path:
    return home / ".claude" / "agents" / f"role-{role}.md"


def _codex_path(home: Path, role: str) -> Path:
    return home / ".codex" / "agents" / f"role-{role}.toml"


def _ledger_path(home: Path) -> Path:
    return home / ".switchboard" / "generated.json"


def _ledger(home: Path) -> Doc:
    data = json.loads(_ledger_path(home).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan_lines(out: str, action: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(f"  {action} ")]


# The only escapes the emitters may use: \\ \" \uXXXX. Within that subset a YAML 1.2
# double-quoted scalar is also a JSON string, so json.loads decodes it with YAML's meaning.
_DOUBLE_QUOTED_RE = re.compile(r'"(?:[^"\\\x00-\x1f\x7f]|\\["\\]|\\u[0-9A-Fa-f]{4})*"')


def _frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse generated frontmatter: ``key: value`` lines, comments, quoted or plain scalars."""
    assert text.startswith("---\n"), text[:40]
    head, sep, body = text[len("---\n") :].partition("\n---\n")
    assert sep, "frontmatter is not closed"
    fields: dict[str, object] = {}
    for line in head.split("\n"):
        if line.startswith("#"):
            continue
        key, colon, raw = line.partition(": ")
        assert colon and re.fullmatch(r"[A-Za-z]+", key) and key not in fields, line
        if raw.startswith('"'):
            assert _DOUBLE_QUOTED_RE.fullmatch(raw), raw
            fields[key] = json.loads(raw)
        elif raw in {"true", "false"}:
            fields[key] = raw == "true"
        else:
            # A plain scalar must not start with a YAML indicator or hold ": " / " #".
            assert raw and raw[0] not in "-?:,[]{}#&*!|>'\"%@`", raw
            assert ": " not in raw and " #" not in raw, raw
            fields[key] = raw
    return fields, body


def _expected_claude(row: RoleRow) -> dict[str, object]:
    want: dict[str, object] = {"name": f"role-{row.role}", "description": row.description}
    if row.claude.model != "inherit":
        want["model"] = row.claude.model
    if row.claude.effort != "inherit":
        want["effort"] = row.claude.effort
    if row.read_only:
        want["disallowedTools"] = "Agent, Edit, Write, NotebookEdit"
        want["omitClaudeMd"] = True
    return want


def _expected_codex_keys(row: RoleRow) -> set[str]:
    keys = {"name", "description", "developer_instructions"}
    if row.codex.model != "inherit":
        keys.add("model")
    if row.codex.effort != "inherit":
        keys.add("model_reasoning_effort")
    return keys


def _assert_files_match_registry(home: Path, rows: tuple[RoleRow, ...]) -> None:
    for row in rows:
        claude_bytes = _claude_path(home, row.role).read_bytes()
        assert b"\r" not in claude_bytes
        fields, body = _frontmatter(claude_bytes.decode("utf-8"))
        assert fields == _expected_claude(row)
        assert row.role in body and row.description.rstrip(".") in body

        codex_bytes = _codex_path(home, row.role).read_bytes()
        assert b"\r" not in codex_bytes
        toml = tomllib.loads(codex_bytes.decode("utf-8"))
        assert set(toml) == _expected_codex_keys(row)
        assert toml["name"] == f"role-{row.role}"
        assert toml["description"] == row.description
        if row.codex.model != "inherit":
            assert toml["model"] == row.codex.model
        if row.codex.effort != "inherit":
            assert toml["model_reasoning_effort"] == row.codex.effort
        instructions = toml["developer_instructions"]
        assert row.role in instructions and row.description.rstrip(".") in instructions
        assert ("read-only" in instructions) is row.read_only
        if row.read_only:
            assert "subagents" in instructions  # read-only also forbids launching subagents


# --- One source of truth -------------------------------------------------------------------


def test_generated_hosts_are_exactly_the_registry_hosts() -> None:
    assert tuple(HOST_AGENT_DIRECTORIES) == ALLOWED_HOSTS
    assert tuple(HOST_FILE_SUFFIXES) == ALLOWED_HOSTS


# --- a bare run writes nothing ---------------------------------------------------------------


def test_bare_run_prints_a_create_plan_and_writes_nothing(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _tree(env.root)

    rc, out, err = _apply(env, capsys)

    assert rc == 0, err
    assert _tree(env.root) == before
    assert len(_plan_lines(out, "create")) == N_FILES
    assert "dry run, nothing written" in out
    assert not (env.home / ".claude").exists()
    assert not (env.home / ".switchboard").exists()


def test_bare_run_after_a_registry_change_plans_the_update_but_writes_nothing(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _apply(env, capsys, "--write")[0] == 0
    doc = _committed()
    doc["roles"]["reviewer"]["claude"]["effort"] = "high"
    changed = _write_registry(env, doc)
    before = _tree(env.root)

    rc, out, _ = _apply(env, capsys, registry=changed)

    assert rc == 0
    assert _tree(env.root) == before
    updates = _plan_lines(out, "update")
    assert len(updates) == 1 and "role-reviewer.md" in updates[0]
    assert len(_plan_lines(out, "unchanged")) == N_FILES - 1


# --- --write creates both hosts' files that parse back ---------------------------------------


def test_write_creates_both_hosts_files_that_parse_back_to_the_registry(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err = _apply(env, capsys, "--write")

    assert rc == 0, err
    assert len(_plan_lines(out, "create")) == N_FILES
    assert f"{N_FILES} change(s) written" in out
    rows = _rows()
    _assert_files_match_registry(env.home, rows)

    ledger = _ledger(env.home)
    assert ledger["schema_version"] == 1
    assert len(ledger["files"]) == N_FILES
    for row in rows:
        for host, path in (
            ("claude", _claude_path(env.home, row.role)),
            ("codex", _codex_path(env.home, row.role)),
        ):
            key = path.relative_to(env.home).as_posix()
            assert ledger["files"][key] == {"sha256": _sha(path), "role": row.role, "host": host}
            assert PROVENANCE_MARKER in path.read_text(encoding="utf-8")
    # Atomic writes leave no staged temp file behind.
    assert not [p for p in env.home.rglob("*.tmp")]


def test_inherit_writes_no_key_and_pins_write_the_exact_values(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    # A test-local registry fixes both shapes, so a reviewed models.json swap cannot hide either:
    # builder inherits every key on both hosts; reviewer pins every key and is read-only.
    doc = _committed()
    inherit = {"model": "inherit", "effort": "inherit"}
    doc["roles"]["builder"].update(read_only=False, claude=inherit, codex=inherit)
    doc["roles"]["reviewer"].update(
        read_only=True,
        claude={"model": "claude-test-model-1", "effort": "high"},
        codex={"model": "gpt-test-model-1", "effort": "low"},
    )
    registry = _write_registry(env, doc)

    rc, _, err = _apply(env, capsys, "--write", registry=registry)

    assert rc == 0, err
    _assert_files_match_registry(env.home, _rows(registry))
    builder, _ = _frontmatter(_claude_path(env.home, "builder").read_text(encoding="utf-8"))
    assert set(builder) == {"name", "description"}
    codex_builder = tomllib.loads(_codex_path(env.home, "builder").read_text(encoding="utf-8"))
    assert set(codex_builder) == {"name", "description", "developer_instructions"}
    reviewer, _ = _frontmatter(_claude_path(env.home, "reviewer").read_text(encoding="utf-8"))
    assert (reviewer["model"], reviewer["effort"]) == ("claude-test-model-1", "high")
    codex_reviewer = tomllib.loads(_codex_path(env.home, "reviewer").read_text(encoding="utf-8"))
    assert (codex_reviewer["model"], codex_reviewer["model_reasoning_effort"]) == (
        "gpt-test-model-1",
        "low",
    )


@pytest.mark.parametrize(
    "description",
    [
        "Colon: value # not a comment",
        "Has \"double\" and 'single' quotes",
        "Back\\slash and trailing backslash \\",
        "- leading dash, [flow] {map} & *alias !tag | > % @ `tick`",
        "#starts with a hash",
        "Unicode é ü 漢字 and a dash —",
        "Ends without a period",
    ],
)
def test_descriptions_with_metacharacters_round_trip_on_both_hosts(
    env: Env, capsys: pytest.CaptureFixture[str], description: str
) -> None:
    doc = _committed()
    doc["roles"]["scanner"]["description"] = description
    registry = _write_registry(env, doc)

    rc, _, err = _apply(env, capsys, "--write", registry=registry)

    assert rc == 0, err
    fields, _ = _frontmatter(_claude_path(env.home, "scanner").read_text(encoding="utf-8"))
    assert fields["description"] == description
    toml = tomllib.loads(_codex_path(env.home, "scanner").read_text(encoding="utf-8"))
    assert toml["description"] == description
    assert description in toml["developer_instructions"]
    _assert_files_match_registry(env.home, _rows(registry))


def test_rendering_is_byte_identical_across_homes(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    other = env.root / "other-home"
    other.mkdir()

    _apply(env, capsys, "--write")
    _apply(env, capsys, "--write", home=other)

    first = {k: v[0] for k, v in _tree(env.home).items()}
    second = {k: v[0] for k, v in _tree(other).items()}
    assert first == second


# --- a hand-edited or foreign file is never modified or deleted ------------------------------


def test_foreign_file_at_a_target_path_is_refused_even_with_the_provenance_marker(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _claude_path(env.home, "reviewer")
    target.parent.mkdir(parents=True)
    # Carries the marker, so acting on the marker alone would wrongly claim it.
    foreign = f"---\n# {PROVENANCE_MARKER}\nname: role-reviewer\n---\nmine\n".encode()
    target.write_bytes(foreign)
    mtime = target.stat().st_mtime_ns

    # First run: no ledger at all. Second run: a ledger exists but has no entry for it.
    rc, out, _ = _apply(env, capsys, "--write")
    rc2, out2, _ = _apply(env, capsys, "--prune", "--write")

    assert rc == 0 and rc2 == 0
    assert target.read_bytes() == foreign
    assert target.stat().st_mtime_ns == mtime
    refused = _plan_lines(out, "refuse")
    assert len(refused) == 1 and "role-reviewer.md" in refused[0]
    assert "there is no ledger" in refused[0]
    refused = _plan_lines(out2, "refuse")
    assert len(refused) == 1 and "no ledger entry" in refused[0]
    assert ".claude/agents/role-reviewer.md" not in _ledger(env.home)["files"]
    assert len(_ledger(env.home)["files"]) == N_FILES - 1


def test_byte_identical_copy_without_a_ledger_entry_is_still_refused(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewer = next(row for row in _rows() if row.role == "reviewer")
    target = _claude_path(env.home, "reviewer")
    target.parent.mkdir(parents=True)
    target.write_bytes(render_claude(reviewer))

    rc, out, _ = _apply(env, capsys, "--write")

    assert rc == 0
    assert any("role-reviewer.md" in line for line in _plan_lines(out, "refuse"))
    assert ".claude/agents/role-reviewer.md" not in _ledger(env.home)["files"]


def test_hand_edited_generated_file_is_refused_and_kept(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    _apply(env, capsys, "--write")
    target = _claude_path(env.home, "reviewer")
    recorded = _ledger(env.home)["files"][".claude/agents/role-reviewer.md"]["sha256"]
    edited = target.read_bytes() + b"\nmy local note\n"
    target.write_bytes(edited)
    doc = _committed()
    doc["roles"]["reviewer"]["claude"]["effort"] = "high"
    registry = _write_registry(env, doc)

    rc, out, _ = _apply(env, capsys, "--write", "--prune", registry=registry)

    assert rc == 0
    assert target.read_bytes() == edited
    refused = _plan_lines(out, "refuse")
    assert len(refused) == 1 and "hand edit" in refused[0]
    assert _ledger(env.home)["files"][".claude/agents/role-reviewer.md"]["sha256"] == recorded


def test_missing_ledger_means_every_existing_file_is_refused(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    _apply(env, capsys, "--write")
    _ledger_path(env.home).unlink()
    doc = _committed()
    doc["roles"]["reviewer"]["claude"]["effort"] = "high"
    registry = _write_registry(env, doc)
    before = _tree(env.home)

    rc, out, _ = _apply(env, capsys, "--write", "--prune", registry=registry)

    assert rc == 0
    assert _tree(env.home) == before
    assert len(_plan_lines(out, "refuse")) == N_FILES
    assert not _ledger_path(env.home).exists()


def test_corrupt_ledger_refuses_existing_files_and_is_kept_aside(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    _apply(env, capsys, "--write")
    garbage = b'{"schema_version": 1, "files": {'
    _ledger_path(env.home).write_bytes(garbage)
    _codex_path(env.home, "author").unlink()
    before = _tree(env.home)

    rc, out, err = _apply(env, capsys, "--write")

    assert rc == 0
    assert "unreadable" in err
    after = _tree(env.home)
    for key, value in before.items():
        if key != ".switchboard/generated.json":
            assert after[key] == value, key
    assert len(_plan_lines(out, "refuse")) == N_FILES - 1
    assert _codex_path(env.home, "author").exists()
    kept = [p for p in (env.home / ".switchboard").iterdir() if ".corrupt-" in p.name]
    assert len(kept) == 1 and kept[0].read_bytes() == garbage
    assert list(_ledger(env.home)["files"]) == [".codex/agents/role-author.toml"]


@pytest.mark.parametrize(
    "key",
    [
        "../victim.md",  # escapes the home
        ".claude/agents/role-victim.md",  # the right shape, but not the entry's role
    ],
)
def test_a_ledger_path_that_is_not_the_generated_path_grants_nothing(
    env: Env, capsys: pytest.CaptureFixture[str], key: str
) -> None:
    victim = env.home.joinpath(*key.split("/"))
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_bytes(b"precious\n")
    ledger = {
        "schema_version": 1,
        "files": {key: {"sha256": _sha(victim), "role": "retired", "host": "claude"}},
    }
    _ledger_path(env.home).parent.mkdir(parents=True)
    _ledger_path(env.home).write_text(json.dumps(ledger), encoding="utf-8")

    rc, _, err = _apply(env, capsys, "--prune", "--write")

    assert rc == 0
    assert victim.read_bytes() == b"precious\n"
    assert "unreadable" in err


def test_directory_at_a_target_path_is_refused(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _codex_path(env.home, "reviewer")
    target.mkdir(parents=True)
    (target / "keep.txt").write_bytes(b"x")

    rc, out, _ = _apply(env, capsys, "--write")

    assert rc == 0
    assert (target / "keep.txt").read_bytes() == b"x"
    assert any("role-reviewer.toml" in line for line in _plan_lines(out, "refuse"))


def test_symlink_at_a_target_path_is_refused(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    real = env.root / "elsewhere.md"
    real.write_bytes(b"not yours\n")
    target = _claude_path(env.home, "reviewer")
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(real)
    except OSError as exc:  # Windows without Developer Mode or admin
        pytest.skip(f"symlinks unavailable: {exc}")

    rc, out, _ = _apply(env, capsys, "--write")

    assert rc == 0
    assert target.is_symlink() and real.read_bytes() == b"not yours\n"
    assert any("symbolic link" in line for line in _plan_lines(out, "refuse"))


def test_create_never_replaces_a_file_that_appears_after_the_plan(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _claude_path(env.home, "reviewer")
    real_stage: Callable[[Path, str, bytes], Path] = generate_module._stage

    def racing_stage(directory: Path, name: str, data: bytes) -> Path:
        staged = real_stage(directory, name, data)
        if name == target.name:
            target.write_bytes(b"written by someone else\n")
        return staged

    monkeypatch.setattr(generate_module, "_stage", racing_stage)

    rc, out, _ = _apply(env, capsys, "--write")

    assert rc == 0
    assert target.read_bytes() == b"written by someone else\n"
    assert any("appeared after the plan" in line for line in _plan_lines(out, "refuse"))
    assert ".claude/agents/role-reviewer.md" not in _ledger(env.home)["files"]
    assert not list(env.home.rglob("*.tmp"))


def test_update_refuses_a_hand_edit_made_after_staging_before_the_rename(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply(env, capsys, "--write")
    target = _claude_path(env.home, "reviewer")
    recorded = _ledger(env.home)["files"][".claude/agents/role-reviewer.md"]["sha256"]
    edited = target.read_bytes() + b"\nmy local note\n"
    doc = _committed()
    doc["roles"]["reviewer"]["claude"]["effort"] = "high"
    registry = _write_registry(env, doc)
    real_stage: Callable[[Path, str, bytes], Path] = generate_module._stage

    def editing_stage(directory: Path, name: str, data: bytes) -> Path:
        # The plan saw the owned bytes; the hand edit lands while the new content is staged.
        staged = real_stage(directory, name, data)
        if name == target.name:
            target.write_bytes(edited)
        return staged

    monkeypatch.setattr(generate_module, "_stage", editing_stage)

    rc, out, _ = _apply(env, capsys, "--write", registry=registry)

    assert rc == 0
    assert target.read_bytes() == edited
    refused = _plan_lines(out, "refuse")
    assert len(refused) == 1 and "changed after the plan" in refused[0]
    assert _ledger(env.home)["files"][".claude/agents/role-reviewer.md"]["sha256"] == recorded
    assert not list(env.home.rglob("*.tmp"))


def test_failed_update_keeps_the_old_file_and_its_ledger_entry(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply(env, capsys, "--write")
    target = _claude_path(env.home, "reviewer")
    old = target.read_bytes()
    doc = _committed()
    doc["roles"]["reviewer"]["claude"]["effort"] = "high"
    registry = _write_registry(env, doc)
    real_replace = os.replace

    def failing_replace(src: Any, dst: Any) -> None:
        if Path(dst) == target:
            raise PermissionError("simulated lock")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing_replace)
    rc, out, err = _apply(env, capsys, "--write", registry=registry)
    monkeypatch.setattr(os, "replace", real_replace)

    assert rc == 1
    assert "simulated lock" in err
    assert target.read_bytes() == old
    assert not list(env.home.rglob("*.tmp"))
    assert _ledger(env.home)["files"][".claude/agents/role-reviewer.md"]["sha256"] == _sha(target)
    assert len(_plan_lines(out, "error")) == 1
    # The file is still provably owned, so the next run updates it.
    rc, out, _ = _apply(env, capsys, "--write", registry=registry)
    assert rc == 0 and len(_plan_lines(out, "update")) == 1


# --- an invalid registry leaves every generated file byte-identical --------------------------


@pytest.mark.parametrize("flags", [(), ("--write",), ("--prune", "--write")])
def test_invalid_registry_writes_nothing_and_exits_2(
    env: Env, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...]
) -> None:
    _apply(env, capsys, "--write")
    doc = _committed()
    # One invalid row stands for every validation rule: apply only branches on the loaded state,
    # and the rules themselves are registry.py's (tests/test_registry.py).
    doc["roles"]["reviewer"]["claude"]["model"] = "sonnet"
    registry = _write_registry(env, doc)
    before = _tree(env.root)

    rc, out, err = _apply(env, capsys, *flags, registry=registry)

    assert rc == 2
    assert _tree(env.root) == before
    assert out == ""
    assert len(err.splitlines()) == 1 and err.startswith(f"{ADVISORY}registry is invalid")


@pytest.mark.parametrize("content", [None, "not json", "[]"])
def test_missing_or_unparseable_registry_writes_nothing_and_exits_2(
    env: Env, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    _apply(env, capsys, "--write")
    registry = env.root / "candidate.json"
    if content is not None:
        registry.write_text(content, encoding="utf-8")
    before = _tree(env.root)

    rc, out, err = _apply(env, capsys, "--write", "--prune", registry=registry)

    assert rc == 2
    assert _tree(env.root) == before
    assert out == "" and len(err.splitlines()) == 1 and err.startswith(f"{ADVISORY}registry")


def test_unrenderable_registry_writes_nothing_and_exits_2(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    _apply(env, capsys, "--write")
    registry = env.root / "surrogate.json"
    # A lone surrogate passes registry validation but cannot be written as UTF-8 TOML or YAML.
    text = json.dumps(_committed()).replace("The review-deep Style lens", "Bad \\ud800 lens")
    registry.write_text(text, encoding="utf-8")
    before = _tree(env.root)

    rc, out, err = _apply(env, capsys, "--write", registry=registry)

    assert rc == 2
    assert _tree(env.root) == before
    assert out == "" and len(err.splitlines()) == 1 and "cannot be rendered" in err


# --- a second --write is a no-op -------------------------------------------------------------


def test_second_write_is_a_no_op(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    _apply(env, capsys, "--write")
    before = _tree(env.home)

    rc, out, _ = _apply(env, capsys, "--write")

    assert rc == 0
    assert _tree(env.home) == before  # bytes AND mtimes: no file, ledger included, was touched
    assert len(_plan_lines(out, "unchanged")) == N_FILES
    assert "0 change(s) written" in out


def test_write_updates_only_the_changed_row(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    _apply(env, capsys, "--write")
    before = _tree(env.home)
    doc = _committed()
    doc["roles"]["reviewer"]["claude"]["effort"] = "high"
    registry = _write_registry(env, doc)

    rc, out, _ = _apply(env, capsys, "--write", registry=registry)

    assert rc == 0
    after = _tree(env.home)
    changed = sorted(k for k in after if after[k] != before.get(k))
    assert changed == [".claude/agents/role-reviewer.md", ".switchboard/generated.json"]
    fields, _ = _frontmatter(_claude_path(env.home, "reviewer").read_text(encoding="utf-8"))
    assert fields["effort"] == "high"
    entry = _ledger(env.home)["files"][".claude/agents/role-reviewer.md"]
    assert entry["sha256"] == _sha(_claude_path(env.home, "reviewer"))
    assert "1 change(s) written" in out


# --- --prune removes only ledger-owned, hash-matching files ----------------------------------


def test_prune_removes_only_ledger_owned_hash_matching_files(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Generate two extra roles while the vocabulary includes them, then retire both.
    monkeypatch.setattr(
        registry_module, "ALLOWED_ROLES", (*ALLOWED_ROLES, "retired-a", "retired-b")
    )
    doc = _committed()
    for role in ("retired-a", "retired-b"):
        doc["roles"][role] = {**copy.deepcopy(doc["roles"]["reviewer"]), "claim_id": f"c-{role}"}
    assert _apply(env, capsys, "--write", registry=_write_registry(env, doc, "wide.json"))[0] == 0
    monkeypatch.setattr(registry_module, "ALLOWED_ROLES", ALLOWED_ROLES)
    assert len(_ledger(env.home)["files"]) == N_FILES + 4

    edited = _claude_path(env.home, "retired-b")
    edited_bytes = edited.read_bytes() + b"\nhand edit\n"
    edited.write_bytes(edited_bytes)
    foreign = [env.home / ".claude/agents/role-foreign.md", env.home / ".codex/agents/x.toml"]
    for path in foreign:
        path.write_bytes(b"foreign\n")
    current = {
        k: v for k, v in _tree(env.home).items() if "retired" not in k and "generated" not in k
    }

    # Without --prune the orphans are only reported.
    rc, out, _ = _apply(env, capsys, "--write")
    assert rc == 0 and len(_plan_lines(out, "orphan")) == 4
    assert _claude_path(env.home, "retired-a").exists()

    # --prune without --write is a dry run.
    before = _tree(env.root)
    rc, out, _ = _apply(env, capsys, "--prune")
    assert rc == 0 and _tree(env.root) == before
    assert len(_plan_lines(out, "delete")) == 3 and len(_plan_lines(out, "refuse")) == 1

    rc, out, _ = _apply(env, capsys, "--prune", "--write")

    assert rc == 0
    assert not _claude_path(env.home, "retired-a").exists()
    assert not _codex_path(env.home, "retired-a").exists()
    assert not _codex_path(env.home, "retired-b").exists()
    assert edited.read_bytes() == edited_bytes  # hand-edited: refused, kept
    for path in foreign:
        assert path.read_bytes() == b"foreign\n"
    after = _tree(env.home)
    for key, value in current.items():
        assert after[key] == value, key  # current roles' files and foreign files untouched
    files = _ledger(env.home)["files"]
    assert len(files) == N_FILES + 1 and ".claude/agents/role-retired-b.md" in files

    # Once the refused file is gone by hand, --prune drops its stale ledger entry.
    edited.unlink()
    rc, out, _ = _apply(env, capsys, "--prune", "--write")
    assert rc == 0 and len(_plan_lines(out, "forget")) == 1
    assert len(_ledger(env.home)["files"]) == N_FILES


def test_prune_refuses_a_hand_edit_made_after_the_plan_before_the_delete(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Generate one extra role while the vocabulary includes it, then retire it.
    monkeypatch.setattr(registry_module, "ALLOWED_ROLES", (*ALLOWED_ROLES, "retired"))
    doc = _committed()
    doc["roles"]["retired"] = {**copy.deepcopy(doc["roles"]["reviewer"]), "claim_id": "c-retired"}
    assert _apply(env, capsys, "--write", registry=_write_registry(env, doc, "wide.json"))[0] == 0
    monkeypatch.setattr(registry_module, "ALLOWED_ROLES", ALLOWED_ROLES)
    target = _claude_path(env.home, "retired")
    sibling = _codex_path(env.home, "retired")
    target_key = target.relative_to(env.home).as_posix()
    sibling_key = sibling.relative_to(env.home).as_posix()
    recorded = _ledger(env.home)["files"][target_key]
    assert recorded["sha256"] == _sha(target) and sibling_key in _ledger(env.home)["files"]
    edited = target.read_bytes() + b"\nhand edit made after the plan\n"
    real_apply_one: Callable[[FilePlan, dict[str, LedgerEntry]], FilePlan] = (
        generate_module._apply_one
    )
    edited_at: list[str] = []

    def editing_apply_one(item: FilePlan, entries: dict[str, LedgerEntry]) -> FilePlan:
        # The plan saw the owned, hash-matching bytes and chose delete; the hand edit lands
        # between that plan and the delete being carried out.
        if item.action == "delete" and item.path == target:
            target.write_bytes(edited)
            edited_at.append(item.action)
        return real_apply_one(item, entries)

    monkeypatch.setattr(generate_module, "_apply_one", editing_apply_one)

    rc, out, err = _apply(env, capsys, "--prune", "--write")

    assert rc == 0, err  # a refusal is a reported plan state, not an error
    assert edited_at == ["delete"]  # the race was injected at the delete, not the plan
    assert target.read_bytes() == edited  # the hand-edited file survives
    refused = _plan_lines(out, "refuse")
    assert len(refused) == 1 and "role-retired.md" in refused[0]
    assert "changed after the plan; not pruned" in refused[0]
    deleted = _plan_lines(out, "delete")
    assert len(deleted) == 1 and "role-retired.toml" in deleted[0]
    assert not sibling.exists()  # the untouched sibling is still pruned
    files = _ledger(env.home)["files"]
    assert files[target_key] == recorded  # its ledger entry is kept as recorded
    assert sibling_key not in files
    assert len(files) == N_FILES + 1
    assert "1 change(s) written" in out


# --- Advisory lines (never errors) ---------------------------------------------------------


def test_claude_override_environment_variables_are_advisories(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in SUBAGENT_OVERRIDE_ENV_VARS:
        monkeypatch.setenv(name, "claude-opus-5-5")

    rc, _, err = _apply(env, capsys, "--write")

    assert rc == 0
    lines = err.splitlines()
    for name in SUBAGENT_OVERRIDE_ENV_VARS:
        assert sum(line.startswith(f"{ADVISORY}{name}=") for line in lines) == 1
    # Every stderr line, the new-directory notes included, carries the program prefix.
    assert lines and all(line.startswith(ADVISORY) for line in lines)
    assert len(_ledger(env.home)["files"]) == N_FILES


def test_unset_or_empty_override_variables_give_no_advisory(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "")

    _, _, err = _apply(env, capsys)

    assert "CLAUDE_CODE" not in err


def test_same_named_project_agents_are_advisories(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    agents = env.project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "role-reviewer.md").write_text("---\nname: something\n---\n", encoding="utf-8")
    (agents / "custom.md").write_text('---\nname: "role-scanner"\n---\nx\n', encoding="utf-8")
    (agents / "unrelated.md").write_text("---\nname: helper\n---\n", encoding="utf-8")
    # Above the git root: not part of this project, never reported.
    outside = env.root / ".claude" / "agents"
    outside.mkdir(parents=True)
    (outside / "role-author.md").write_text("---\nname: role-author\n---\n", encoding="utf-8")
    nested = env.project / "pkg" / "sub"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    rc, _, err = _apply(env, capsys)

    assert rc == 0
    lines = [line for line in err.splitlines() if line.startswith(f"{ADVISORY}project agent ")]
    assert len(lines) == 2
    assert any("'role-reviewer'" in line for line in lines)
    assert any("'role-scanner'" in line for line in lines)
    assert not any("role-author" in line for line in lines)


def test_the_user_level_agents_directory_is_not_a_project_agent(
    env: Env, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply(env, capsys, "--write")
    monkeypatch.chdir(env.home)

    _, _, err = _apply(env, capsys)

    assert f"{ADVISORY}project agent " not in err


def test_catalog_roles_without_a_row_are_advisories(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = env.root / "spawn-sites.json"
    sites = {
        "build-step.reviewer": "reviewer",
        "score-skill.grader": "inherit",
        "ghost.one": "ghost-role",
        "ghost.two": "ghost-role",
    }
    catalog.write_text(json.dumps({"schema_version": 1, "sites": sites}), encoding="utf-8")

    rc, out, err = _apply(env, capsys, "--catalog", str(catalog))

    assert rc == 0
    lines = [line for line in err.splitlines() if line.startswith(f"{ADVISORY}catalog ")]
    assert len(lines) == 1
    assert "'ghost-role'" in lines[0] and "'ghost.one'" in lines[0] and "'ghost.two'" in lines[0]
    assert len(_plan_lines(out, "create")) == N_FILES


@pytest.mark.parametrize(
    "content",
    [
        None,  # missing file
        "{not json",
        "[]",
        '{"schema_version": 2, "sites": {}}',
        '{"schema_version": 1, "sites": []}',
        '{"schema_version": 1, "sites": {"a": 3}}',
        '{"sites": {"a": "reviewer"}}',
    ],
)
def test_malformed_catalog_is_one_advisory_line_and_no_crash(
    env: Env, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    catalog = env.root / "spawn-sites.json"
    if content is not None:
        catalog.write_text(content, encoding="utf-8")

    rc, _, err = _apply(env, capsys, "--write", "--catalog", str(catalog))

    assert rc == 0
    assert len([line for line in err.splitlines() if line.startswith(f"{ADVISORY}catalog ")]) == 1
    assert "is unusable" in err
    assert len(_ledger(env.home)["files"]) == N_FILES


# --- --home ----------------------------------------------------------------------------------


def test_home_defaults_to_the_user_home_directory(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    assert Path.home() == env.home  # the fixture's guard: never the real home

    rc = main(["apply", "--registry", str(COMMITTED_REGISTRY), "--write"])
    capsys.readouterr()

    assert rc == 0
    assert len(_ledger(env.home)["files"]) == N_FILES
    assert _claude_path(env.home, "reviewer").is_file()


def test_home_that_is_not_a_directory_exits_2(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    before = _tree(env.root)

    rc, out, err = _apply(env, capsys, "--write", home=env.root / "nope")

    assert rc == 2 and out == "" and len(err.splitlines()) == 1
    assert _tree(env.root) == before


# --- The real process entry point ----------------------------------------------------------


def test_python_dash_m_apply_dry_run_then_write(env: Env) -> None:
    # INTEGRATION through ``python -m switchboard`` (``__main__`` -> cli.main -> generate).
    child_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {REGISTRY_ENV_VAR, *SUBAGENT_OVERRIDE_ENV_VARS}
    }
    child_env.update(HOME=str(env.home), USERPROFILE=str(env.home), PYTHONIOENCODING="utf-8")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        # Ruff's S603 accepts an argv of only string literals and ``sys.executable`` (as in
        # test_registry.py's inspect call) and flags anything else. This argv also carries
        # ``str(env.home)`` and ``*args``, so the noqa is required. Those values are a test-owned
        # temp path and this test's own fixed flags, so the input is trusted.
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "switchboard", "apply", "--home", str(env.home), *args],
            cwd=PROJECT_ROOT,
            env=child_env,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    before = _tree(env.root)
    dry = run()
    assert dry.returncode == 0, dry.stderr
    assert _tree(env.root) == before
    assert dry.stdout.count("  create ") == N_FILES

    wrote = run("--write")
    assert wrote.returncode == 0, wrote.stderr
    _assert_files_match_registry(env.home, _rows())
    assert len(_ledger(env.home)["files"]) == N_FILES
