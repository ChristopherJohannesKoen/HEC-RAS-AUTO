from __future__ import annotations

from src.models import ScenarioSpec


def build_spec() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario_3",
        title="Riverside Tourism Development",
        flow_multiplier_upstream=1.00,
        flow_multiplier_tributary=1.05,
        rationale=(
            "Represents local confluence-area platform raising and conveyance changes for riverside infrastructure. "
            "[VERIFY][CITE]"
        ),
        references=[],
        parameter_adjustments={
            "confluence_storage_factor": 0.9,
            "confluence_overbank_n": 0.05,
        },
    )
