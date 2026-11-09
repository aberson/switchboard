"""``python -m switchboard observe``: requested-versus-observed receipts (Step R3).

Every test drives the production entry point ``switchboard.cli.main(["observe", ...])`` and
reads the result back through ``main(["inspect", ...])``; one test drives the real
``python -m switchboard`` process. The autouse fixture points ``Path.home()``, ``HOME`` and
``USERPROFILE`` at a temporary home and unsets the registry and config variables, so nothing
here can read or write the real ``~/.claude``, ``~/.codex`` or ``~/.switchboard``.

The transcripts under ``tests/fixtures/observe/`` are SYNTHETIC. Their field names are the ones
``switchboard.observe`` records from one real transcript per host; every content string is a
``SYNTHETIC ...`` placeholder (``test_fixtures_are_synthetic`` checks this).
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import switchboard.observe as observe_module
from switchboard.cli import main
from switchboard.config import CONFIG_DIRECTORY_NAME, SwitchboardConfig
from switchboard.observe import (
    CLAUDE_AGENT_TYPE_FIELD,
    CLAUDE_EFFORT_FIELD,
    CLAUDE_MODEL_PATH,
    CLAUDE_SYNTHETIC_MODEL,
    CODEX_AGENT_TYPE_FIELD,
    CODEX_EFFORT_PATH,
    CODEX_HISTORY_START_PATH,
    CODEX_MODEL_PATH,
    CODEX_SPAWN_PATH,
    MULTI_VALUE_SEPARATOR,
    OBSERVED_FIELDS,
    OBSERVED_STATUSES,
    OBSERVED_UNKNOWN,
    RECEIPT_FIELDS,
    RECEIPTS_FILENAME,
    RECEIPTS_STATES,
    UNATTRIBUTED,
    UNKNOWN_EFFORT,
    claude_project_slug,
)
from switchboard.registry import ALLOWED_HOSTS, ALLOWED_ROLES, REGISTRY_ENV_VAR

PROJECT_ROOT = Path(__file__).parents[1]
COMMITTED_REGISTRY = PROJECT_ROOT / "registry" / "models.json"
CONTRACT_PATH = PROJECT_ROOT / "docs" / "observatory-contract.json"
FIXTURES = Path(__file__).parent / "fixtures" / "observe"
ADVISORY = "switchboard observe: "
# The placeholder written into every fixture's content fields.
_FIXTURE_CWD = "C:\\fixture\\project"
_TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z")

Doc = dict[str, Any]


@dataclass(frozen=True)
class Env:
    root: Path
    home: Path
    project: Path


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Env]:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv(REGISTRY_ENV_VAR, raising=False)
    monkeypatch.delenv("SWITCHBOARD_CONFIG", raising=False)
    monkeypatch.setattr("switchboard.config._default_config_path", lambda: tmp_path / "absent.json")
    monkeypatch.chdir(project)
    yield Env(root=tmp_path, home=home, project=project)


# --- Helpers ---------------------------------------------------------------------------------


def _observe(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    """``observe`` against the default (temporary) home and the committed registry."""
    rc = main(["observe", *args])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _receipts_file(env: Env) -> Path:
    return env.home / CONFIG_DIRECTORY_NAME / RECEIPTS_FILENAME


def _receipts(env: Env) -> list[Doc]:
    lines = _receipts_file(env).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _roles_json(capsys: pytest.CaptureFixture[str], *args: str) -> Doc:
    rc = main(["inspect", "--roles", "--json", *args])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(report, dict)
    return report


def _rows(report: Doc) -> dict[str, Doc]:
    return {row["role"]: row for row in report["roles"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(name: str) -> Path:
    return FIXTURES / name


def _fixture_lines(name: str) -> list[Doc | str]:
    """The fixture's lines: parsed objects, or the raw text of a line that is not JSON."""
    out: list[Doc | str] = []
    for line in _fixture(name).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append(line)
    return out


