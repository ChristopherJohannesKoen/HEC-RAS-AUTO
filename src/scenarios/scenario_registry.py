from __future__ import annotations

from src.models import ScenarioSpec
from src.scenarios import scenario_1_settlement, scenario_2_climate, scenario_3_tourism, scenario_4_rehab


def build_scenario_spec(scenario_id: str, climate_multiplier: float | None = None) -> ScenarioSpec:
    sid = scenario_id.lower().strip()
    if sid == "scenario_1":
        return scenario_1_settlement.build_spec()
    if sid == "scenario_2":
        return scenario_2_climate.build_spec(multiplier=climate_multiplier or 1.15)
    if sid == "scenario_3":
        return scenario_3_tourism.build_spec()
    if sid == "scenario_4":
        return scenario_4_rehab.build_spec()
    raise ValueError(f"Unsupported scenario id: {scenario_id}")
