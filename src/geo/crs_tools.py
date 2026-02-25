from __future__ import annotations

from pyproj import Transformer


def transform_xy(x: float, y: float, src_epsg: int, dst_epsg: int) -> tuple[float, float]:
    transformer = Transformer.from_crs(f"EPSG:{src_epsg}", f"EPSG:{dst_epsg}", always_xy=True)
    return transformer.transform(x, y)
