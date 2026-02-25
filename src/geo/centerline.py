from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point


@dataclass
class CenterlineModel:
    line: LineString

    @property
    def length(self) -> float:
        return float(self.line.length)

    def get_point_at_chainage(self, chainage_m: float) -> Point:
        c = min(max(chainage_m, 0.0), self.length)
        return self.line.interpolate(c)

    def get_tangent_at_chainage(self, chainage_m: float, delta: float = 1.0) -> tuple[float, float]:
        c0 = min(max(chainage_m - delta, 0.0), self.length)
        c1 = min(max(chainage_m + delta, 0.0), self.length)
        p0 = self.line.interpolate(c0)
        p1 = self.line.interpolate(c1)
        dx = p1.x - p0.x
        dy = p1.y - p0.y
        mag = math.hypot(dx, dy)
        if mag == 0:
            return (1.0, 0.0)
        return (dx / mag, dy / mag)

    def get_normal_at_chainage(self, chainage_m: float) -> tuple[float, float]:
        tx, ty = self.get_tangent_at_chainage(chainage_m)
        return (-ty, tx)


def load_centerline(path: Path) -> CenterlineModel:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"No centerline geometry in {path}")
    geom = gdf.geometry.iloc[0]
    if not isinstance(geom, LineString):
        raise ValueError("Centerline geometry is not a LineString")
    return CenterlineModel(line=geom)
