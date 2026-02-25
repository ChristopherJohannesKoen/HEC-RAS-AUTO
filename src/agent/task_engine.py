from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.models import AgentDecision, ExecutionPlan


ActionCallable = Callable[[dict[str, Any]], dict[str, Any] | None]


class TaskEngine:
    def __init__(
        self,
        run_id: str,
        output_root: Path = Path("outputs"),
        retry_budget_per_stage: int = 1,
        enable_self_heal: bool = True,
    ) -> None:
        self.run_id = run_id
        self.output_root = output_root
        self.retry_budget_per_stage = retry_budget_per_stage
        self.enable_self_heal = enable_self_heal
        self.agent_dir = output_root / run_id / "agent"
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_path = self.agent_dir / "decisions.jsonl"
        self.state_path = self.agent_dir / "task_state.json"
        self._state: dict[str, Any] = {
            "run_id": run_id,
            "status": "running",
            "updated_at": datetime.utcnow().isoformat(),
            "nodes": {},
            "artifacts": {},
        }

    def execute(
        self,
        plan: ExecutionPlan,
        action_registry: dict[str, ActionCallable],
        retry_playbook: dict[str, dict[str, Any]] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        if resume and self.state_path.exists():
            self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
        retry_playbook = retry_playbook or {}

        for node in plan.task_graph:
            existing = self._state["nodes"].get(node.node_id, {})
            if existing.get("status") == "completed":
                continue

            action = action_registry.get(node.tool_action)
            if action is None:
                self._fail_node(node.node_id, f"No action registered for {node.tool_action}")
                raise RuntimeError(f"Unknown task action: {node.tool_action}")

            node_retry_budget = self.retry_budget_per_stage
            if node.retry_rule and node.retry_rule in retry_playbook:
                node_retry_budget = int(retry_playbook[node.retry_rule].get("max_retries", node_retry_budget))

            attempts = 0
            while True:
                attempts += 1
                self._log_decision(
                    AgentDecision(
                        stage=node.node_id,
                        decision_type="task_start" if attempts == 1 else "task_retry",
                        rationale=f"Executing task action={node.tool_action}, attempt={attempts}",
                    )
                )
                self._state["nodes"][node.node_id] = {
                    "status": "running",
                    "attempt": attempts,
                    "action": node.tool_action,
                    "updated_at": datetime.utcnow().isoformat(),
                }
                self._persist_state()
                try:
                    result = action(node.inputs) or {}
                    self._state["nodes"][node.node_id] = {
                        "status": "completed",
                        "attempt": attempts,
                        "action": node.tool_action,
                        "result": result,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    self._persist_state()
                    break
                except Exception as exc:
                    can_retry = self.enable_self_heal and attempts <= node_retry_budget
                    self._log_decision(
                        AgentDecision(
                            stage=node.node_id,
                            decision_type="task_error",
                            rationale=str(exc),
                            evidence_refs=[],
                        )
                    )
                    if can_retry:
                        self._state["nodes"][node.node_id] = {
                            "status": "retrying",
                            "attempt": attempts,
                            "action": node.tool_action,
                            "error": str(exc),
                            "updated_at": datetime.utcnow().isoformat(),
                        }
                        self._persist_state()
                        time.sleep(1.0)
                        continue

                    self._fail_node(node.node_id, str(exc))
                    if node.terminal_on_fail:
                        raise RuntimeError(f"Task '{node.node_id}' failed: {exc}") from exc
                    break

        self._state["status"] = "completed"
        self._state["updated_at"] = datetime.utcnow().isoformat()
        self._persist_state()
        return self._state

    def _fail_node(self, node_id: str, error: str) -> None:
        self._state["nodes"][node_id] = {
            "status": "failed",
            "error": error,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._state["status"] = "failed"
        self._state["updated_at"] = datetime.utcnow().isoformat()
        self._persist_state()

    def _persist_state(self) -> None:
        self.state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _log_decision(self, decision: AgentDecision) -> None:
        with self.decisions_path.open("a", encoding="utf-8") as f:
            f.write(decision.model_dump_json() + "\n")
