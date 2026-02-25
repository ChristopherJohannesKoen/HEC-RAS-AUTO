from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.models import AIAgentConfig, AutopilotIssue, RunState, RunStepState


class OpenAIAdvisor:
    def __init__(self, config: AIAgentConfig) -> None:
        self.config = config
        self.enabled = bool(os.getenv(config.api_key_env))
        self._client = None
        self.last_response_id: str | None = None
        self.last_prompt_type: str | None = None
        if self.enabled:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=os.getenv(config.api_key_env))
            except Exception:
                self.enabled = False

    def anomaly_triage(self, context: str) -> str:
        self.last_prompt_type = "anomaly_triage"
        self.last_response_id = None
        if not self.enabled or self._client is None:
            return "AI disabled or unavailable; using deterministic guardrails."
        try:
            resp = self._client.responses.create(
                model=self.config.model,
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                input=[
                    {"role": "system", "content": self.config.prompts.anomaly_triage},
                    {"role": "user", "content": context},
                ],
            )
            self.last_response_id = getattr(resp, "id", None)
            return getattr(resp, "output_text", "") or "No AI output."
        except Exception as exc:
            return f"AI triage unavailable: {exc}"

    def report_reasoning(self, context: str) -> str:
        self.last_prompt_type = "report_reasoning"
        self.last_response_id = None
        if not self.enabled or self._client is None:
            return "[VERIFY] AI narrative not enabled; add manual interpretation."
        try:
            resp = self._client.responses.create(
                model=self.config.model,
                temperature=self.config.temperature,
                max_output_tokens=self.config.max_tokens,
                input=[
                    {"role": "system", "content": self.config.prompts.report_reasoning},
                    {"role": "user", "content": context},
                ],
            )
            self.last_response_id = getattr(resp, "id", None)
            return getattr(resp, "output_text", "") or "[VERIFY] Empty AI narrative."
        except Exception as exc:
            return f"[VERIFY] AI narrative unavailable: {exc}"


class AutopilotOrchestrator:
    def __init__(self, run_id: str, output_root: Path = Path("outputs")) -> None:
        self.run_id = run_id
        self.output_root = output_root
        self.autopilot_dir = output_root / run_id / "autopilot"
        self.autopilot_dir.mkdir(parents=True, exist_ok=True)
        self.state = RunState(run_id=run_id)
        self.issues: list[AutopilotIssue] = []
        self._actions_log = self.autopilot_dir / "actions.log"

    def step(self, name: str, fn: Callable[[], dict | str | Path | None]) -> dict | str | Path | None:
        step = RunStepState(step=name, status="running", started_at=datetime.utcnow())
        self.state.steps.append(step)
        self._log(f"START {name}")
        try:
            result = fn()
            step.status = "completed"
            step.finished_at = datetime.utcnow()
            self._log(f"DONE {name}")
            self._persist_state()
            return result
        except Exception as exc:
            step.status = "failed"
            step.finished_at = datetime.utcnow()
            step.notes = str(exc)
            issue = AutopilotIssue(
                severity="critical",
                stage=name,
                message=str(exc),
                terminal=True,
            )
            self.issues.append(issue)
            self.state.status = "failed"
            self.state.finished_at = datetime.utcnow()
            self._log(f"FAIL {name}: {exc}")
            self._persist_state()
            self._write_fail_report()
            raise

    def set_artifact(self, key: str, value: str | Path) -> None:
        self.state.artifacts[key] = str(value)
        self._persist_state()

    def complete(self) -> None:
        self.state.status = "completed"
        self.state.finished_at = datetime.utcnow()
        self._persist_state()
        self._log("RUN COMPLETED")

    def log_action(self, message: str) -> None:
        self._log(f"ACTION {message}")

    def _write_fail_report(self) -> None:
        fail_path = self.autopilot_dir / "fail_report.json"
        payload = {
            "run_id": self.run_id,
            "status": "failed",
            "issues": [i.model_dump(mode="json") for i in self.issues],
            "artifacts": self.state.artifacts,
        }
        fail_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _persist_state(self) -> None:
        state_path = self.autopilot_dir / "state.json"
        state_path.write_text(self.state.model_dump_json(indent=2), encoding="utf-8")

    def _log(self, line: str) -> None:
        ts = datetime.utcnow().isoformat()
        with self._actions_log.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {line}\n")