def _write_lines(path: Path, lines: list[Doc | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines)
    path.write_text(text, encoding="utf-8")
    return path


def _variant(
    tmp: Path, name: str, edit: Callable[[Doc], None], *, out: str = "variant.jsonl"
) -> Path:
    """A copy of fixture ``name`` with ``edit`` applied to every assistant line."""
    lines = copy.deepcopy(_fixture_lines(name))
    for line in lines:
        if isinstance(line, dict) and line.get("type") == "assistant":
            edit(line)
    return _write_lines(tmp / out, lines)


def _offline_health(config: SwitchboardConfig) -> dict[str, object]:
    return {"reachable": False, "models": [], "model_served": False, "error": "offline"}


# --- Round trip: fixture -> python -m switchboard observe -> receipt -> inspect --roles ------


def test_claude_fixture_round_trips_into_a_receipt_and_inspect_roles(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript = _fixture("claude-role-reviewer.jsonl")

    rc, out, err = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    assert rc == 0, err
    assert err == ""
    [receipt] = _receipts(env)
    assert list(receipt) == list(RECEIPT_FIELDS)
    assert _TS_RE.fullmatch(receipt["ts"])
    assert {k: v for k, v in receipt.items() if k != "ts"} == {
        "host": "claude",
        "role": "reviewer",
        "agent_type": "role-reviewer",
        "requested_model": "claude-sonnet-5-5",
        "requested_effort": "inherit",
        "observed_model": "claude-sonnet-5-5",
        "observed_effort": "medium",
        "source_locator": str(transcript.absolute()),
        "registry_sha256": _sha256(COMMITTED_REGISTRY),
    }
    assert "  role: reviewer" in out
    assert "  requested: claude-sonnet-5-5/inherit" in out
    assert "  observed: claude-sonnet-5-5/medium" in out
    assert "  model: match" in out
    assert "  effort: inherit (the registry requests inherit; nothing to compare)" in out

    report = _roles_json(capsys)
    assert report["receipts_state"] == "ok"
    assert report["receipts_source"] == str(_receipts_file(env))
    assert report["receipts_error"] is None
    rows = _rows(report)
    assert rows["reviewer"]["observed"] == {
        "claude": {
            "model": "claude-sonnet-5-5",
            "effort": "medium",
            "model_status": "match",
            "effort_status": "inherit",
            "ts": receipt["ts"],
            "source_locator": str(transcript.absolute()),
        },
        "codex": OBSERVED_UNKNOWN,
    }
    # inspect --json sorts keys, so compare the key set; the order is the contract's.
    assert sorted(rows["reviewer"]["observed"]["claude"]) == sorted(OBSERVED_FIELDS)
    # The requested pin is unchanged beside it, and no other row picked the receipt up.
    assert rows["reviewer"]["claude"] == {"model": "claude-sonnet-5-5", "effort": "inherit"}
    for role in ALLOWED_ROLES:
        if role != "reviewer":
            assert rows[role]["observed"] == dict.fromkeys(ALLOWED_HOSTS, OBSERVED_UNKNOWN)


def test_codex_fixture_round_trips_and_counts_only_the_threads_own_turns(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    # The fork's inherited parent turn (before subagent_history_start_ordinal) ran gpt-6-astra
    # at high; counting it would make the observed model "gpt-6-astra|gpt-5.6-sol".
    transcript = _fixture("codex-role-builder-fork.jsonl")

    rc, out, err = _observe(capsys, "--host", "codex", "--transcript", str(transcript))

    assert rc == 0, err
    [receipt] = _receipts(env)
    assert receipt["role"] == "builder"
    assert receipt["agent_type"] == "role-builder"
    assert (receipt["requested_model"], receipt["requested_effort"]) == ("gpt-5.6-sol", "medium")
    assert (receipt["observed_model"], receipt["observed_effort"]) == ("gpt-5.6-sol", "medium")
    assert "  model: match" in out and "  effort: match" in out

    observed = _rows(_roles_json(capsys))["builder"]["observed"]
    assert observed["claude"] == OBSERVED_UNKNOWN
    assert observed["codex"]["model"] == "gpt-5.6-sol"
    assert observed["codex"]["model_status"] == "match"
    assert observed["codex"]["effort_status"] == "match"


def test_python_dash_m_observe_then_inspect_roles(env: Env) -> None:
    # INTEGRATION through ``python -m switchboard`` (``__main__`` -> cli.main -> observe).
    child_env = {k: v for k, v in os.environ.items() if k != REGISTRY_ENV_VAR}
    child_env.update(HOME=str(env.home), USERPROFILE=str(env.home), PYTHONIOENCODING="utf-8")
    transcript = _fixture("claude-role-reviewer-style-mismatch.jsonl")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        # The argv carries test-owned temp paths and this test's own fixed flags (see the
        # matching note in test_generate.py), so the S603 noqa is safe.
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "switchboard", *args, "--home", str(env.home)],
            cwd=PROJECT_ROOT,
            env=child_env,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    observed = run("observe", "--host", "claude", "--transcript", str(transcript))
    assert observed.returncode == 0, observed.stderr
    assert "MISMATCH (requested claude-haiku-5-5, observed claude-sonnet-5-5)" in observed.stdout
    assert [r["role"] for r in _receipts(env)] == ["reviewer-style"]

    inspected = run("inspect", "--roles", "--json")
    assert inspected.returncode == 0, inspected.stderr
    row = _rows(json.loads(inspected.stdout))["reviewer-style"]
    assert row["observed"]["claude"]["model_status"] == "mismatch"


# --- Attribution never guesses ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "name", "model", "effort"),
    [
        ("claude", "claude-no-agent-type.jsonl", "claude-opus-5-5", UNKNOWN_EFFORT),
        ("codex", "codex-no-agent-type.jsonl", "gpt-6-astra", "medium"),
    ],
)
def test_a_transcript_with_no_agent_type_yields_an_unattributed_receipt(
    env: Env, capsys: pytest.CaptureFixture[str], host: str, name: str, model: str, effort: str
) -> None:
    rc, out, err = _observe(capsys, "--host", host, "--transcript", str(_fixture(name)))

    assert rc == 0, err
    [receipt] = _receipts(env)
    assert receipt["role"] == UNATTRIBUTED
    assert receipt["agent_type"] is None
    assert receipt["requested_model"] is None and receipt["requested_effort"] is None
    assert (receipt["observed_model"], receipt["observed_effort"]) == (model, effort)
    assert err.splitlines() == [
        f"{ADVISORY}the transcript records no agent type; the receipt is unattributed "
        "(no role is guessed)"
    ]
    assert "  agent type: none recorded" in out
    assert f"  role: {UNATTRIBUTED}" in out
    assert "  model: not compared (unattributed)" in out

    # Not a guess: no row takes the receipt, not even one requesting exactly the observed
    # model (claude-opus-5-5 is diagnosis's, vision-judge's and final-judge's pin).
    for row in _roles_json(capsys)["roles"]:
        assert row["observed"] == dict.fromkeys(ALLOWED_HOSTS, OBSERVED_UNKNOWN)


@pytest.mark.parametrize(
    ("agent_type", "reason"),
    [
        ("general-purpose", "agent type 'general-purpose' is not the agent of a registry role"),
        ("role-grader", "agent type 'role-grader' is not the agent of a registry role"),
        ("reviewer", "agent type 'reviewer' is not the agent of a registry role"),
    ],
)
def test_an_agent_type_that_is_not_a_registry_role_agent_is_unattributed(
    env: Env, capsys: pytest.CaptureFixture[str], agent_type: str, reason: str
) -> None:
    def retype(line: Doc) -> None:
        line[CLAUDE_AGENT_TYPE_FIELD] = agent_type

    transcript = _variant(env.root, "claude-role-reviewer.jsonl", retype)

    rc, _, err = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    assert rc == 0, err
    [receipt] = _receipts(env)
    assert receipt["role"] == UNATTRIBUTED
    assert receipt["agent_type"] == agent_type  # what the host recorded is kept
    assert receipt["requested_model"] is None
    assert reason in err


def test_several_recorded_agent_types_are_unattributed(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _fixture_lines("claude-role-reviewer.jsonl")
    assistants = [line for line in lines if isinstance(line, dict) and line["type"] == "assistant"]
    assistants[-1][CLAUDE_AGENT_TYPE_FIELD] = "role-author"
    transcript = _write_lines(env.root / "two-types.jsonl", lines)

    rc, _, err = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    assert rc == 0, err
    [receipt] = _receipts(env)
    assert receipt["role"] == UNATTRIBUTED
    assert receipt["agent_type"] == "role-reviewer|role-author"
    assert "records 2 agent types ('role-reviewer', 'role-author')" in err


# --- Requested versus observed ---------------------------------------------------------------


def test_a_requested_versus_observed_mismatch_is_displayed(
    env: Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # reviewer-style requests claude-haiku-5-5; the transcript ran claude-sonnet-5-5.
    transcript = _fixture("claude-role-reviewer-style-mismatch.jsonl")

    rc, out, _ = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    assert rc == 0
    assert "  model: MISMATCH (requested claude-haiku-5-5, observed claude-sonnet-5-5)" in out
    [receipt] = _receipts(env)
    assert (receipt["requested_model"], receipt["observed_model"]) == (
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
    )

    observed = _rows(_roles_json(capsys))["reviewer-style"]["observed"]["claude"]
    assert (observed["model_status"], observed["effort_status"]) == ("mismatch", "inherit")

    assert main(["inspect", "--roles"]) == 0
    text = capsys.readouterr().out
    assert (
        "    observed claude=claude-sonnet-5-5/medium (model mismatch, effort inherit) "
        "codex=unknown" in text
    )
    assert (
        "    MISMATCH claude model: requested claude-haiku-5-5, observed claude-sonnet-5-5" in text
    )
    assert text.count("MISMATCH") == 1
    assert f"  receipts: ok ({_receipts_file(env)})" in text

    # The full inspect report carries the same rows and prints the same line.
    monkeypatch.setattr("switchboard.cli.health", _offline_health)
    assert main(["inspect", "--json"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert _rows(full)["reviewer-style"]["observed"]["claude"]["model_status"] == "mismatch"
    assert full["receipts_state"] == "ok"
    assert main(["inspect"]) == 0
    assert "MISMATCH claude model: requested claude-haiku-5-5" in capsys.readouterr().out


def test_an_effort_mismatch_is_displayed(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    # extractor requests claude-sonnet-5-5 at low; this run recorded medium.
    def medium(line: Doc) -> None:
        if CLAUDE_EFFORT_FIELD in line:
            line[CLAUDE_EFFORT_FIELD] = "medium"

    transcript = _variant(env.root, "claude-role-extractor-fork.jsonl", medium)

    rc, out, _ = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    assert rc == 0
    assert "  model: match" in out
    assert "  effort: MISMATCH (requested low, observed medium)" in out
    observed = _rows(_roles_json(capsys))["extractor"]["observed"]["claude"]
    assert (observed["model_status"], observed["effort_status"]) == ("match", "mismatch")


def test_inherited_synthetic_and_torn_lines_are_not_counted(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    # The fork fixture holds an inherited parent turn (no attributionAgent; claude-opus-5-5 at
    # xhigh), a host-made "<synthetic>" message (effort max) and a line that is not JSON.
    rc, out, err = _observe(
        capsys,
        "--host",
        "claude",
        "--transcript",
        str(_fixture("claude-role-extractor-fork.jsonl")),
    )

    assert rc == 0, err
    [receipt] = _receipts(env)
    assert receipt["role"] == "extractor"
    assert (receipt["observed_model"], receipt["observed_effort"]) == ("claude-sonnet-5-5", "low")
    assert "  model: match" in out and "  effort: match" in out
    assert err.splitlines() == [f"{ADVISORY}1 unparseable transcript line(s) skipped"]


def test_several_observed_models_never_read_as_a_match(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _fixture_lines("claude-role-reviewer.jsonl")
    assistants = [line for line in lines if isinstance(line, dict) and line["type"] == "assistant"]
    assistants[-1]["message"]["model"] = "claude-haiku-5-5"
    transcript = _write_lines(env.root / "two-models.jsonl", lines)

    rc, out, err = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    assert rc == 0
    joined = f"claude-sonnet-5-5{MULTI_VALUE_SEPARATOR}claude-haiku-5-5"
    assert _receipts(env)[0]["observed_model"] == joined
    assert f"  model: MISMATCH (requested claude-sonnet-5-5, observed {joined})" in out
    assert "the counted lines record 2 models" in err


def test_the_last_receipt_wins_and_malformed_receipt_lines_are_skipped(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _fixture("claude-role-reviewer.jsonl")
    assert _observe(capsys, "--host", "claude", "--transcript", str(first))[0] == 0
    # Damage the log: a garbage line, then a torn write with no trailing newline.
    with _receipts_file(env).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("not a receipt\n")
        fh.write('{"ts": "2026-11-08T00:00:00.000000Z", "host": "claude"')

    def haiku(line: Doc) -> None:
        line["message"]["model"] = "claude-haiku-5-5"

    second = _variant(env.root, "claude-role-reviewer.jsonl", haiku)
    assert _observe(capsys, "--host", "claude", "--transcript", str(second))[0] == 0

    report = _roles_json(capsys)
    assert report["receipts_state"] == "ok"
    assert report["receipts_error"] == "2 malformed receipt line(s) skipped"
    observed = _rows(report)["reviewer"]["observed"]["claude"]
    assert observed["model"] == "claude-haiku-5-5"  # the later receipt, appended intact
    assert observed["model_status"] == "mismatch"
    assert observed["source_locator"] == str(second.absolute())


def test_receipts_absent_and_unreadable_are_reported_states(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _roles_json(capsys)
    assert (report["receipts_state"], report["receipts_error"]) == ("absent", None)

    _receipts_file(env).mkdir(parents=True)  # a directory where the file belongs
    report = _roles_json(capsys)
    assert report["receipts_state"] == "invalid"
    assert report["receipts_error"].startswith("could not read receipts")
    assert report["registry_state"] == "ok"
    for row in report["roles"]:
        assert row["observed"] == dict.fromkeys(ALLOWED_HOSTS, OBSERVED_UNKNOWN)


# --- --latest ---------------------------------------------------------------------------------


def _stamp(path: Path, when: int) -> Path:
    os.utime(path, (when, when))
    return path


def _claude_project(env: Env, project_dir: Path) -> Path:
    return env.home / ".claude" / "projects" / claude_project_slug(str(project_dir))


def test_latest_claude_picks_the_newest_subagent_transcript(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    proj_a = env.root / "proj_a"
    proj_b = env.root / "proj.b"
    old = _claude_project(env, proj_a) / "s1" / "subagents" / "agent-a1.jsonl"
    old.parent.mkdir(parents=True)
    old.write_bytes(_fixture("claude-role-reviewer.jsonl").read_bytes())
    _stamp(old, 1_000_000)
    workflow = _claude_project(env, proj_b) / "s2" / "subagents" / "workflows" / "wf_1"
    new = workflow / "agent-a2.jsonl"
    new.parent.mkdir(parents=True)
    new.write_bytes(_fixture("claude-role-extractor-fork.jsonl").read_bytes())
    _stamp(new, 2_000_000)
    # Newer still, but not subagent transcripts: the main session and a workflow journal.
    main_session = _claude_project(env, proj_b) / "s2.jsonl"
    main_session.write_bytes(_fixture("claude-no-agent-type.jsonl").read_bytes())
    _stamp(main_session, 3_000_000)
    _stamp(_write_lines(workflow / "journal.jsonl", [{"type": "assistant"}]), 3_000_000)

    assert _observe(capsys, "--host", "claude", "--latest")[0] == 0
    assert main(["observe", "--host", "claude", "--latest", "--project-dir", str(proj_a)]) == 0
    capsys.readouterr()

    receipts = _receipts(env)
    assert [(r["role"], r["source_locator"]) for r in receipts] == [
        ("extractor", str(new)),
        ("reviewer", str(old)),
    ]


@pytest.mark.parametrize(
    ("project_dir", "slug"),
    [
        pytest.param(
            "c:\\Users\\someone\\dev",
            "c--Users-someone-dev",
            marks=pytest.mark.skipif(os.name != "nt", reason="a Windows path"),
        ),
        pytest.param(
            "C:\\Users\\someone\\dev\\pta_finance",
            "C--Users-someone-dev-pta-finance",
            marks=pytest.mark.skipif(os.name != "nt", reason="a Windows path"),
        ),
        pytest.param(
            "/home/someone/my_proj.v2",
            "-home-someone-my-proj-v2",
            marks=pytest.mark.skipif(os.name == "nt", reason="a POSIX path"),
        ),
    ],
)
def test_claude_project_slug_matches_the_real_folder_names(project_dir: str, slug: str) -> None:
    # The Windows cases have the shape of real ~/.claude/projects folder names seen at build
    # time (the drive letter's case is kept; the colon, separators and underscore become -),
    # with a placeholder user name.
    assert claude_project_slug(project_dir) == slug


def _rollout(env: Env, name: str, fixture: str, cwd: Path, when: int) -> Path:
    path = env.home / ".codex" / "sessions" / "2026" / "11" / "08" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _fixture(fixture).read_text(encoding="utf-8")
    text = text.replace(json.dumps(_FIXTURE_CWD)[1:-1], json.dumps(str(cwd))[1:-1])
    path.write_text(text, encoding="utf-8")
    return _stamp(path, when)


def test_latest_codex_picks_the_newest_spawned_subagent_rollout(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    here = env.root / "proj-a"
    there = env.root / "proj-b"
    builder = _rollout(env, "rollout-a.jsonl", "codex-role-builder-fork.jsonl", here, 1_000_000)
    plain = _rollout(env, "rollout-b.jsonl", "codex-no-agent-type.jsonl", there, 2_000_000)
    # The newest rollout is the parent session (not a spawned subagent): never picked.
    _rollout(env, "rollout-c.jsonl", "codex-parent-session.jsonl", here, 3_000_000)

    assert _observe(capsys, "--host", "codex", "--latest")[0] == 0
    assert _observe(capsys, "--host", "codex", "--latest", "--project-dir", str(here))[0] == 0

    receipts = _receipts(env)
    assert [(r["role"], r["source_locator"]) for r in receipts] == [
        (UNATTRIBUTED, str(plain)),
        ("builder", str(builder)),
    ]


@pytest.mark.parametrize("host", ALLOWED_HOSTS)
def test_latest_with_no_subagent_transcript_exits_2_and_writes_nothing(
    env: Env, capsys: pytest.CaptureFixture[str], host: str
) -> None:
    rc, out, err = _observe(capsys, "--host", host, "--latest")

    assert rc == 2
    assert out == ""
    assert len(err.splitlines()) == 1
    assert err.startswith(f"{ADVISORY}no {host} subagent transcript found")
    assert not (env.home / CONFIG_DIRECTORY_NAME).exists()


def test_project_dir_without_latest_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    transcript = str(_fixture("claude-role-reviewer.jsonl"))
    argv = ["observe", "--host", "claude", "--transcript", transcript, "--project-dir", "."]
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "--project-dir requires --latest" in capsys.readouterr().err


# --- No receipt without evidence -------------------------------------------------------------


def _assert_no_receipt(env: Env, rc: int, out: str, err: str, needle: str) -> None:
    assert rc == 2
    assert out == ""
    assert len(err.splitlines()) == 1 and err.startswith(ADVISORY)
    assert needle in err
    assert not _receipts_file(env).exists()


def test_an_invalid_registry_exits_2_and_writes_nothing(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = json.loads(COMMITTED_REGISTRY.read_text(encoding="utf-8"))
    doc["roles"]["reviewer"]["claude"]["model"] = "sonnet"
    bad = env.root / "bad-models.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    transcript = str(_fixture("claude-role-reviewer.jsonl"))

    rc, out, err = _observe(
        capsys, "--host", "claude", "--transcript", transcript, "--registry", str(bad)
    )

    _assert_no_receipt(env, rc, out, err, "registry is invalid")


@pytest.mark.parametrize(
    ("host", "name", "needle"),
    [
        # A Codex rollout has no Claude assistant lines, so no Claude model metadata.
        ("claude", "codex-role-builder-fork.jsonl", "records no claude model metadata"),
        # A Claude transcript has no session_meta line.
        ("codex", "claude-role-reviewer.jsonl", "is not a Codex rollout"),
    ],
)
def test_a_transcript_of_the_other_host_exits_2(
    env: Env, capsys: pytest.CaptureFixture[str], host: str, name: str, needle: str
) -> None:
    rc, out, err = _observe(capsys, "--host", host, "--transcript", str(_fixture(name)))

    _assert_no_receipt(env, rc, out, err, needle)


def test_a_transcript_whose_turns_record_no_model_exits_2(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_model(line: Doc) -> None:
        del line["message"]["model"]

    transcript = _variant(env.root, "claude-role-reviewer.jsonl", no_model)

    rc, out, err = _observe(capsys, "--host", "claude", "--transcript", str(transcript))

    _assert_no_receipt(env, rc, out, err, "not evidence of a dispatch")


def test_a_missing_transcript_or_home_exits_2(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    missing = env.root / "missing.jsonl"
    rc, out, err = _observe(capsys, "--host", "claude", "--transcript", str(missing))
    _assert_no_receipt(env, rc, out, err, "is not a file")

    transcript = str(_fixture("claude-role-reviewer.jsonl"))
    nowhere = str(env.root / "no-home")
    rc, out, err = _observe(
        capsys, "--host", "claude", "--transcript", transcript, "--home", nowhere
    )
    _assert_no_receipt(env, rc, out, err, "is not a directory")


def test_a_failed_append_exits_1(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    _receipts_file(env).mkdir(parents=True)  # the append target is a directory
    transcript = str(_fixture("claude-role-reviewer.jsonl"))

    rc, out, err = _observe(capsys, "--host", "claude", "--transcript", transcript)

    assert rc == 1
    assert out == ""
    assert "error: could not append the receipt" in err


def _strict_cp1252_stdout(monkeypatch: pytest.MonkeyPatch) -> io.TextIOWrapper:
    """A redirected Windows stdout: cp1252 with strict errors, Python's default for stdout."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    return stream


def _written(stream: io.TextIOWrapper) -> str:
    stream.flush()
    buffer = stream.buffer
    assert isinstance(buffer, io.BytesIO)
    return buffer.getvalue().decode("cp1252")


def test_text_stdout_cannot_encode_is_escaped_after_the_append(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The report is printed AFTER the receipt is appended. A non-Latin transcript path and a
    # lone surrogate (a JSON escape the metadata reader accepts) on a cp1252 stdout must not
    # turn a written receipt into a traceback and exit 1, which would invite a duplicate retry.
    def surrogate_model(line: Doc) -> None:
        line["message"]["model"] = "claude-sonnet-5-5\ud800"

    transcript = _variant(env.root / "日本", "claude-role-reviewer.jsonl", surrogate_model)
    stream = _strict_cp1252_stdout(monkeypatch)

    rc = main(["observe", "--host", "claude", "--transcript", str(transcript)])

    out = _written(stream)
    assert rc == 0
    [receipt] = _receipts(env)
    assert receipt["observed_model"] == "claude-sonnet-5-5\ud800"
    assert receipt["source_locator"] == str(transcript)
    assert "  transcript: " in out and "\\u65e5\\u672c" in out
    assert "  observed: claude-sonnet-5-5\\ud800/medium" in out
    assert (
        "  model: MISMATCH (requested claude-sonnet-5-5, observed claude-sonnet-5-5\\ud800)" in out
    )
    assert f"  receipt: appended to {_receipts_file(env)}" in out

    # The inspect text view prints the same receipt value the same way.
    assert main(["inspect", "--roles"]) == 0
    assert (
        "    MISMATCH claude model: requested claude-sonnet-5-5, observed claude-sonnet-5-5\\ud800"
        in _written(stream)
    )


# --- Evidence: field names and synthetic fixtures ----------------------------------------------


def test_the_parsers_read_the_field_names_the_docstring_records() -> None:
    # The constants the parsers use are the names captured from the real transcripts, and the
    # module docstring records each one (a renamed constant without a docstring update fails).
    doc = observe_module.__doc__ or ""
    recorded = [
        "message.model",
        f"``{CLAUDE_EFFORT_FIELD}``",
        f"``{CLAUDE_AGENT_TYPE_FIELD}``",
        f'"{CLAUDE_SYNTHETIC_MODEL}"',
        '"type": "assistant"',
        '"type": "session_meta"',
        '"type": "turn_context"',
        ".".join((*CODEX_SPAWN_PATH, CODEX_AGENT_TYPE_FIELD)),
        ".".join(CODEX_HISTORY_START_PATH),
        f"``{'.'.join(CODEX_MODEL_PATH)}``",
        f"``{'.'.join(CODEX_EFFORT_PATH)}``",
        "Claude Code 2.1.318",
        "Codex CLI 0.155.0-alpha.16.3",
    ]
    assert ".".join(CLAUDE_MODEL_PATH) == "message.model"
    missing = [name for name in recorded if name not in doc]
    assert missing == []


def _strings(value: object, key: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, str):
        yield key, value


# A session id (UUID) or a Claude agent id; the synthetic ones carry a run of eight zeros.
_IDENTIFIER_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\ba[0-9a-f]{16}\b", re.I
)
_SYNTHETIC_ID_MARK = "00000000"
# A user's home directory (``C:\Users\<user>``, its ``C--Users-<user>`` project folder name,
# ``/Users/<user>``, ``/home/<user>``) or a real Codex rollout's timestamped file name.
_HOME_PATH_RE = re.compile(r"users[\\/-]|/home/", re.I)
_ROLLOUT_STAMP_RE = re.compile(r"rollout-\d{4}-\d\d-\d\dT")


def _identifier_leaks(text: str) -> list[str]:
    """Identifier-shaped strings in ``text`` other than the synthetic all-zero ones."""
    leaks = [m.group() for m in _IDENTIFIER_RE.finditer(text)]
    leaks = [leak for leak in leaks if _SYNTHETIC_ID_MARK not in leak]
    leaks += [m.group() for m in _HOME_PATH_RE.finditer(text)]
    leaks += [m.group() for m in _ROLLOUT_STAMP_RE.finditer(text)]
    return leaks


def test_the_module_records_field_names_without_real_session_identifiers() -> None:
    # The docstring cites the real transcripts by shape only: placeholders for the project
    # folder, session id, agent id and date (criterion 2: only synthetic values are committed).
    source = Path(observe_module.__file__).read_text(encoding="utf-8")
    assert _identifier_leaks(source) == []
    doc = observe_module.__doc__ or ""
    assert "~/.claude/projects/<project>/<session-uuid>/subagents/agent-<agent-id>.jsonl" in doc
    assert "~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-<timestamp>-<session-uuid>.jsonl" in doc


@pytest.mark.parametrize(
    "garbage",
    [
        # Real-shaped, made-up values: the guard must flag each one, or it proves nothing.
        "~/.claude/projects/c--Users-someone-dev/1f2e3d4c-5b6a-4789-9abc-def012345678/",
        "subagents/agent-a1b2c3d4e5f60718a.jsonl",
        "~/.codex/sessions/2026/01/02/rollout-2026-01-02T03-04-05-x.jsonl",
        "C:\\Users\\someone\\dev",
        "/home/someone/dev",
    ],
)
def test_identifier_leak_guard_flags_real_shaped_values(garbage: str) -> None:
    assert _identifier_leaks(garbage) != []
    assert _identifier_leaks("00000000-0000-4000-8000-000000000001 a00000000000000a1") == []


def test_fixtures_are_synthetic() -> None:
    names = sorted(path.name for path in FIXTURES.iterdir())
    assert names == [
        "claude-no-agent-type.jsonl",
        "claude-role-extractor-fork.jsonl",
        "claude-role-reviewer-style-mismatch.jsonl",
        "claude-role-reviewer.jsonl",
        "codex-no-agent-type.jsonl",
        "codex-parent-session.jsonl",
        "codex-role-builder-fork.jsonl",
    ]
    for name in names:
        raw = _fixture(name).read_text(encoding="utf-8")
        # No session or agent id copied from a real transcript, and no real home path.
        assert _identifier_leaks(raw) == [], name
        for line in _fixture_lines(name):
            if isinstance(line, str):
                assert line.startswith("SYNTHETIC"), (name, line)
                continue
            for key, text in _strings(line):
                if key in ("text", "content"):
                    assert text.startswith("SYNTHETIC"), (name, key, text)


# --- The producer-owned observatory contract -------------------------------------------------

Mutation = Callable[[Doc], None]


def _contract() -> Doc:
    data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _receipts_contract_drift(contract: Doc) -> list[str]:
    """Every receipts or observed contract fact that differs from the runtime constants."""
    drift: list[str] = []
    receipts = contract.get("receipts", {})
    inspect = contract.get("inspect", {})
    expected: list[tuple[str, object, object]] = [
        ("receipts.directory_name", receipts.get("directory_name"), CONFIG_DIRECTORY_NAME),
        ("receipts.filename", receipts.get("filename"), RECEIPTS_FILENAME),
        ("receipts.fields", receipts.get("fields"), list(RECEIPT_FIELDS)),
        ("receipts.hosts", receipts.get("hosts"), list(ALLOWED_HOSTS)),
        ("receipts.unattributed_role", receipts.get("unattributed_role"), UNATTRIBUTED),
        ("receipts.unknown_effort", receipts.get("unknown_effort"), UNKNOWN_EFFORT),
        (
            "receipts.multi_value_separator",
            receipts.get("multi_value_separator"),
            MULTI_VALUE_SEPARATOR,
        ),
        (
            "receipts.nullable_fields",
            receipts.get("nullable_fields"),
            ["agent_type", "requested_model", "requested_effort", "registry_sha256"],
        ),
        (
            "inspect.role_observed_fields",
            inspect.get("role_observed_fields"),
            list(OBSERVED_FIELDS),
        ),
        ("inspect.observed_statuses", inspect.get("observed_statuses"), list(OBSERVED_STATUSES)),
        ("inspect.observed_unknown", inspect.get("observed_unknown"), OBSERVED_UNKNOWN),
        ("inspect.receipts_states", inspect.get("receipts_states"), list(RECEIPTS_STATES)),
    ]
    for label, got, want in expected:
        if got != want:
            drift.append(f"{label}: contract={got!r} runtime={want!r}")
    return drift


def test_observatory_contract_receipts_section_matches_runtime() -> None:
    assert _receipts_contract_drift(_contract()) == []


def test_contract_nullable_fields_are_the_ones_a_receipt_may_leave_null(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    # Shape, not a copy: an unattributed receipt's null keys are exactly the nullable ones,
    # and inspect parses such a line back (it is not counted as malformed).
    rc, _, _ = _observe(
        capsys, "--host", "claude", "--transcript", str(_fixture("claude-no-agent-type.jsonl"))
    )
    assert rc == 0
    [receipt] = _receipts(env)
    nulls = [key for key, value in receipt.items() if value is None]
    assert nulls == ["agent_type", "requested_model", "requested_effort"]
    assert set(nulls) <= set(_contract()["receipts"]["nullable_fields"])
    assert _roles_json(capsys)["receipts_error"] is None


def _set(path: tuple[str, ...], value: object) -> Mutation:
    def mutate(doc: Doc) -> None:
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("receipts", "fields"), [f for f in RECEIPT_FIELDS if f != "agent_type"]),
        _set(("receipts", "filename"), "receipts.json"),
        _set(("receipts", "unattributed_role"), "unknown"),
        _set(("receipts", "unknown_effort"), "unknown"),
        _set(("receipts", "hosts"), ["claude", "codex", "copilot"]),
        _set(("inspect", "observed_statuses"), ["match", "mismatch"]),
        _set(("inspect", "role_observed_fields"), ["model", "effort"]),
        _set(("inspect", "observed_unknown"), "UNKNOWN"),
    ],
)
def test_receipts_contract_drift_guard_fails_on_any_field_change(mutate: Mutation) -> None:
    # Red-on-garbage: the comparison must FAIL on a drifted copy, or it proves nothing.
    contract = _contract()
    mutate(contract)
    assert _receipts_contract_drift(contract) != []
