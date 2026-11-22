import os
import subprocess
import sysconfig
from pathlib import Path

import pytest


def _run_faultbox(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    executable_name = "faultbox.exe" if os.name == "nt" else "faultbox"
    executable = Path(sysconfig.get_path("scripts")) / executable_name

    return subprocess.run(
        [str(executable), *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize("arguments", [(), ("--help",)], ids=["no-arguments", "help-option"])
def test_installed_faultbox_shows_help(arguments: tuple[str, ...]) -> None:
    result = _run_faultbox(*arguments)

    assert result.returncode == 0
    assert "faultbox" in result.stdout
    assert "--help" in result.stdout
    assert "check" in result.stdout
    assert result.stderr == ""


def test_check_accepts_readme_example(tmp_path: Path) -> None:
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    scenario = readme.split("```toml\n", 1)[1].split("```", 1)[0]
    body = readme.split("```json\n", 1)[1].split("```", 1)[0]
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(scenario, encoding="utf-8")
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "payment.json").write_text(body, encoding="utf-8")
    working_directory = tmp_path / "working-directory"
    working_directory.mkdir()

    result = _run_faultbox("check", str(scenario_path), cwd=working_directory)

    assert result.returncode == 0
    assert result.stdout.strip() == f"Scenario is valid: {scenario_path}"
    assert result.stderr == ""


def test_check_rejects_invalid_scenario(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text("routes = []\n", encoding="utf-8")

    result = _run_faultbox("check", str(scenario_path))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == f"faultbox: {scenario_path}: routes: expected a non-empty array"


def test_check_rejects_missing_scenario(tmp_path: Path) -> None:
    scenario_path = tmp_path / "missing.toml"

    result = _run_faultbox("check", str(scenario_path))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith(f"faultbox: {scenario_path}: cannot read scenario:")
    assert "Traceback" not in result.stderr


def test_check_requires_scenario_argument() -> None:
    result = _run_faultbox("check")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "required" in result.stderr
    assert "scenario" in result.stderr
    assert "Traceback" not in result.stderr
