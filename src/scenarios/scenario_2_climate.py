from __future__ import annotations

from src.models import ScenarioSpec


def build_spec(multiplier: float = 1.30) -> ScenarioSpec:
    references = [
        "https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-8/",
        "https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-11/",
        "https://repository.up.ac.za/bitstream/handle/2263/88622/McBride_Changes_2022.pdf?sequence=1",
        "https://www.wrc.org.za/wp-content/uploads/mdocs/TT%20921%20final%20web.pdf",
        "https://www.dws.gov.za/iwrp/uMkhomazi/Documents/Module%201/2/P%20WMA%2011_U10_00_3312_3_1_11%20-%20Climate%20Change_FINAL.pdf",
    ]
    return ScenarioSpec(
        scenario_id="scenario_2",
        title=f"Climate Intensification x{multiplier:.2f}",
        flow_multiplier_upstream=float(multiplier),
        flow_multiplier_tributary=float(multiplier),
        rationale=(
            "Represents non-stationary rare-event flood forcing under climate intensification. "
            "Scenario 2 modifies only hydrologic forcing (peak-flow multipliers), keeping geometry and roughness fixed."
        ),
        references=references,
        parameter_adjustments={"flow_multiplier": float(multiplier)},
    )


def build_spec_from_tier_profile(
    tier_id: str,
    upstream_multiplier: float,
    tributary_multiplier: float,
    rationale: str = "",
    references: list[str] | None = None,
) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario_2",
        title=f"Climate Intensification ({tier_id.title()})",
        flow_multiplier_upstream=float(upstream_multiplier),
        flow_multiplier_tributary=float(tributary_multiplier),
        rationale=(
            rationale.strip()
            or "Scenario 2 climate intensification tier with multiplicative peak-flow scaling."
        ),
        references=list(references or []),
        parameter_adjustments={
            "flow_multiplier_upstream": float(upstream_multiplier),
            "flow_multiplier_tributary": float(tributary_multiplier),
        },
    )
