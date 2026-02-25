from __future__ import annotations

from pathlib import Path


def build_summary(run_id: str) -> str:
    autopilot_state = Path("outputs") / run_id / "autopilot" / "state.json"
    if autopilot_state.exists():
        return (
            f"Run `{run_id}` was processed in unattended autopilot mode with COM-driven HEC-RAS compute. "
            "Outputs were auto-generated for QA, metrics, plots, CAD export, and reporting."
        )
    return (
        f"Run `{run_id}` was processed through the supervised HEC-RAS pipeline. "
        "Outputs were auto-generated for QA, metrics, plots, and reporting."
    )


def build_qa_status(run_id: str, outputs_root: Path = Path("outputs")) -> str:
    qa_file = outputs_root / run_id / "qa" / "hydraulic_qa.md"
    if qa_file.exists():
        return qa_file.read_text(encoding="utf-8")
    return "[VERIFY] Hydraulic QA memo missing."


def scenario_notes(run_id: str) -> str:
    if run_id.startswith("scenario_2"):
        return (
            "Scenario 2 applies explicit multipliers to upstream and tributary 1:100-year flows.\n"
            "[VERIFY] Confirm multiplier values against selected climate projection source."
        )
    if run_id.startswith("scenario_1"):
        return (
            "Scenario 1 represents right-bank floodplain settlement effects with changed conveyance/storage.\n"
            "[VERIFY][CITE] Confirm roughness and effective-flow assumptions."
        )
    if run_id.startswith("scenario_3"):
        return (
            "Scenario 3 represents confluence-area development and platform leveling impacts.\n"
            "[VERIFY][CITE] Confirm parameter choices for confluence hydraulics."
        )
    if run_id.startswith("scenario_4"):
        return (
            "Scenario 4 represents floodplain rehabilitation and increased riparian retardance.\n"
            "[VERIFY][CITE] Confirm literature-supported roughness adjustments."
        )
    return "Baseline case. No scenario flow multipliers applied."
