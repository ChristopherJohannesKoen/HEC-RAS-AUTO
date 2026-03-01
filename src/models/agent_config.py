from __future__ import annotations

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    parser_model: str = "gpt-5"
    planner_model: str = "gpt-5"
    max_parse_retries: int = 2
    enable_self_heal: bool = True
    retry_budget_per_stage: int = 1
    strict_mode_default: bool = True
    assigned_scenario_required: bool = True
    automation_policy_file: str = "config/automation.yml"


class RetrievalConfig(BaseModel):
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    max_sources_per_claim: int = 2
    recency_days: int = 3650
    citation_confidence_threshold: float = 0.6


class AgentSettings(BaseModel):
    agent: AgentConfig


class RetrievalSettings(BaseModel):
    retrieval: RetrievalConfig
