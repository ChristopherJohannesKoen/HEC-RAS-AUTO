from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import LineString

from src.common.exceptions import TerrainSamplingError


def sample_point(terrain_path: Path, x: float, y: float) -> float:
    with rasterio.open(terrain_path) as ds:
        value = list(ds.sample([(x, y)]))[0][0]
        nodata = ds.nodata
        if nodata is not None and np.isclose(value, nodata):
            raise TerrainSamplingError(f"NoData at sampled point ({x:.2f}, {y:.2f})")
        return float(value)


def sample_profile(terrain_path: Path, line: LineString, spacing_m: float = 2.0) -> pd.DataFrame:
    if line.length <= 0:
        raise TerrainSamplingError("Cannot sample profile on zero-length line.")

    distances = np.arange(0.0, line.length + spacing_m, spacing_m)
    distances[-1] = line.length
    coords = [line.interpolate(d) for d in distances]
    xy = [(p.x, p.y) for p in coords]

    with rasterio.open(terrain_path) as ds:
        nodata = ds.nodata
        sampled = list(ds.sample(xy))

    rows: list[dict[str, float | bool]] = []
    for d, (x, y), v in zip(distances, xy, sampled):
        z = float(v[0])
        valid = True
        if nodata is not None and np.isclose(z, nodata):
            valid = False
            z = float("nan")
        rows.append({"distance_m": float(d), "x": x, "y": y, "elevation_m": z, "valid": valid})

    df = pd.DataFrame(rows)
    if df["valid"].sum() == 0:
        raise TerrainSamplingError("All profile samples are NoData.")
    return df
