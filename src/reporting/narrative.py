from __future__ import annotations

import json
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
    if run_id.startswith("scenario_2") or "_scenario_2" in run_id:
        metadata = _load_scenario_metadata(run_id)
        tier = str(metadata.get("tier_id", "")).strip()
        tier_text = f" Tier `{tier}`." if tier else ""
        return (
            "Scenario 2 applies explicit multipliers to upstream and tributary 1:100-year flows "
            "to represent climate intensification forcing only (no geometry/roughness modification)."
            f"{tier_text}\n"
            "Recommended interpretation: evaluate max WSE, max velocity, max energy, and flood-extent "
            "change relative to baseline and discuss confluence response near chainage 1500 m."
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


def _load_scenario_metadata(run_id: str) -> dict[str, object]:
    path = Path("runs") / run_id / "flow" / "scenario_metadata.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
