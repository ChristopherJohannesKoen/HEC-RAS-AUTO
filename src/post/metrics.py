from __future__ import annotations

from pathlib import Path

import pandas as pd


def compute_metrics(sections_csv: Path, run_id: str, output_root: Path = Path("outputs")) -> Path:
    out_dir = output_root / run_id / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(sections_csv)
    if df.empty:
        out_path = out_dir / "metrics.csv"
        pd.DataFrame().to_csv(out_path, index=False)
        return out_path

    max_wse_idx = df["water_level_m"].idxmax()
    max_vel_idx = df["velocity_mps"].idxmax()

    metrics = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "max_wse_m": float(df.loc[max_wse_idx, "water_level_m"]),
                "max_wse_chainage_m": float(df.loc[max_wse_idx, "chainage_m"]),
                "max_velocity_mps": float(df.loc[max_vel_idx, "velocity_mps"]),
                "max_velocity_chainage_m": float(df.loc[max_vel_idx, "chainage_m"]),
                "confluence_chainage_m": 1500.0,
                "confluence_note": "[VERIFY] Interpret local hydraulic effect using HEC-RAS profile and velocity maps.",
            }
        ]
    )
    out_path = out_dir / "metrics.csv"
    metrics.to_csv(out_path, index=False)
    return out_path
