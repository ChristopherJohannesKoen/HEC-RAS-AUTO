from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from src.common.exceptions import TerrainSamplingError
from src.geo.terrain import sample_profile
from src.models import ThresholdConfig

logger = logging.getLogger(__name__)


def complete_chainage_zero_section(
    terrain_tif: Path,
    reference_points_csv: Path = Path("data/processed/reference_points.csv"),
    raw_sections_csv: Path = Path("data/processed/cross_sections_raw.csv"),
    thresholds: ThresholdConfig | None = None,
    out_dir: Path = Path("data/processed"),
    run_output_dir: Path = Path("outputs/baseline"),
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_output_dir.mkdir(parents=True, exist_ok=True)
    (run_output_dir / "plots").mkdir(parents=True, exist_ok=True)

    tcfg = thresholds.terrain if thresholds else None
    spacing = tcfg.xs_profile_sample_spacing_m if tcfg else 2.0

    points = pd.read_csv(reference_points_csv)
    raw = pd.read_csv(raw_sections_csv)

    p1 = points.loc[points["name"] == "chainage0_right_bank_floodplain"]
    p2 = points.loc[points["name"] == "chainage0_right_bank_top"]
    if p1.empty or p2.empty:
        raise ValueError(
            "Missing required reference points in reference_points.csv: "
            "chainage0_right_bank_floodplain and chainage0_right_bank_top"
        )

    xs0 = raw.loc[raw["chainage_m"] == 0].copy()
    if xs0.empty:
        raise ValueError("No chainage 0 rows found in cross_sections_raw.csv")
    xs0 = xs0.sort_values("offset_m")

    line = LineString(
        [
            (float(p1.iloc[0]["x"]), float(p1.iloc[0]["y"])),
            (float(p2.iloc[0]["x"]), float(p2.iloc[0]["y"])),
        ]
    )

    try:
        sampled = sample_profile(terrain_tif, line, spacing_m=spacing)
    except TerrainSamplingError:
        logger.warning(
            "Terrain sampling returned NoData for chainage 0 gap; using linear fallback profile. "
            "Verify this segment manually before submission."
        )
        sampled = _fallback_profile(xs0, line.length, spacing)

    max_offset = float(xs0["offset_m"].max())

    gap = sampled.loc[sampled["valid"]].copy()
    gap["chainage_m"] = 0.0
    gap["river_station"] = float(xs0["river_station"].iloc[0])
    gap["offset_m"] = max_offset + gap["distance_m"]
    gap = gap[["chainage_m", "river_station", "offset_m", "elevation_m"]]

    completed = pd.concat([xs0, gap], ignore_index=True).sort_values("offset_m")
    completed = completed.drop_duplicates(subset=["offset_m"], keep="first")

    out_csv = out_dir / "xs_chainage_0_completed.csv"
    completed.to_csv(out_csv, index=False)

    plot_path = run_output_dir / "plots" / "xs_chainage_0_completed.png"
    _plot_completion(xs0, completed, plot_path)
    return out_csv


def _plot_completion(xs_original: pd.DataFrame, xs_completed: pd.DataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(xs_original["offset_m"], xs_original["elevation_m"], label="original", linewidth=2.0)
    ax.plot(xs_completed["offset_m"], xs_completed["elevation_m"], label="completed", linewidth=1.5)
    ax.set_xlabel("Offset (m)")
    ax.set_ylabel("Elevation (m)")
    ax.set_title("Chainage 0 Cross-Section Completion")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _fallback_profile(xs0: pd.DataFrame, gap_length_m: float, spacing: float) -> pd.DataFrame:
    distances = np.arange(0.0, max(gap_length_m, spacing) + spacing, spacing)
    if distances[-1] > gap_length_m:
        distances[-1] = gap_length_m

    xs0 = xs0.sort_values("offset_m")
    z_last = float(xs0["elevation_m"].iloc[-1])
    if len(xs0) >= 2:
        dz = float(xs0["elevation_m"].iloc[-1] - xs0["elevation_m"].iloc[-2])
        dx = float(xs0["offset_m"].iloc[-1] - xs0["offset_m"].iloc[-2])
        slope = (dz / dx) if dx != 0 else 0.0
    else:
        slope = 0.0

    rows = []
    for d in distances:
        rows.append(
            {
                "distance_m": float(d),
                "x": float("nan"),
                "y": float("nan"),
                "elevation_m": z_last + slope * float(d),
                "valid": True,
            }
        )
    return pd.DataFrame(rows)
