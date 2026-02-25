from __future__ import annotations

from src.agent.prompt_compiler import PromptCompiler
from src.models import AIAgentConfig


def test_prompt_compiler_builds_spec_and_plan() -> None:
    cfg = AIAgentConfig()
    compiler = PromptCompiler(cfg, max_retries=1)
    spec = compiler.compile_job_spec(
        prompt_text=(
            "Build HEC-RAS baseline model for Meerlustkloof and run Scenario 2 climate intensification. "
            "Use Manning n channel = 0.04 and floodplain = 0.06."
        ),
        run_id="baseline",
        source="ref",
        assigned_scenario_override="scenario_2",
        strict=False,
    )
    assert spec.project_name == "Meerlustkloof"
    assert spec.assigned_scenario == "scenario_2"
    assert spec.roughness_rules["channel_n"] == 0.04
    plan = compiler.compile_execution_plan(spec, run_id="baseline")
    assert plan.run_id == "baseline"
    assert len(plan.task_graph) >= 3
