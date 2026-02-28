from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Scenario2SweepConfig(BaseModel):
    enabled: bool = False
    fixed_multiplier: float = 1.15
    sweep_enabled: bool = False
    sweep_values: list[float] = Field(default_factory=lambda: [1.1, 1.15, 1.2])


class AutomationPolicy(BaseModel):
    mode: Literal["guardrailed", "self_healing", "best_effort"] = "guardrailed"
    strict_geometry: bool = True
    strict_hydraulics: bool = True
    max_retries: int = 1
    require_source_files: bool = True
    allow_fallback_xs_fill: bool = True
    scenario2: Scenario2SweepConfig = Field(default_factory=Scenario2SweepConfig)
    stop_on: list[str] = Field(default_factory=list)


class AutomationConfig(BaseModel):
    autopilot: AutomationPolicy


class RunStepState(BaseModel):
    step: str
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    notes: Optional[str] = None


class RunState(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    status: Literal["running", "completed", "failed"] = "running"
    steps: list[RunStepState] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    retries: int = 0


class AutopilotIssue(BaseModel):
    severity: Literal["info", "warn", "error", "critical"]
    stage: str
    message: str
    evidence: list[Path] = Field(default_factory=list)
    suggested_recovery: Optional[str] = None
    terminal: bool = False
