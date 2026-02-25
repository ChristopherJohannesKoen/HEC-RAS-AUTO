from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic import ConfigDict


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    scenario_id: str
    title: str
    flow_multiplier_upstream: float
    flow_multiplier_tributary: float
    rationale: str
    references: list[str] = Field(default_factory=list)
    parameter_adjustments: dict[str, float] = Field(default_factory=dict)
