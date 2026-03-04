from __future__ import annotations

import pytest

from src.scenarios.scenario_registry import build_scenario_spec
from src.scenarios.scenario_2_climate import build_spec_from_tier_profile


@pytest.mark.parametrize("sid", ["scenario_1", "scenario_2", "scenario_3", "scenario_4"])
def test_scenario_registry_dispatch(sid: str) -> None:
    spec = build_scenario_spec(sid, climate_multiplier=1.2)
    assert spec.scenario_id == sid


def test_scenario_2_multiplier_applied() -> None:
    spec = build_scenario_spec("scenario_2", climate_multiplier=1.2)
    assert spec.flow_multiplier_upstream == 1.2
    assert spec.flow_multiplier_tributary == 1.2


def test_scenario_2_tier_profile_builder() -> None:
    spec = build_spec_from_tier_profile(
        tier_id="conservative",
        upstream_multiplier=1.6,
        tributary_multiplier=1.6,
        rationale="Tiered climate uplift.",
        references=["https://example.com/ref1"],
    )
    assert spec.scenario_id == "scenario_2"
    assert spec.flow_multiplier_upstream == 1.6
    assert spec.flow_multiplier_tributary == 1.6
    assert "conservative" in spec.title.lower()
    assert spec.references
