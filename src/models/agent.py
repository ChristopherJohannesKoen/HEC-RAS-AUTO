from __future__ import annotations

from pydantic import BaseModel, Field


class PromptCompilerPrompts(BaseModel):
    extract_job_spec: str = ""
    repair_job_spec: str = ""


class PlannerPrompts(BaseModel):
    compile_plan: str = ""


class RepairPrompts(BaseModel):
    stage_retry: str = ""


class ReportPrompts(BaseModel):
    interpretation: str = ""
    full_report: str = ""


class PromptConfig(BaseModel):
    anomaly_triage: str = ""
    report_reasoning: str = ""
    input_review: str = ""
    prompt_compiler: PromptCompilerPrompts = Field(default_factory=PromptCompilerPrompts)
    planner: PlannerPrompts = Field(default_factory=PlannerPrompts)
    repair: RepairPrompts = Field(default_factory=RepairPrompts)
    report: ReportPrompts = Field(default_factory=ReportPrompts)


class AIAgentConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-5"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.1
    max_tokens: int = 800
    prompts: PromptConfig = Field(default_factory=PromptConfig)


class AIConfig(BaseModel):
    ai: AIAgentConfig
