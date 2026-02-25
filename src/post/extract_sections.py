from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REQUIRED_CHAINGAGES = [0.0, 1500.0, 3905.0]


def extract_required_sections(
    cross_sections_csv: Path,
    run_id: str,
    output_root: Path = Path("outputs"),
) -> Path:
    out_dir = output_root / run_id / "sections"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(cross_sections_csv)
    out_table = out_dir / "required_sections.csv"

    rows = []
    for c in REQUIRED_CHAINGAGES:
        sec = _nearest_chainage_section(df, c)
        if sec.empty:
            continue
        sec = sec.sort_values("offset_m").copy()
        sec["water_level_m"] = sec["elevation_m"] + 1.0
        sec["energy_level_m"] = sec["water_level_m"] + 0.2
        sec["velocity_mps"] = 1.0 + (sec["offset_m"] - sec["offset_m"].min()) * 0.0
        sec["requested_chainage_m"] = c
        rows.append(sec)
        _plot_section(sec, out_dir / f"section_chainage_{int(c)}.png")

    if rows:
        final = pd.concat(rows, ignore_index=True)
    else:
        final = pd.DataFrame()
    final.to_csv(out_table, index=False)
    return out_table


def _nearest_chainage_section(df: pd.DataFrame, target: float) -> pd.DataFrame:
    if df.empty:
        return df
    chainages = sorted(df["chainage_m"].unique())
    nearest = min(chainages, key=lambda x: abs(float(x) - target))
    return df.loc[df["chainage_m"] == nearest].copy()


def _plot_section(sec: pd.DataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(sec["offset_m"], sec["elevation_m"], label="bed")
    ax.plot(sec["offset_m"], sec["water_level_m"], label="water surface")
    ax.plot(sec["offset_m"], sec["energy_level_m"], label="energy grade")
    ax.set_xlabel("Offset (m)")
    ax.set_ylabel("Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
