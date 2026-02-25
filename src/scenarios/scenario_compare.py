from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def compare_runs(base_run: str, other_run: str, outputs_root: Path = Path("outputs")) -> tuple[Path, Path]:
    base_metrics = outputs_root / base_run / "tables" / "metrics.csv"
    other_metrics = outputs_root / other_run / "tables" / "metrics.csv"
    if not base_metrics.exists() or not other_metrics.exists():
        raise FileNotFoundError("Missing metrics.csv for baseline or scenario run.")

    b = pd.read_csv(base_metrics)
    o = pd.read_csv(other_metrics)
    if b.empty or o.empty:
        raise ValueError("Metrics missing content for comparison.")

    row_b = b.iloc[0]
    row_o = o.iloc[0]
    comp = pd.DataFrame(
        [
            {"metric": "max_wse_m", "baseline": row_b["max_wse_m"], "scenario": row_o["max_wse_m"], "delta": row_o["max_wse_m"] - row_b["max_wse_m"]},
            {
                "metric": "max_velocity_mps",
                "baseline": row_b["max_velocity_mps"],
                "scenario": row_o["max_velocity_mps"],
                "delta": row_o["max_velocity_mps"] - row_b["max_velocity_mps"],
            },
        ]
    )
    out_dir = outputs_root / other_run / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / "comparison_table.csv"
    comp.to_csv(table_path, index=False)

    profile_path = out_dir / "overlay_longitudinal_profile.png"
    _plot_overlay(base_run, other_run, outputs_root, profile_path)
    return table_path, profile_path


def _plot_overlay(base_run: str, other_run: str, outputs_root: Path, out_path: Path) -> None:
    base_sections = outputs_root / base_run / "sections" / "required_sections.csv"
    other_sections = outputs_root / other_run / "sections" / "required_sections.csv"
    b = pd.read_csv(base_sections)
    o = pd.read_csv(other_sections)
    bg = b.groupby("chainage_m", as_index=False).agg(wse=("water_level_m", "max")).sort_values("chainage_m")
    og = o.groupby("chainage_m", as_index=False).agg(wse=("water_level_m", "max")).sort_values("chainage_m")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(bg["chainage_m"], bg["wse"], label=f"{base_run} WSE")
    ax.plot(og["chainage_m"], og["wse"], label=f"{other_run} WSE")
    ax.set_xlabel("Chainage (m)")
    ax.set_ylabel("Water Surface Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
