from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.models import HydraulicsConfig
from src.models.scenario import ScenarioSpec


def write_steady_flow_payload(
    hydraulics: HydraulicsConfig,
    run_id: str,
    scenario: ScenarioSpec | None = None,
    run_dir: Path = Path("runs"),
) -> tuple[Path, Path]:
    target = run_dir / run_id / "flow"
    target.mkdir(parents=True, exist_ok=True)
    up_mult = scenario.flow_multiplier_upstream if scenario else 1.0
    tr_mult = scenario.flow_multiplier_tributary if scenario else 1.0

    payload = {
        "run_id": run_id,
        "scenario_id": scenario.scenario_id if scenario else "baseline",
        "upstream_flow_cms": hydraulics.upstream_q_100 * up_mult,
        "tributary_flow_cms": hydraulics.tributary_q_100 * tr_mult,
        "tributary_chainage_m": hydraulics.tributary_chainage_m,
        "upstream_normal_depth_slope": hydraulics.upstream_normal_depth_slope,
        "downstream_normal_depth_slope": hydraulics.downstream_normal_depth_slope,
    }

    json_path = target / "steady_flow.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = target / "steady_flow.csv"
    pd.DataFrame([payload]).to_csv(csv_path, index=False)
    return json_path, csv_path
