from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class PromptJobSpec(BaseModel):
    project_name: str
    objective: str
    baseline_required: bool = True
    assigned_scenario: str = "scenario_2"
    required_outputs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    boundary_conditions: dict[str, Any] = Field(default_factory=dict)
    roughness_rules: dict[str, float] = Field(default_factory=dict)
    qa_policy: str = "strict"
    evidence_policy: str = "web-assisted"
    source_paths: list[str] = Field(default_factory=list)
    raw_prompt: str = ""
    parser_confidence: float = 0.0


class TaskNode(BaseModel):
    node_id: str
    tool_action: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    retry_rule: Optional[str] = None
    terminal_on_fail: bool = True


class ExecutionPlan(BaseModel):
    run_id: str
    task_graph: list[TaskNode] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    retry_playbook: dict[str, dict[str, Any]] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)


class AgentDecision(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    stage: str
    decision_type: str
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    model_response_id: Optional[str] = None


class CitationRecord(BaseModel):
    source_url: str
    title: str
    publisher: str
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    claim_text: str
    confidence: float
    allowed_quote_excerpt: str = ""


class SubmissionPackManifest(BaseModel):
    run_id: str
    baseline_artifacts: dict[str, str] = Field(default_factory=dict)
    scenario_artifacts: dict[str, str] = Field(default_factory=dict)
    scenario_runs: dict[str, dict[str, str]] = Field(default_factory=dict)
    scenario_run_ids: list[str] = Field(default_factory=list)
    primary_scenario_run_id: str = ""
    comparison_artifacts: dict[str, str] = Field(default_factory=dict)
    report_paths: list[str] = Field(default_factory=list)
    cad_paths: list[str] = Field(default_factory=list)
    qa_paths: list[str] = Field(default_factory=list)
    unresolved_verify_items: list[str] = Field(default_factory=list)
    manifest_path: Optional[Path] = None
