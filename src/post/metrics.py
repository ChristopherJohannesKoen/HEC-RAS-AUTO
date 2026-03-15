from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


def compute_metrics(
    sections_csv: Path,
    run_id: str,
    floodline_geojson: Path | None = None,
    output_root: Path = Path("outputs"),
    confluence_chainage_m: float | None = 1500.0,
) -> Path:
    out_dir = output_root / run_id / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(sections_csv)
    if df.empty:
        out_path = out_dir / "metrics.csv"
        pd.DataFrame().to_csv(out_path, index=False)
        return out_path

    max_wse_idx = df["water_level_m"].idxmax()
    max_energy_idx = df["energy_level_m"].idxmax()
    max_vel_idx = df["velocity_mps"].idxmax()
    flood_extent_area_m2, flood_extent_area_ha = _compute_flood_extent_areas(floodline_geojson)

    metrics = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "max_wse_m": float(df.loc[max_wse_idx, "water_level_m"]),
                "max_wse_chainage_m": float(df.loc[max_wse_idx, "chainage_m"]),
                "max_energy_level_m": float(df.loc[max_energy_idx, "energy_level_m"]),
                "max_energy_chainage_m": float(df.loc[max_energy_idx, "chainage_m"]),
                "max_velocity_mps": float(df.loc[max_vel_idx, "velocity_mps"]),
                "max_velocity_chainage_m": float(df.loc[max_vel_idx, "chainage_m"]),
                "flood_extent_area_m2": flood_extent_area_m2,
                "flood_extent_area_ha": flood_extent_area_ha,
                "confluence_chainage_m": float(confluence_chainage_m) if confluence_chainage_m is not None else float("nan"),
                "confluence_note": (
                    "[VERIFY] Interpret local hydraulic effect using HEC-RAS profile and velocity maps."
                    if confluence_chainage_m is not None
                    else "[VERIFY] No confluence metadata was inferred for this project."
                ),
                "flood_extent_note": (
                    "[VERIFY] Flood extent envelope missing or non-polygon geometry."
                    if np.isnan(flood_extent_area_m2)
                    else "Flood extent derived from energy_flood_envelope polygon."
                ),
            }
        ]
    )
    out_path = out_dir / "metrics.csv"
    metrics.to_csv(out_path, index=False)
    return out_path


def _compute_flood_extent_areas(floodline_geojson: Path | None) -> tuple[float, float]:
    if floodline_geojson is None or not floodline_geojson.exists():
        return float("nan"), float("nan")
    try:
        gdf = gpd.read_file(floodline_geojson)
    except Exception:
        return float("nan"), float("nan")
    if gdf.empty:
        return float("nan"), float("nan")
    if "type" in gdf.columns:
        gdf = gdf[gdf["type"].astype(str) == "energy_flood_envelope"]
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if gdf.empty:
        return float("nan"), float("nan")
    area_m2 = float(gdf.geometry.area.sum())
    return area_m2, area_m2 / 10000.0
