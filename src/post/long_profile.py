from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


def build_longitudinal_profile(
    sections_csv: Path,
    run_id: str,
    output_root: Path = Path("outputs"),
) -> Path:
    out_dir = output_root / run_id / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(sections_csv)
    if df.empty:
        raise ValueError(f"No section data found: {sections_csv}")

    grouped = (
        df.groupby("chainage_m", as_index=False)
        .agg(bed_min=("elevation_m", "min"), wse=("water_level_m", "max"), eg=("energy_level_m", "max"))
        .sort_values("chainage_m")
    )

    out_png = out_dir / "longitudinal_profile.png"
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(grouped["chainage_m"], grouped["bed_min"], label="Bed min")
    ax.plot(grouped["chainage_m"], grouped["wse"], label="Water surface")
    ax.plot(grouped["chainage_m"], grouped["eg"], label="Energy grade")
    ax.set_xlabel("Chainage (m)")
    ax.set_ylabel("Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return out_png
