from __future__ import annotations

import json
import os
import re
from pathlib import Path

from src.models import AIAgentConfig, ExecutionPlan, PromptJobSpec, TaskNode


class PromptCompiler:
    def __init__(self, ai_config: AIAgentConfig, max_retries: int = 2) -> None:
        self.ai_config = ai_config
        self.max_retries = max_retries
        self._client = self._build_client()
        self.last_model_response_id: str | None = None

    def compile_job_spec(
        self,
        prompt_text: str,
        run_id: str,
        source: str,
        assigned_scenario_override: str | None = None,
        strict: bool = True,
    ) -> PromptJobSpec:
        spec = self._deterministic_parse(prompt_text, run_id=run_id, source=source)
        if assigned_scenario_override:
            spec.assigned_scenario = assigned_scenario_override
        if strict and spec.parser_confidence < 0.45 and self._client is not None:
            spec = self._llm_repair(prompt_text, spec)
        if strict and spec.parser_confidence < 0.35:
            raise ValueError(
                f"Prompt parse confidence too low ({spec.parser_confidence:.2f}). "
                "Provide a clearer assignment prompt or pass explicit scenario."
            )
        return spec

    def compile_execution_plan(self, spec: PromptJobSpec, run_id: str) -> ExecutionPlan:
        scenario_id = spec.assigned_scenario.lower()
        if scenario_id not in {"scenario_1", "scenario_2", "scenario_3", "scenario_4"}:
            scenario_id = "scenario_2"

        task_graph = [
            TaskNode(
                node_id="baseline_autopilot",
                tool_action="run_baseline_autopilot",
                inputs={"source": spec.source_paths[0] if spec.source_paths else "ref", "run_id": run_id},
                outputs=[f"outputs/{run_id}/qa/hydraulic_qa.md"],
                retry_rule="run-hecras",
            ),
            TaskNode(
                node_id="scenario_payload",
                tool_action="prepare_assigned_scenario_payload",
                inputs={"base_run_id": run_id, "scenario_id": scenario_id},
                outputs=[f"runs/{scenario_id}/flow/steady_flow.json"],
                retry_rule="ingest",
            ),
            TaskNode(
                node_id="scenario_execute",
                tool_action="execute_assigned_scenario",
                inputs={"base_run_id": run_id, "scenario_id": scenario_id},
                outputs=[f"outputs/{scenario_id}/qa/hydraulic_qa.md"],
                retry_rule="run-hecras",
            ),
            TaskNode(
                node_id="scenario_compare",
                tool_action="compare_baseline_scenario",
                inputs={"base_run_id": run_id, "scenario_id": scenario_id},
                outputs=[f"outputs/{scenario_id}/comparison/comparison_table.csv"],
                retry_rule="analyze",
            ),
            TaskNode(
                node_id="citations",
                tool_action="collect_citations",
                inputs={"run_id": run_id, "scenario_id": scenario_id, "objective": spec.objective},
                outputs=[f"outputs/{run_id}/agent/citations.json"],
                retry_rule="analyze",
                terminal_on_fail=False,
            ),
            TaskNode(
                node_id="build_submission_pack",
                tool_action="build_submission_pack",
                inputs={"base_run_id": run_id, "scenario_id": scenario_id},
                outputs=[f"outputs/{run_id}/submission/manifest.json"],
                retry_rule="analyze",
            ),
        ]
        expected = [o for n in task_graph for o in n.outputs]
        return ExecutionPlan(
            run_id=run_id,
            task_graph=task_graph,
            stop_conditions=[
                "geometry_qa_error",
                "hecras_compute_failure",
                "missing_plan_hdf",
                "hydraulic_qa_error",
            ],
            retry_playbook={
                "doctor": {"max_retries": 1},
                "ingest": {"max_retries": 1},
                "complete-xs": {"max_retries": 1},
                "build-geometry": {"max_retries": 1},
                "run-hecras": {"max_retries": 1},
                "import-results": {"max_retries": 1},
                "analyze": {"max_retries": 1},
            },
            expected_artifacts=expected,
            acceptance_checks=[
                "baseline_hydraulic_qa_exists",
                "scenario_hydraulic_qa_exists",
                "comparison_table_exists",
                "submission_manifest_exists",
            ],
        )

    def persist_plan_artifacts(
        self,
        run_id: str,
        spec: PromptJobSpec,
        plan: ExecutionPlan,
        output_root: Path = Path("outputs"),
    ) -> tuple[Path, Path]:
        agent_dir = output_root / run_id / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        spec_path = agent_dir / "prompt_parse.json"
        plan_path = agent_dir / "compiled_plan.json"
        spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return spec_path, plan_path

    def _deterministic_parse(self, prompt_text: str, run_id: str, source: str) -> PromptJobSpec:
        text = prompt_text or ""
        lower = text.lower()
        scenario = self._extract_scenario(lower)
        n_channel = self._extract_value(lower, r"manning[^=\n]*channel[^=\n]*=\s*([0-9]*\.?[0-9]+)")
        n_flood = self._extract_value(lower, r"floodplain[^=\n]*=\s*([0-9]*\.?[0-9]+)")
        q_up = self._extract_value(lower, r"flood peak[^0-9]*([0-9]{2,5}(?:\.[0-9]+)?)")
        slope_down = self._extract_value(lower, r"downstream[^=\n]*s0[^=\n]*=\s*([0-9eE\-\.\sx]+)")

        confidence = 0.2
        if "hec-ras" in lower:
            confidence += 0.1
        if scenario:
            confidence += 0.2
        if n_channel is not None and n_flood is not None:
            confidence += 0.2
        if "baseline" in lower:
            confidence += 0.1
        if "cross section" in lower:
            confidence += 0.1
        if "floodline" in lower:
            confidence += 0.1

        constraints = {
            "run_id": run_id,
            "strict": True,
            "mode": "bounded-self-heal",
        }
        bc = {}
        if q_up is not None:
            bc["upstream_q_100"] = q_up
        if slope_down is not None:
            bc["downstream_s0"] = slope_down
        roughness = {}
        if n_channel is not None:
            roughness["channel_n"] = n_channel
        if n_flood is not None:
            roughness["floodplain_n"] = n_flood

        required_outputs = [
            "completed_chainage0_cross_section",
            "hec_ras_geometry_and_flow",
            "baseline_metrics",
            "scenario_comparison",
            "submission_pack",
        ]

        return PromptJobSpec(
            project_name=self._guess_project_name(text),
            objective="Automate hydraulic assignment from prompt to submission pack.",
            baseline_required=True,
            assigned_scenario=scenario or "scenario_2",
            required_outputs=required_outputs,
            constraints=constraints,
            boundary_conditions=bc,
            roughness_rules=roughness,
            qa_policy="strict",
            evidence_policy="web-assisted",
            source_paths=[source],
            raw_prompt=text,
            parser_confidence=min(confidence, 0.95),
        )

    def _llm_repair(self, prompt_text: str, deterministic_spec: PromptJobSpec) -> PromptJobSpec:
        if self._client is None:
            return deterministic_spec
        schema_hint = {
            "project_name": "string",
            "objective": "string",
            "baseline_required": "bool",
            "assigned_scenario": "scenario_1|scenario_2|scenario_3|scenario_4",
            "required_outputs": ["string"],
            "constraints": {},
            "boundary_conditions": {},
            "roughness_rules": {},
            "qa_policy": "string",
            "evidence_policy": "string",
            "source_paths": ["string"],
            "raw_prompt": "string",
            "parser_confidence": "float 0..1",
        }
        msg = (
            f"Current parsed spec:\n{deterministic_spec.model_dump_json(indent=2)}\n\n"
            f"Prompt:\n{prompt_text}\n\n"
            f"Return strict JSON only, schema:\n{json.dumps(schema_hint)}"
        )
        try:
            resp = self._client.responses.create(
                model=self.ai_config.model,
                temperature=self.ai_config.temperature,
                max_output_tokens=self.ai_config.max_tokens,
                input=[
                    {"role": "system", "content": self.ai_config.prompts.prompt_compiler.repair_job_spec},
                    {"role": "user", "content": msg},
                ],
            )
            self.last_model_response_id = getattr(resp, "id", None)
            raw = getattr(resp, "output_text", "") or ""
            payload = self._extract_json(raw)
            repaired = PromptJobSpec.model_validate(payload)
            if repaired.parser_confidence < deterministic_spec.parser_confidence:
                return deterministic_spec
            return repaired
        except Exception:
            return deterministic_spec

    def _build_client(self):
        try:
            api_key = os.getenv(self.ai_config.api_key_env)
            if not api_key:
                return None
            from openai import OpenAI

            return OpenAI(api_key=api_key)
        except Exception:
            return None

    @staticmethod
    def _extract_json(text: str) -> dict:
        if not text.strip():
            return {}
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        snippet = text[start : end + 1]
        return json.loads(snippet)

    @staticmethod
    def _extract_scenario(lower_text: str) -> str | None:
        mapping = {
            "scenario 1": "scenario_1",
            "scenario 2": "scenario_2",
            "scenario 3": "scenario_3",
            "scenario 4": "scenario_4",
            "climate intensification": "scenario_2",
            "informal settlement": "scenario_1",
            "riverside tourism": "scenario_3",
            "rehabilitation": "scenario_4",
        }
        for key, value in mapping.items():
            if key in lower_text:
                return value
        return None

    @staticmethod
    def _extract_value(text: str, pattern: str) -> float | None:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m is None:
            return None
        try:
            return float(str(m.group(1)).replace("x 10-", "e-").replace(" ", ""))
        except ValueError:
            return None

    @staticmethod
    def _guess_project_name(text: str) -> str:
        if "meerlustkloof" in text.lower():
            return "Meerlustkloof"
        return "Hydraulic Assignment"
