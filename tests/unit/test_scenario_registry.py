from __future__ import annotations

import pytest

from src.scenarios.scenario_registry import build_scenario_spec


@pytest.mark.parametrize("sid", ["scenario_1", "scenario_2", "scenario_3", "scenario_4"])
def test_scenario_registry_dispatch(sid: str) -> None:
    spec = build_scenario_spec(sid, climate_multiplier=1.2)
    assert spec.scenario_id == sid


def test_scenario_2_multiplier_applied() -> None:
    spec = build_scenario_spec("scenario_2", climate_multiplier=1.2)
    assert spec.flow_multiplier_upstream == 1.2
    assert spec.flow_multiplier_tributary == 1.2
