"""The two production entry points: the `switchboard` console command and `python -m switchboard`.

Both must resolve to ``switchboard.cli.main``, so every subcommand and the ``--version`` health
check behave identically through either. These tests drive the real installed entry points in
subprocesses (the console script ``uv sync`` installs beside the interpreter, and ``-m``), not
only the in-process function.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from switchboard import cli

PROJECT_ROOT = Path(__file__).parents[1]
CONSOLE_SCRIPT = "switchboard"


def _pyproject_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    assert isinstance(version, str)
    return version


def _console_script_path() -> str:
    """The installed console script beside this interpreter; a missing one is a red test."""
    scripts_dir = Path(sys.executable).parent
    found = shutil.which(CONSOLE_SCRIPT, path=str(scripts_dir))
    assert found is not None, (
        f"console script {CONSOLE_SCRIPT!r} is not installed in {scripts_dir}; "
        "run `uv sync --extra dev` so [project.scripts] is installed"
    )
    return found


def _child_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SWITCHBOARD_")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    return env


def _run(argv: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    # argv is a test-owned interpreter or installed script path plus this module's fixed flags.
    return subprocess.run(  # noqa: S603
        argv,
        cwd=PROJECT_ROOT,
        env=_child_env(home),
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_version_string_comes_from_the_one_version_source() -> None:
    # pyproject.toml is the only place the version is written; metadata and the CLI read it.
    assert metadata.version(cli.DISTRIBUTION_NAME) == _pyproject_version()
    assert cli.package_version() == _pyproject_version()


def test_package_version_without_metadata_is_total(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> str:
        raise metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(cli.metadata, "version", missing)
    assert cli.package_version() == cli.UNKNOWN_VERSION


def test_version_flag_in_process(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out == f"switchboard {_pyproject_version()}\n"


def test_console_script_entry_point_is_cli_main() -> None:
    (entry,) = metadata.entry_points(group="console_scripts", name=CONSOLE_SCRIPT)
    assert entry.value == "switchboard.cli:main"
    assert entry.load() is cli.main


def test_python_dash_m_version(tmp_path: Path) -> None:
    result = _run([sys.executable, "-m", "switchboard", "--version"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"switchboard {_pyproject_version()}\n"


def test_console_script_version(tmp_path: Path) -> None:
    result = _run([_console_script_path(), "--version"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"switchboard {_pyproject_version()}\n"


def test_both_entry_points_give_the_same_subcommand_output(tmp_path: Path) -> None:
    # A real subcommand through both production entry points: the registry table reads only the
    # committed registry and the (empty) temp home, so the two outputs must be byte-identical.
    args = ["inspect", "--roles", "--json", "--home", str(tmp_path)]
    via_module = _run([sys.executable, "-m", "switchboard", *args], tmp_path)
    via_script = _run([_console_script_path(), *args], tmp_path)
    assert via_module.returncode == 0, via_module.stderr
    assert via_script.returncode == 0, via_script.stderr
    assert via_module.stdout == via_script.stdout
    assert '"registry_state": "ok"' in via_script.stdout


def test_console_script_usage_error_exits_2(tmp_path: Path) -> None:
    # The console command has no bare live-smoke mode: with no subcommand it is a usage error.
    result = _run([_console_script_path()], tmp_path)
    assert result.returncode == 2
    assert "required" in result.stderr
