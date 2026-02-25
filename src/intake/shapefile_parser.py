from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge


def parse_centerline_shapefile(shp_path: Path, target_epsg: int, out_dir: Path = Path("data/processed")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf = gpd.read_file(shp_path)
    if gdf.empty:
        raise ValueError(f"Centerline shapefile is empty: {shp_path}")
    if gdf.crs is None:
        raise ValueError("Centerline shapefile has no CRS metadata.")
    gdf = gdf.to_crs(epsg=target_epsg)

    merged = linemerge(list(gdf.geometry))
    if isinstance(merged, MultiLineString):
        merged = max(merged.geoms, key=lambda g: g.length)
    if not isinstance(merged, LineString):
        raise ValueError("Could not derive single LineString centerline from shapefile.")

    out_gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[merged], crs=f"EPSG:{target_epsg}")
    out_path = out_dir / "centerline_from_shp.geojson"
    out_gdf.to_file(out_path, driver="GeoJSON")
    return out_path
