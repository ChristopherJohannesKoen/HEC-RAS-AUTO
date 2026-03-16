#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import Point


def _detect_column(columns: list[str], candidates: list[str]) -> str:
    lowered = {c.lower(): c for c in columns}
    for cand in candidates:
        for lower, original in lowered.items():
            if cand in lower:
                return original
    raise ValueError(f"Could not detect required column from {columns}")


def _load_profile_points(transects: gpd.GeoDataFrame, profiles_dir: Path) -> gpd.GeoDataFrame:
    rows: list[dict] = []
    transects = transects.set_index("line_id", drop=False)
    for csv_path in sorted(profiles_dir.glob("*.csv")):
        line_id = csv_path.stem
        if line_id not in transects.index:
            continue
        df = pd.read_csv(csv_path)
        if df.empty:
            continue
        distance_col = _detect_column(list(df.columns), ["distance", "chainage", "station"])
        elevation_col = _detect_column(list(df.columns), ["elevation", "height", "z"])
        line = transects.loc[line_id, "geometry"]
        line_length = float(line.length)
        for idx, record in df.iterrows():
            try:
                distance = float(record[distance_col])
                elevation = float(record[elevation_col])
            except Exception:
                continue
            if distance < 0:
                continue
            point = line.interpolate(min(distance, line_length))
            rows.append(
                {
                    "line_id": line_id,
                    "source_csv": csv_path.name,
                    "sample_index": int(idx),
                    "distance_m": distance,
                    "elevation_m": elevation,
                    "geometry": Point(point.x, point.y),
                }
            )
    if not rows:
        raise SystemExit(f"No usable profile rows found in {profiles_dir}")
    return gpd.GeoDataFrame(rows, crs=transects.crs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Map exported Cape Farm Mapper elevation profiles.")
    parser.add_argument("--boundary", type=Path, required=True)
    parser.add_argument("--transects", type=Path, required=True)
    parser.add_argument("--profiles-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    boundary = gpd.read_file(args.boundary)
    transects = gpd.read_file(args.transects)
    if "line_id" not in transects.columns:
        raise SystemExit("Transects file must contain a 'line_id' property.")

    points = _load_profile_points(transects, args.profiles_dir)
    profiled_line_ids = set(points["line_id"].astype(str))
    profiled_transects = transects[transects["line_id"].astype(str).isin(profiled_line_ids)].copy()

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    points_path = out_dir / "cfm_profile_points.geojson"
    transects_path = out_dir / "cfm_transects.geojson"
    profiled_transects_path = out_dir / "cfm_profiled_transects.geojson"
    map_path = out_dir / "cfm_profile_map.png"
    summary_path = out_dir / "cfm_profile_summary.json"

    points.to_file(points_path, driver="GeoJSON")
    transects.to_file(transects_path, driver="GeoJSON")
    profiled_transects.to_file(profiled_transects_path, driver="GeoJSON")

    fig, ax = plt.subplots(figsize=(10, 10))
    boundary.boundary.plot(ax=ax, color="black", linewidth=1.2)
    transects.plot(ax=ax, color="#b9d2e6", linewidth=0.6, alpha=0.45)
    if not profiled_transects.empty:
        profiled_transects.plot(ax=ax, color="#356d9a", linewidth=1.8, alpha=0.95)
    points.plot(
        ax=ax,
        column="elevation_m",
        cmap="terrain",
        markersize=18,
        alpha=0.9,
        legend=True,
        legend_kwds={"label": "CFM Elevation (m)"},
    )
    ax.set_title("Cape Farm Mapper Dense Sampling")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(map_path, dpi=200)
    plt.close(fig)

    summary = {
        "boundary_features": int(len(boundary)),
        "transects": int(len(transects)),
        "profile_csv_files": int(len(list(args.profiles_dir.glob("*.csv")))),
        "profile_points": int(len(points)),
        "points_geojson": str(points_path),
        "transects_geojson": str(transects_path),
        "profiled_transects_geojson": str(profiled_transects_path),
        "map_png": str(map_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
