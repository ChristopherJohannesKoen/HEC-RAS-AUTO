from __future__ import annotations

from src.models import ScenarioSpec


def build_spec() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario_1",
        title="Informal Settlement Development",
        flow_multiplier_upstream=1.00,
        flow_multiplier_tributary=1.00,
        rationale=(
            "Represents reduced right-bank floodplain effectiveness and changed surface condition. "
            "[VERIFY][CITE]"
        ),
        references=[],
        parameter_adjustments={
            "right_floodplain_n": 0.045,
            "effective_storage_factor": 0.85,
        },
    )
