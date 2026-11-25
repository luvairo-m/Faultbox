import os
import socket
import subprocess
import sysconfig
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path

import pytest

from faultbox.commands.run import run_scenario


RUN_SCENARIO = """\
[[routes]]
id = "payments"
method = "GET"
path = "/payments"

[[routes.steps]]
status = 200
"""


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
    assert "run" in result.stdout
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


@pytest.fixture
def occupied_port() -> Iterator[int]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        yield listener.getsockname()[1]


def test_run_shows_help() -> None:
    result = _run_faultbox("run", "--help")

    assert result.returncode == 0
    assert "scenario" in result.stdout
    assert "--port" in result.stdout
    assert "8080" in result.stdout
    assert result.stderr == ""


def test_run_rejects_out_of_range_port() -> None:
    result = _run_faultbox("run", "scenario.toml", "--port", "65536")

    assert result.returncode == 2
    assert "argument --port: must be between 1 and 65535" in result.stderr


@pytest.mark.parametrize(
    ("step_fields", "message"),
    [
        ('body_file = "missing.json"\n', "body_file: cannot read 'missing.json'"),
        ("delay_ms = 1\n", "delay_ms > 0 is not supported yet"),
    ],
)
def test_run_validates_before_binding(
    step_fields: str, message: str, tmp_path: Path, occupied_port: int
) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(RUN_SCENARIO + step_fields, encoding="utf-8")

    result = _run_faultbox("run", str(scenario_path), "--port", str(occupied_port))

    assert result.returncode == 1
    assert result.stdout == ""
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_run_reports_occupied_port(tmp_path: Path, occupied_port: int) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(RUN_SCENARIO, encoding="utf-8")

    result = _run_faultbox("run", str(scenario_path), "--port", str(occupied_port))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == (
        f"faultbox: cannot listen on 127.0.0.1:{occupied_port}: port is already in use"
    )


def test_run_serves_404_and_closes_on_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(RUN_SCENARIO, encoding="utf-8")
    listeners: list[socket.socket] = []

    def serve_until_interrupted(server: HTTPServer) -> None:
        listeners.append(server.socket)
        assert server.server_address == ("127.0.0.1", server.server_port)
        server.timeout = 2

        with ThreadPoolExecutor(max_workers=1) as executor:
            for method, path in [("GET", "/payments"), ("POST", "/__faultbox/reset")]:
                request = executor.submit(server.handle_request)
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                with closing(connection):
                    connection.request(method, path)
                    with connection.getresponse() as response:
                        assert response.status == 404
                        response.read()

                request.result(timeout=2)

        raise KeyboardInterrupt

    monkeypatch.setattr(HTTPServer, "serve_forever", serve_until_interrupted)

    assert run_scenario(scenario_path, port=0) == 0
    assert listeners[0].fileno() == -1
    assert capsys.readouterr().out.startswith("Listening on http://127.0.0.1:")
