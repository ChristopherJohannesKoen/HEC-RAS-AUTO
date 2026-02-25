from pathlib import Path

from src.scenarios.scenario_loader import load_scenario


def test_load_scenario_2_config() -> None:
    spec = load_scenario(Path("config/scenarios/scenario_2_climate.yml"))
    assert spec.scenario_id == "scenario_2"
    assert spec.flow_multiplier_upstream > 1.0
    assert spec.flow_multiplier_tributary > 1.0
