from __future__ import annotations

from pathlib import Path


def build_summary(run_id: str) -> str:
    return (
        f"Run `{run_id}` was processed through the supervised HEC-RAS pipeline with a manual compute gate. "
        "Outputs were auto-generated for QA, metrics, plots, and reporting."
    )


def build_qa_status(run_id: str, outputs_root: Path = Path("outputs")) -> str:
    qa_file = outputs_root / run_id / "qa" / "hydraulic_qa.md"
    if qa_file.exists():
        return qa_file.read_text(encoding="utf-8")
    return "[VERIFY] Hydraulic QA memo missing."


def scenario_notes(run_id: str) -> str:
    if run_id == "scenario_2":
        return (
            "Scenario 2 applies explicit multipliers to upstream and tributary 1:100-year flows.\n"
            "[VERIFY] Confirm multiplier values against selected climate projection source."
        )
    return "Baseline case. No scenario flow multipliers applied."
