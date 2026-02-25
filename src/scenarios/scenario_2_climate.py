from __future__ import annotations

from src.models import ScenarioSpec


def build_spec(multiplier: float = 1.15) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario_2",
        title=f"Climate Intensification x{multiplier:.2f}",
        flow_multiplier_upstream=float(multiplier),
        flow_multiplier_tributary=float(multiplier),
        rationale="Represents rare-event flood intensity increase under projected climate change. [CITE]",
        references=[],
        parameter_adjustments={"flow_multiplier": float(multiplier)},
    )
