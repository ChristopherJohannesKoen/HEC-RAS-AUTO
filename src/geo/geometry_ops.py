from __future__ import annotations

from shapely.geometry import LineString, Point


def section_intersects_reach_once(section: LineString, reach: LineString) -> bool:
    inter = section.intersection(reach)
    if inter.is_empty:
        return False
    if isinstance(inter, Point):
        return True
    if hasattr(inter, "geoms"):
        return len(list(inter.geoms)) == 1
    return False


def sections_cross(section_a: LineString, section_b: LineString) -> bool:
    return section_a.crosses(section_b)


def point_side_of_direction(
    point: tuple[float, float], origin: tuple[float, float], direction: tuple[float, float]
) -> float:
    px, py = point
    ox, oy = origin
    dx, dy = direction
    return (px - ox) * dy - (py - oy) * dx
