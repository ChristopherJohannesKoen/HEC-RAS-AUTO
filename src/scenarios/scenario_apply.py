from __future__ import annotations

from pathlib import Path

from src.models import HydraulicsConfig
from src.models.scenario import ScenarioSpec
from src.ras.flow_writer import write_steady_flow_payload


def apply_scenario_flow(
    hydraulics: HydraulicsConfig,
    scenario: ScenarioSpec,
    run_id: str,
    runs_root: Path = Path("runs"),
) -> tuple[Path, Path]:
    return write_steady_flow_payload(hydraulics, run_id=run_id, scenario=scenario, run_dir=runs_root)
