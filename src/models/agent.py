from __future__ import annotations

from pydantic import BaseModel, Field


class PromptConfig(BaseModel):
    anomaly_triage: str = ""
    report_reasoning: str = ""


class AIAgentConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.1
    max_tokens: int = 800
    prompts: PromptConfig = Field(default_factory=PromptConfig)


class AIConfig(BaseModel):
    ai: AIAgentConfig
