#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import LineString, Point


def _utm_epsg_for_lon_lat(lon: float, lat: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def _read_kmz_point(path: Path) -> tuple[float, float]:
    with zipfile.ZipFile(path) as zf:
        kml_name = next((name for name in zf.namelist() if name.lower().endswith(".kml")), None)
        if not kml_name:
            raise ValueError(f"No KML found inside KMZ: {path}")
        text = zf.read(kml_name).decode("utf-8", errors="ignore")
    start = text.find("<coordinates>")
    end = text.find("</coordinates>", start + 1)
    if start < 0 or end < 0:
        raise ValueError(f"Could not find coordinates in {path}")
    raw = text[start + len("<coordinates>") : end].strip()
    lon, lat, *_rest = raw.split(",")
    return float(lon), float(lat)


def _line_azimuth_deg(line: LineString) -> float:
    (x1, y1), (x2, y2) = list(line.coords)
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a geographic corridor boundary from KMZ anchor points."
    )
    parser.add_argument("--station-kmz", type=Path, required=True)
    parser.add_argument("--floodplain-kmz", type=Path, required=True)
    parser.add_argument("--top-kmz", type=Path, required=True)
    parser.add_argument("--buffer-m", type=float, default=250.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    station_lonlat = _read_kmz_point(args.station_kmz)
    floodplain_lonlat = _read_kmz_point(args.floodplain_kmz)
    top_lonlat = _read_kmz_point(args.top_kmz)

    chainage0_mid = (
        (floodplain_lonlat[0] + top_lonlat[0]) / 2.0,
        (floodplain_lonlat[1] + top_lonlat[1]) / 2.0,
    )
    wgs84 = CRS.from_epsg(4326)
    local_epsg = _utm_epsg_for_lon_lat(chainage0_mid[0], chainage0_mid[1])

    anchors = gpd.GeoDataFrame(
        [
            {"name": "station_3905", "geometry": Point(station_lonlat)},
            {"name": "chainage_0_right_bank_floodplain", "geometry": Point(floodplain_lonlat)},
            {"name": "chainage_0_right_bank_top", "geometry": Point(top_lonlat)},
            {"name": "chainage_0_midpoint", "geometry": Point(chainage0_mid)},
        ],
        crs=wgs84,
    )
    anchors_m = anchors.to_crs(local_epsg)
    centerline_m = LineString(
        [
            anchors_m.loc[anchors_m["name"] == "station_3905", "geometry"].iloc[0],
            anchors_m.loc[anchors_m["name"] == "chainage_0_midpoint", "geometry"].iloc[0],
        ]
    )
    boundary_m = centerline_m.buffer(args.buffer_m, cap_style=2, join_style=2)
    boundary = gpd.GeoDataFrame(
        [{"name": "cfm_corridor", "geometry": boundary_m}], crs=local_epsg
    ).to_crs(wgs84)
    centerline = gpd.GeoDataFrame(
        [{"name": "approx_centerline", "geometry": centerline_m}], crs=local_epsg
    ).to_crs(wgs84)

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = out_dir / "boundary.geojson"
    centerline_path = out_dir / "approx_centerline.geojson"
    anchors_path = out_dir / "anchors.geojson"
    manifest_path = out_dir / "boundary_manifest.json"

    boundary.to_file(boundary_path, driver="GeoJSON")
    centerline.to_file(centerline_path, driver="GeoJSON")
    anchors.to_file(anchors_path, driver="GeoJSON")

    line_wgs84 = centerline.geometry.iloc[0]
    river_axis_azimuth = _line_azimuth_deg(line_wgs84)
    transect_azimuth = (river_axis_azimuth + 90.0) % 180.0

    manifest = {
        "buffer_m": args.buffer_m,
        "boundary_geojson": str(boundary_path),
        "centerline_geojson": str(centerline_path),
        "anchors_geojson": str(anchors_path),
        "river_axis_azimuth_deg": river_axis_azimuth,
        "recommended_transect_azimuth_deg": transect_azimuth,
        "recommended_local_crs": str(local_epsg),
        "notes": [
            "Boundary is an approximate corridor derived from the provided KMZ anchors.",
            "Transect azimuth is perpendicular to the approximate centerline.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
