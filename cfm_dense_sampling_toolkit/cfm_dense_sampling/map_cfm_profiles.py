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
from pyproj import CRS
from shapely.geometry import LineString
from shapely.geometry import Point

try:
    import contextily as ctx
except Exception:
    ctx = None


def _detect_column(columns: list[str], candidates: list[str]) -> str:
    lowered = {c.lower(): c for c in columns}
    for cand in candidates:
        for lower, original in lowered.items():
            if cand in lower:
                return original
    raise ValueError(f"Could not detect required column from {columns}")


def _utm_epsg_for_lon_lat(lon: float, lat: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def _metric_crs_for_gdf(gdf: gpd.GeoDataFrame) -> CRS:
    geom = gdf.to_crs(epsg=4326).geometry
    union = geom.union_all() if hasattr(geom, "union_all") else geom.unary_union
    centroid = union.centroid
    return CRS.from_epsg(_utm_epsg_for_lon_lat(centroid.x, centroid.y))


def _resolve_profile_matches(transects: gpd.GeoDataFrame, profiles_dir: Path) -> list[dict]:
    metric_crs = _metric_crs_for_gdf(transects)
    transects_metric = transects.to_crs(metric_crs).set_index("line_id", drop=False)
    available_ids = set(transects_metric.index.astype(str))
    matches: list[dict] = []

    for csv_path in sorted(profiles_dir.glob("*.csv")):
        df = pd.read_csv(csv_path)
        if df.empty:
            continue
        lon_col = _detect_column(list(df.columns), ["lon", "longitude"])
        lat_col = _detect_column(list(df.columns), ["lat", "latitude"])
        distance_col = _detect_column(list(df.columns), ["distance", "chainage", "station"])
        line_points = [Point(float(r[lon_col]), float(r[lat_col])) for _, r in df.iterrows()]
        if len(line_points) < 2:
            continue
        profile_line = LineString(line_points)
        profile_line_metric = gpd.GeoSeries([profile_line], crs=transects.crs).to_crs(metric_crs).iloc[0]
        file_id = csv_path.stem

        candidate_ids = list(available_ids) or list(transects_metric.index.astype(str))
        if file_id in candidate_ids:
            candidate_ids = [file_id] + [cid for cid in candidate_ids if cid != file_id]

        best_id = None
        best_score = float("inf")
        best_length = None
        for candidate_id in candidate_ids:
            geom = transects_metric.loc[candidate_id, "geometry"]
            score = geom.hausdorff_distance(profile_line_metric)
            if score < best_score:
                best_id = candidate_id
                best_score = float(score)
                best_length = float(transects_metric.loc[candidate_id, "length_m"])
        if best_id is None:
            continue
        if best_id in available_ids:
            available_ids.remove(best_id)
        matches.append(
            {
                "source_csv": csv_path.name,
                "source_stem": file_id,
                "matched_line_id": str(best_id),
                "match_hausdorff_m": best_score,
                "csv_length_m": float(df.iloc[-1][distance_col]),
                "transect_length_m": best_length,
                "length_diff_m": float(df.iloc[-1][distance_col]) - float(best_length),
            }
        )
    return matches


def _load_profile_points(
    transects: gpd.GeoDataFrame, profiles_dir: Path, matches: list[dict]
) -> gpd.GeoDataFrame:
    rows: list[dict] = []
    transects = transects.set_index("line_id", drop=False)
    match_map = {m["source_csv"]: m for m in matches}
    for csv_path in sorted(profiles_dir.glob("*.csv")):
        match = match_map.get(csv_path.name)
        if not match:
            continue
        line_id = match["matched_line_id"]
        df = pd.read_csv(csv_path)
        if df.empty:
            continue
        distance_col = _detect_column(list(df.columns), ["distance", "chainage", "station"])
        elevation_col = _detect_column(list(df.columns), ["elevation", "height", "z"])
        lon_col = None
        lat_col = None
        try:
            lon_col = _detect_column(list(df.columns), ["lon", "longitude"])
            lat_col = _detect_column(list(df.columns), ["lat", "latitude"])
        except Exception:
            lon_col = None
            lat_col = None
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
            if lon_col and lat_col:
                try:
                    point = Point(float(record[lon_col]), float(record[lat_col]))
                except Exception:
                    point = line.interpolate(min(distance, line_length))
            else:
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

    matches = _resolve_profile_matches(transects, args.profiles_dir)
    points = _load_profile_points(transects, args.profiles_dir, matches)
    profiled_line_ids = set(points["line_id"].astype(str))
    profiled_transects = transects[transects["line_id"].astype(str).isin(profiled_line_ids)].copy()

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    points_path = out_dir / "cfm_profile_points.geojson"
    transects_path = out_dir / "cfm_transects.geojson"
    profiled_transects_path = out_dir / "cfm_profiled_transects.geojson"
    match_manifest_path = out_dir / "cfm_profile_match_manifest.csv"
    map_path = out_dir / "cfm_profile_map.png"
    summary_path = out_dir / "cfm_profile_summary.json"

    points.to_file(points_path, driver="GeoJSON")
    transects.to_file(transects_path, driver="GeoJSON")
    profiled_transects.to_file(profiled_transects_path, driver="GeoJSON")
    pd.DataFrame(matches).to_csv(match_manifest_path, index=False)

    fig, ax = plt.subplots(figsize=(10, 10))
    plot_boundary = boundary
    plot_transects = transects
    plot_profiled = profiled_transects
    plot_points = points
    use_basemap = ctx is not None
    if use_basemap:
        plot_boundary = boundary.to_crs(epsg=3857)
        plot_transects = transects.to_crs(epsg=3857)
        plot_profiled = profiled_transects.to_crs(epsg=3857)
        plot_points = points.to_crs(epsg=3857)
    plot_boundary.boundary.plot(ax=ax, color="black", linewidth=1.2)
    plot_transects.plot(ax=ax, color="#b9d2e6", linewidth=0.6, alpha=0.1)
    if not plot_profiled.empty:
        plot_profiled.plot(ax=ax, color="#356d9a", linewidth=1.8, alpha=0.1)
    plot_points.plot(
        ax=ax,
        column="elevation_m",
        cmap="terrain",
        markersize=20,
        alpha=0.95,
        legend=True,
        legend_kwds={"label": "CFM Elevation (m)"},
    )
    if use_basemap:
        ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery, attribution=False, reset_extent=False)
    ax.set_title("Cape Farm Mapper Dense Sampling")
    ax.set_xlabel("Easting" if use_basemap else "Longitude")
    ax.set_ylabel("Northing" if use_basemap else "Latitude")
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
        "profile_match_manifest_csv": str(match_manifest_path),
        "match_hausdorff_m_max": float(pd.DataFrame(matches)["match_hausdorff_m"].max()) if matches else None,
        "match_hausdorff_m_mean": float(pd.DataFrame(matches)["match_hausdorff_m"].mean()) if matches else None,
        "map_png": str(map_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
