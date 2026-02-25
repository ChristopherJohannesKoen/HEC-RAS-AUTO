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

    station_hints = _derive_station_hints()
    payload = {
        "run_id": run_id,
        "scenario_id": scenario.scenario_id if scenario else "baseline",
        "upstream_flow_cms": hydraulics.upstream_q_100 * up_mult,
        "tributary_flow_cms": hydraulics.tributary_q_100 * tr_mult,
        "tributary_chainage_m": hydraulics.tributary_chainage_m,
        "upstream_station_hint": station_hints.get("upstream_station_hint"),
        "tributary_station_hint": station_hints.get("tributary_station_hint"),
        "downstream_station_hint": station_hints.get("downstream_station_hint"),
        "upstream_normal_depth_slope": hydraulics.upstream_normal_depth_slope,
        "downstream_normal_depth_slope": hydraulics.downstream_normal_depth_slope,
    }

    json_path = target / "steady_flow.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = target / "steady_flow.csv"
    pd.DataFrame([payload]).to_csv(csv_path, index=False)
    return json_path, csv_path


def _derive_station_hints(path: Path = Path("data/processed/cross_sections_raw.csv")) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if df.empty or "river_station" not in df.columns:
        return {}

    station_map = (
        df[["chainage_m", "river_station"]]
        .drop_duplicates()
        .sort_values("chainage_m")
        .reset_index(drop=True)
    )
    out: dict[str, float] = {}
    out["upstream_station_hint"] = float(station_map["river_station"].max())
    out["downstream_station_hint"] = float(station_map["river_station"].min())

    # Assignment-specific confluence chainage is 1500m; use nearest chainage station.
    station_map["absdiff"] = (station_map["chainage_m"] - 1500.0).abs()
    row = station_map.sort_values("absdiff").iloc[0]
    out["tributary_station_hint"] = float(row["river_station"])
    return out
