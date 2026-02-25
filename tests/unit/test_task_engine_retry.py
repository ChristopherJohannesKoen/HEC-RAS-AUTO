from __future__ import annotations

from pathlib import Path

from src.agent.task_engine import TaskEngine
from src.models import ExecutionPlan, TaskNode


def test_task_engine_retries_then_completes(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def flaky(_inputs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("first fail")
        return {"ok": True}

    plan = ExecutionPlan(
        run_id="r1",
        task_graph=[TaskNode(node_id="n1", tool_action="flaky", retry_rule="run-hecras")],
        retry_playbook={"run-hecras": {"max_retries": 1}},
    )
    engine = TaskEngine(run_id="r1", output_root=tmp_path, retry_budget_per_stage=0, enable_self_heal=True)
    state = engine.execute(plan=plan, action_registry={"flaky": flaky}, retry_playbook=plan.retry_playbook)
    assert state["status"] == "completed"
    assert attempts["n"] == 2
