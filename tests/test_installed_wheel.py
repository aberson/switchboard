"""INTEGRATION: a real built wheel, installed into a temporary venv, finds its role registry.

An installed tool (``uv tool install``) has no repository, so ``registry/models.json`` at the
repository root does not exist for it; the wheel must carry the registry as package data and
the default resolver must find that copy. This test builds the sdist and the wheel with
``uv build`` (the wheel is built from the sdist, so the sdist must carry the registry too),
installs the wheel with no network into a fresh virtual environment created from this
interpreter, and drives the installed ``switchboard`` console command. Every command gets a
temporary ``--home`` (and ``HOME``/``USERPROFILE``), so the real home is never read or written.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from switchboard.registry import ALLOWED_ROLES, REGISTRY_ENV_VAR

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).parents[1]
COMMITTED_REGISTRY = PROJECT_ROOT / "registry" / "models.json"
PACKAGED_MEMBER = "switchboard/_registry/models.json"
TIMEOUT_SECONDS = 300


def _pyproject_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    assert isinstance(version, str)
    return version


def _env(home: Path) -> dict[str, str]:
    # No inherited registry/config selection and no outer virtual environment; a temporary home.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("SWITCHBOARD_") and k not in {"VIRTUAL_ENV", "PYTHONPATH"}
    }
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    return env


def _run(
    argv: list[str], cwd: Path, env: dict[str, str], timeout: int = TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    # argv is the uv executable or the installed console script plus this module's fixed flags.
    return subprocess.run(  # noqa: S603
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def _ok(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, f"exit {proc.returncode}\nstdout:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _single(directory: Path, pattern: str) -> Path:
    found = sorted(directory.glob(pattern))
    assert len(found) == 1, f"expected one {pattern} in {directory}, found {found}"
    return found[0]


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Build sdist + wheel, install the wheel into a fresh venv; return the paths the tests use."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH; the installed-wheel test needs it to build and install")
    root = tmp_path_factory.mktemp("installed-wheel")
    home = root / "home"
    home.mkdir()
    dist = root / "dist"
    venv = root / "venv"
    env = _env(home)

    # A plain `uv build` builds the sdist, then the wheel from that sdist.
    _ok(_run([uv, "build", "--out-dir", str(dist), str(PROJECT_ROOT)], root, env))
    _ok(_run([uv, "venv", "--python", sys.executable, str(venv)], root, env))
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    wheel = _single(dist, "switchboard-*.whl")
    install = [uv, "pip", "install", "--python", str(python), "--no-deps", "--offline"]
    _ok(_run([*install, str(wheel)], root, env))
    script = shutil.which("switchboard", path=str(bin_dir))
    assert script is not None, f"console script not installed in {bin_dir}"
    return {"root": root, "home": home, "dist": dist, "venv": venv, "script": Path(script)}


def test_wheel_and_sdist_carry_the_committed_registry(installed: dict[str, Path]) -> None:
    committed = COMMITTED_REGISTRY.read_bytes()
    with zipfile.ZipFile(_single(installed["dist"], "switchboard-*.whl")) as wheel:
        assert wheel.read(PACKAGED_MEMBER) == committed
    with tarfile.open(_single(installed["dist"], "switchboard-*.tar.gz")) as sdist:
        members = {m.name.split("/", 1)[1]: m for m in sdist.getmembers() if "/" in m.name}
        extracted = sdist.extractfile(members["registry/models.json"])
        assert extracted is not None
        assert extracted.read() == committed


def test_installed_version_reports_the_pyproject_version(installed: dict[str, Path]) -> None:
    proc = _run([str(installed["script"]), "--version"], installed["root"], _env(installed["home"]))

    assert _ok(proc).strip() == f"switchboard {_pyproject_version()}"


def test_installed_inspect_roles_reads_the_packaged_registry(installed: dict[str, Path]) -> None:
    home = installed["home"]
    argv = [str(installed["script"]), "inspect", "--roles", "--json", "--home", str(home)]

    report = json.loads(_ok(_run(argv, installed["root"], _env(home))))

    assert report["registry_state"] == "ok", report["error"]
    assert report["error"] is None
    source = report["source"]
    assert source.startswith("package:"), source
    packaged = Path(source.removeprefix("package:"))
    assert packaged.is_relative_to(installed["venv"].resolve())
    assert packaged.read_bytes() == COMMITTED_REGISTRY.read_bytes()
    assert [row["role"] for row in report["roles"]] == list(ALLOWED_ROLES)


def test_installed_apply_previews_role_files_without_writing(installed: dict[str, Path]) -> None:
    home = installed["home"]
    before = sorted(home.rglob("*"))

    out = _ok(
        _run(
            [str(installed["script"]), "apply", "--home", str(home)],
            installed["root"],
            _env(home),
        )
    )

    assert "registry: ok (package:" in out
    for role in ALLOWED_ROLES:
        assert f"role-{role}.md" in out
        assert f"role-{role}.toml" in out
    # A dry run: the temporary home is untouched (no role files, no ~/.switchboard).
    assert sorted(home.rglob("*")) == before


def test_installed_env_and_arg_outrank_the_packaged_registry(
    installed: dict[str, Path], tmp_path: Path
) -> None:
    home = installed["home"]
    garbage = tmp_path / "garbage.json"
    garbage.write_text("not json", encoding="utf-8")
    base = [str(installed["script"]), "inspect", "--roles", "--json", "--home", str(home)]
    env = _env(home) | {REGISTRY_ENV_VAR: str(garbage)}

    from_env = json.loads(_ok(_run(base, installed["root"], env)))
    from_arg = json.loads(
        _ok(_run([*base, "--registry", str(garbage)], installed["root"], _env(home)))
    )

    assert from_env["registry_state"] == "invalid"
    assert from_env["source"] == f"env:{garbage}"
    assert from_arg["registry_state"] == "invalid"
    assert from_arg["source"] == f"arg:{garbage}"
