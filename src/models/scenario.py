from __future__ import annotations

from pydantic import BaseModel, Field


class ScenarioSpec(BaseModel):
    scenario_id: str
    title: str
    flow_multiplier_upstream: float
    flow_multiplier_tributary: float
    rationale: str
    references: list[str] = Field(default_factory=list)
