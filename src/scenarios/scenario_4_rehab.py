from __future__ import annotations

from src.models import ScenarioSpec


def build_spec() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario_4",
        title="Floodplain Rehabilitation",
        flow_multiplier_upstream=1.00,
        flow_multiplier_tributary=1.00,
        rationale=(
            "Represents increased floodplain roughness and restored riparian function along the reach. [VERIFY][CITE]"
        ),
        references=[],
        parameter_adjustments={
            "floodplain_n": 0.08,
            "retardance_factor": 1.1,
        },
    )
