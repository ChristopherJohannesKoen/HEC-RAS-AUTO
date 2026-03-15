#!/usr/bin/env python3
"""
Generate dense transect lines across a Cape Farm Mapper parcel.

What it does
------------
1) Fetches a Western Cape parent-farm polygon from the public ArcGIS REST layer,
   or reads a local polygon file supplied by you.
2) Projects the polygon to a local UTM CRS for meter-based spacing.
3) Generates many parallel transects clipped to the polygon.
4) Writes the transects to GeoJSON for import into Cape Farm Mapper.

Examples
--------
# Use the SG code from your farm popup
python generate_transects.py \
  --sg-code C01300000000005900000 \
  --spacing-m 10 \
  --output-dir out

# Use a local parcel polygon instead of the REST service
python generate_transects.py \
  --boundary-file elands_kloof.geojson \
  --spacing-m 5 \
  --azimuth-deg 90 \
  --output-dir out
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import requests
from pyproj import CRS
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, Polygon, shape, mapping
from shapely.ops import transform

WC_PARENT_FARM_LAYER = (
    "https://ndagis.nda.agric.za/arcgis/rest/services/Western_Cape/MapServer/25/query"
)


def utm_epsg_for_lon_lat(lon: float, lat: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def query_parent_farm_by_sg_code(sg_code: str, timeout: int = 60) -> gpd.GeoDataFrame:
    params = {
        "where": f"ID='{sg_code}'",
        "outFields": "TAG_VALUE,PARCEL_NO,MAJ_REGION,ID,AREA_HA,OBJECTID",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    resp = requests.get(WC_PARENT_FARM_LAYER, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        raise SystemExit(
            f"No parent farm found for SG code {sg_code!r}. "
            "Check the code from CFM/SG popup and try again."
        )
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    return gdf


def read_boundary(boundary_file: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(boundary_file)
    if gdf.empty:
        raise SystemExit(f"Boundary file {boundary_file} is empty.")
    if gdf.crs is None:
        raise SystemExit(
            f"Boundary file {boundary_file} has no CRS. Save it with a valid CRS first."
        )
    return gdf


def dissolve_to_single_polygon(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["_one"] = 1
    out = gdf.dissolve(by="_one", as_index=False)
    out = out.drop(columns=[c for c in out.columns if c == "_one"], errors="ignore")
    out = out.explode(index_parts=False, ignore_index=True)
    # Keep only polygonal pieces and dissolve again in case of multipart.
    out = out[out.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    out["_one"] = 1
    out = out.dissolve(by="_one", as_index=False)
    out = out.drop(columns=[c for c in out.columns if c == "_one"], errors="ignore")
    return out


def infer_azimuth_deg(poly_m) -> float:
    """Infer the long-axis azimuth from the minimum rotated rectangle."""
    rect = poly_m.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    edges = []
    for i in range(4):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        az = math.degrees(math.atan2(dy, dx))
        edges.append((length, az))
    edges.sort(reverse=True, key=lambda t: t[0])
    az = edges[0][1] % 180.0
    return az


def clip_to_polygon(geom, poly) -> List[LineString]:
    inter = geom.intersection(poly)
    if inter.is_empty:
        return []
    if isinstance(inter, LineString):
        return [inter]
    if isinstance(inter, MultiLineString):
        return [g for g in inter.geoms if isinstance(g, LineString) and not g.is_empty]
    if inter.geom_type == "GeometryCollection":
        return [g for g in inter.geoms if isinstance(g, LineString) and not g.is_empty]
    return []


def generate_parallel_transects(
    poly_m,
    spacing_m: float,
    azimuth_deg: Optional[float] = None,
    margin_m: float = 50.0,
    min_length_m: float = 10.0,
) -> List[LineString]:
    if spacing_m <= 0:
        raise ValueError("spacing_m must be > 0")

    az = infer_azimuth_deg(poly_m) if azimuth_deg is None else azimuth_deg % 180.0

    # Rotate polygon so transects become horizontal, then sweep vertically.
    rp = affinity.rotate(poly_m, -az, origin="centroid", use_radians=False)
    minx, miny, maxx, maxy = rp.bounds
    width = maxx - minx
    height = maxy - miny
    half_diag = math.hypot(width, height) / 2.0 + margin_m
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0

    lines: List[LineString] = []
    y = miny - margin_m
    idx = 1
    while y <= maxy + margin_m + 1e-9:
        base = LineString([(cx - half_diag, y), (cx + half_diag, y)])
        base = affinity.rotate(base, az, origin=poly_m.centroid, use_radians=False)
        clipped_parts = clip_to_polygon(base, poly_m)
        for part in clipped_parts:
            if part.length >= min_length_m:
                lines.append(part)
                idx += 1
        y += spacing_m
    return lines


def build_transects_gdf(lines_m: Iterable[LineString], target_crs: CRS, base_attrs: dict) -> gpd.GeoDataFrame:
    records = []
    for i, line in enumerate(lines_m, start=1):
        rec = {
            "line_id": f"TX_{i:04d}",
            "name": f"TX_{i:04d}",
            "length_m": round(float(line.length), 3),
            **base_attrs,
            "geometry": line,
        }
        records.append(rec)
    if not records:
        raise SystemExit("No transects were produced. Reduce spacing or check the boundary polygon.")
    gdf = gpd.GeoDataFrame(records, crs=target_crs)
    return gdf


def save_outputs(
    boundary_wgs84: gpd.GeoDataFrame,
    transects_wgs84: gpd.GeoDataFrame,
    output_dir: Path,
) -> Tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = output_dir / "boundary.geojson"
    transects_path = output_dir / "transects.geojson"
    manifest_path = output_dir / "manifest.csv"

    boundary_wgs84.to_file(boundary_path, driver="GeoJSON")
    transects_wgs84.to_file(transects_path, driver="GeoJSON")

    manifest = pd.DataFrame(transects_wgs84.drop(columns="geometry"))
    manifest.to_csv(manifest_path, index=False)
    return boundary_path, transects_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dense transects across a farm boundary.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--sg-code", help="Surveyor-General code, e.g. C01300000000005900000")
    src.add_argument("--boundary-file", type=Path, help="Local boundary polygon file (GeoJSON/Shapefile/KML/etc.)")
    parser.add_argument("--spacing-m", type=float, required=True, help="Transect spacing in meters, e.g. 10")
    parser.add_argument("--azimuth-deg", type=float, default=None, help="Transect azimuth in degrees. If omitted, infer from parcel shape.")
    parser.add_argument("--min-length-m", type=float, default=10.0, help="Drop clipped line parts shorter than this.")
    parser.add_argument("--margin-m", type=float, default=50.0, help="Extra sweep margin beyond the parcel bounds.")
    parser.add_argument("--output-dir", type=Path, default=Path("out"), help="Output directory")
    args = parser.parse_args()

    if args.boundary_file:
        boundary_wgs84 = read_boundary(args.boundary_file)
    else:
        boundary_wgs84 = query_parent_farm_by_sg_code(args.sg_code)

    boundary_wgs84 = dissolve_to_single_polygon(boundary_wgs84)
    boundary_wgs84 = boundary_wgs84.to_crs("EPSG:4326")

    centroid = boundary_wgs84.geometry.iloc[0].centroid
    local_epsg = utm_epsg_for_lon_lat(centroid.x, centroid.y)
    boundary_m = boundary_wgs84.to_crs(local_epsg)

    base_attrs = {}
    for col in ["TAG_VALUE", "PARCEL_NO", "MAJ_REGION", "ID", "AREA_HA"]:
        if col in boundary_m.columns:
            base_attrs[col.lower()] = boundary_m.iloc[0][col]

    lines_m = generate_parallel_transects(
        boundary_m.geometry.iloc[0],
        spacing_m=args.spacing_m,
        azimuth_deg=args.azimuth_deg,
        margin_m=args.margin_m,
        min_length_m=args.min_length_m,
    )
    transects_m = build_transects_gdf(lines_m, boundary_m.crs, base_attrs)
    transects_wgs84 = transects_m.to_crs("EPSG:4326")

    boundary_path, transects_path, manifest_path = save_outputs(
        boundary_wgs84, transects_wgs84, args.output_dir
    )

    summary = {
        "boundary_features": int(len(boundary_wgs84)),
        "transects": int(len(transects_wgs84)),
        "spacing_m": args.spacing_m,
        "azimuth_deg": (
            args.azimuth_deg
            if args.azimuth_deg is not None
            else round(infer_azimuth_deg(boundary_m.geometry.iloc[0]), 3)
        ),
        "local_crs": str(boundary_m.crs),
        "boundary_geojson": str(boundary_path),
        "transects_geojson": str(transects_path),
        "manifest_csv": str(manifest_path),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
