from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint


def export_energy_floodline(
    sections_csv: Path,
    run_id: str,
    target_epsg: int,
    output_root: Path = Path("outputs"),
) -> Path:
    out_dir = output_root / run_id / "gis"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(sections_csv)
    if df.empty:
        raise ValueError("Sections CSV empty; cannot derive floodline.")

    points = list(zip(df["offset_m"], df["energy_level_m"]))
    # Placeholder geometric projection for v1 fixture pipeline:
    # uses synthetic x/y from offset/elevation to keep deterministic artifact creation.
    geom = MultiPoint([(float(x), float(y)) for x, y in points]).convex_hull
    gdf = gpd.GeoDataFrame({"run_id": [run_id], "type": ["energy_flood_envelope"]}, geometry=[geom], crs=f"EPSG:{target_epsg}")
    out_path = out_dir / "energy_floodline.geojson"
    gdf.to_file(out_path, driver="GeoJSON")
    return out_path
