from pathlib import Path

import pytest


@pytest.fixture
def readme_scenario_path(tmp_path: Path) -> Path:
    readme_path = Path(__file__).resolve().parents[1] / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    scenario = readme.split("```toml\n", 1)[1].split("```", 1)[0]
    body = readme.split("```json\n", 1)[1].split("```", 1)[0]

    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(scenario, encoding="utf-8")
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "payment.json").write_bytes(body.encode("utf-8"))

    return scenario_path
