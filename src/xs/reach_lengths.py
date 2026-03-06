from __future__ import annotations

import json
import logging
import math
import heapq
import shutil
import statistics
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point

from src.models import CrossSection

logger = logging.getLogger(__name__)

_CONTOUR_LAYER_HINTS = ("contour", "surf", "terrain", "ground", "topo")
_EXCLUDED_LAYER_HINTS = (
    "floodline",
    "cross section",
    "title",
    "google",
    "point",
    "centerline",
    "centreline",
)
_CENTERLINE_LAYER_HINTS = ("cl", "centerline", "centreline", "river centerline", "river centreline")


@dataclass
class _BankRouteResult:
    snapped_points: list[Point]
    snap_distances_m: list[float]
    segment_lengths_m: list[float]
    segment_geoms: list[LineString]
    full_line: LineString | None
    contour_segment_count: int
    connector_segment_count: int


def assign_reach_lengths(
    sections: list[CrossSection],
    dxf_path: Path | None = None,
    centerline_geojson: Path | None = None,
    debug_path: Path | None = None,
    diagnostic_dxf_path: Path | None = None,
) -> list[CrossSection]:
    ordered = sorted(sections, key=lambda s: s.chainage_m)
    if not ordered:
        return ordered

    if dxf_path is not None and centerline_geojson is not None and dxf_path.exists() and centerline_geojson.exists():
        debug_payload: dict[str, object] = {
            "method": "dxf_contour_guided_full_path",
            "dxf_path": str(dxf_path),
            "centerline_geojson": str(centerline_geojson),
        }
        try:
            centerline = _load_centerline(centerline_geojson)
            left_anchor = [_bank_point(section, side="left") for section in ordered]
            right_anchor = [_bank_point(section, side="right") for section in ordered]
            all_bank_points = left_anchor + right_anchor

            bank_dists = [centerline.distance(p) for p in all_bank_points]
            median_bank_dist = statistics.median(bank_dists) if bank_dists else 60.0
            corridor_radius_m = _clamp(6.0 * median_bank_dist, lo=180.0, hi=500.0)
            snap_max_dist_m = _clamp(3.5 * median_bank_dist, lo=40.0, hi=220.0)

            contour_lines = _load_contour_lines_near_centerline(
                dxf_path=dxf_path,
                centerline=centerline,
                corridor_radius_m=corridor_radius_m,
            )
            debug_payload["contour_candidate_count"] = len(contour_lines)
            debug_payload["corridor_radius_m"] = corridor_radius_m
            debug_payload["snap_max_dist_m"] = snap_max_dist_m

            if contour_lines:
                left_route = _route_bank_along_contours(
                    anchor_points=left_anchor,
                    contour_lines=contour_lines,
                    snap_max_dist_m=snap_max_dist_m,
                )
                right_route = _route_bank_along_contours(
                    anchor_points=right_anchor,
                    contour_lines=contour_lines,
                    snap_max_dist_m=snap_max_dist_m,
                )
                _assign_lengths_from_segments(
                    sections=ordered,
                    left_segment_lengths_m=left_route.segment_lengths_m,
                    right_segment_lengths_m=right_route.segment_lengths_m,
                    centerline=centerline,
                )

                if diagnostic_dxf_path is not None:
                    wrote_overlay = _write_reach_length_overlay_dxf(
                        source_dxf=dxf_path,
                        out_dxf=diagnostic_dxf_path,
                        left_anchor_points=left_anchor,
                        right_anchor_points=right_anchor,
                        left_route=left_route,
                        right_route=right_route,
                    )
                    debug_payload["diagnostic_dxf"] = {
                        "path": str(diagnostic_dxf_path),
                        "overlay_written": bool(wrote_overlay),
                    }

                debug_payload["left_route"] = {
                    "contour_segment_count": left_route.contour_segment_count,
                    "connector_segment_count": left_route.connector_segment_count,
                    "vertex_count": len(left_route.full_line.coords) if left_route.full_line is not None else 0,
                }
                debug_payload["right_route"] = {
                    "contour_segment_count": right_route.contour_segment_count,
                    "connector_segment_count": right_route.connector_segment_count,
                    "vertex_count": len(right_route.full_line.coords) if right_route.full_line is not None else 0,
                }

                debug_payload["sections"] = [
                    {
                        "chainage_m": float(section.chainage_m),
                        "left_snap_distance_m": _finite_or_none(left_route.snap_distances_m[i]),
                        "right_snap_distance_m": _finite_or_none(right_route.snap_distances_m[i]),
                        "left_reach_len_m": float(section.reach_length_left or 0.0),
                        "channel_reach_len_m": float(section.reach_length_channel or 0.0),
                        "right_reach_len_m": float(section.reach_length_right or 0.0),
                    }
                    for i, section in enumerate(ordered)
                ]
                if debug_path is not None:
                    _write_debug_payload(debug_payload, debug_path)
                return ordered

            debug_payload["note"] = "No contour lines were found near centerline; used chainage fallback."
        except Exception as exc:
            logger.warning("DXF-guided reach-length computation failed (%s); using chainage fallback.", exc)
            debug_payload["error"] = str(exc)
        if debug_path is not None:
            _write_debug_payload(debug_payload, debug_path)

    _assign_chainage_fallback(ordered)
    return ordered


def write_reach_lengths(sections: list[CrossSection], out_path: Path = Path("data/processed/reach_lengths.csv")) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in sections:
        rows.append(
            {
                "chainage_m": s.chainage_m,
                "river_station": s.river_station,
                "left_reach_len_m": s.reach_length_left,
                "channel_reach_len_m": s.reach_length_channel,
                "right_reach_len_m": s.reach_length_right,
            }
        )
    pd.DataFrame(rows).to_csv(out_path, index=False)
    return out_path


def _route_bank_along_contours(
    anchor_points: list[Point],
    contour_lines: list[LineString],
    snap_max_dist_m: float,
) -> _BankRouteResult:
    n = len(anchor_points)
    if n == 0:
        return _BankRouteResult([], [], [], [], None, 0, 0)
    if n == 1:
        return _BankRouteResult([anchor_points[0]], [float("nan")], [], [], None, 0, 0)

    snapped_points: list[Point] = []
    snap_distances: list[float] = []
    for point in anchor_points:
        snap_point, snap_dist = _nearest_projection_to_contours(point, contour_lines)
        if math.isfinite(snap_dist) and snap_dist <= snap_max_dist_m:
            snapped_points.append(snap_point)
            snap_distances.append(float(snap_dist))
        else:
            snapped_points.append(point)
            snap_distances.append(float("nan"))

    segment_geoms: list[LineString] = []
    segment_lengths: list[float] = []
    contour_count = 0
    connector_count = 0

    for i in range(n - 1):
        seg, mode = _route_contour_network_segment(
            start=snapped_points[i],
            end=snapped_points[i + 1],
            contour_lines=contour_lines,
        )
        if seg is None:
            seg = LineString(
                [
                    (snapped_points[i].x, snapped_points[i].y),
                    (snapped_points[i + 1].x, snapped_points[i + 1].y),
                ]
            )
            mode = "connector"
        segment_geoms.append(seg)
        segment_lengths.append(float(seg.length))
        if mode == "network":
            contour_count += 1
        else:
            connector_count += 1

    full_line = _merge_segment_geometries(segment_geoms)
    return _BankRouteResult(
        snapped_points=snapped_points,
        snap_distances_m=snap_distances,
        segment_lengths_m=segment_lengths,
        segment_geoms=segment_geoms,
        full_line=full_line,
        contour_segment_count=contour_count,
        connector_segment_count=connector_count,
    )


def _nearest_projection_to_contours(
    point: Point,
    contour_lines: list[LineString],
) -> tuple[Point, float]:
    best_dist = float("inf")
    best_point = point
    for line in contour_lines:
        dist = float(line.distance(point))
        if dist < best_dist:
            station = float(line.project(point))
            best_point = line.interpolate(station)
            best_dist = dist
    return best_point, best_dist


def _route_contour_network_segment(
    start: Point,
    end: Point,
    contour_lines: list[LineString],
) -> tuple[LineString | None, str]:
    base = LineString([(start.x, start.y), (end.x, end.y)])
    local_radius = _clamp(0.35 * float(base.length), 35.0, 120.0)
    attach_tol = _clamp(0.40 * float(base.length), 25.0, 160.0)
    bridge_tol = _clamp(0.08 * float(base.length), 2.0, 8.0)
    bridge_penalty = 3.0

    local_lines = [line for line in contour_lines if line.distance(base) <= local_radius]
    if not local_lines:
        local_lines = [line for line in contour_lines if line.distance(base) <= 2.0 * local_radius]
    if not local_lines:
        return None, "connector"

    # Guard against pathological local extracts.
    if len(local_lines) > 8000:
        ranked = sorted(local_lines, key=lambda ln: ln.distance(base))
        local_lines = ranked[:8000]

    node_ids: dict[tuple[float, float], int] = {}
    node_coords: list[tuple[float, float]] = []
    adjacency: dict[int, list[tuple[int, float]]] = {}

    def _get_node_id(x: float, y: float) -> int:
        key = (round(float(x), 3), round(float(y), 3))
        existing = node_ids.get(key)
        if existing is not None:
            return existing
        nid = len(node_coords)
        node_ids[key] = nid
        node_coords.append((float(x), float(y)))
        adjacency[nid] = []
        return nid

    def _add_edge(a: int, b: int, w: float) -> None:
        if a == b or w <= 0.0 or (not math.isfinite(w)):
            return
        adjacency[a].append((b, float(w)))
        adjacency[b].append((a, float(w)))

    for line in local_lines:
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        prev_id = _get_node_id(coords[0][0], coords[0][1])
        for coord in coords[1:]:
            x = float(coord[0])
            y = float(coord[1])
            cur_id = _get_node_id(x, y)
            w = math.hypot(node_coords[cur_id][0] - node_coords[prev_id][0], node_coords[cur_id][1] - node_coords[prev_id][1])
            _add_edge(prev_id, cur_id, w)
            prev_id = cur_id

    if len(node_coords) < 2 or len(node_coords) > 100000:
        return None, "connector"

    # Bridge nearby vertices so adjacent/near-touching contour lines become traversable.
    grid_size = max(bridge_tol, 1.0)
    cell_map: dict[tuple[int, int], list[int]] = {}
    for nid, (x, y) in enumerate(node_coords):
        cell = (int(math.floor(x / grid_size)), int(math.floor(y / grid_size)))
        cell_map.setdefault(cell, []).append(nid)

    for nid, (x, y) in enumerate(node_coords):
        cx, cy = int(math.floor(x / grid_size)), int(math.floor(y / grid_size))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for mid in cell_map.get((cx + dx, cy + dy), []):
                    if mid <= nid:
                        continue
                    x2, y2 = node_coords[mid]
                    d = math.hypot(x2 - x, y2 - y)
                    if 0.0 < d <= bridge_tol:
                        _add_edge(nid, mid, d * bridge_penalty)

    start_id = len(node_coords)
    end_id = start_id + 1
    node_coords.extend([(float(start.x), float(start.y)), (float(end.x), float(end.y))])
    adjacency[start_id] = []
    adjacency[end_id] = []

    near_start = _nearest_node_ids(Point(start.x, start.y), node_coords[:-2], max_dist=attach_tol, k=8)
    near_end = _nearest_node_ids(Point(end.x, end.y), node_coords[:-2], max_dist=attach_tol, k=8)
    if not near_start:
        near_start = _nearest_node_ids(Point(start.x, start.y), node_coords[:-2], max_dist=float("inf"), k=4)
    if not near_end:
        near_end = _nearest_node_ids(Point(end.x, end.y), node_coords[:-2], max_dist=float("inf"), k=4)
    if not near_start or not near_end:
        return None, "connector"

    for nid in near_start:
        x, y = node_coords[nid]
        _add_edge(start_id, nid, math.hypot(x - start.x, y - start.y))
    for nid in near_end:
        x, y = node_coords[nid]
        _add_edge(end_id, nid, math.hypot(x - end.x, y - end.y))

    path = _dijkstra_path(adjacency, start_id, end_id)
    if not path or len(path) < 2:
        return None, "connector"
    coords = [node_coords[nid] for nid in path]
    if len(coords) < 2:
        return None, "connector"
    try:
        geom = LineString(coords)
    except Exception:
        return None, "connector"
    if geom.length <= 0.0:
        return None, "connector"
    return geom, "network"


def _nearest_node_ids(point: Point, coords: list[tuple[float, float]], max_dist: float, k: int) -> list[int]:
    ranked: list[tuple[float, int]] = []
    for idx, (x, y) in enumerate(coords):
        d = math.hypot(x - point.x, y - point.y)
        if d <= max_dist:
            ranked.append((d, idx))
    if not ranked:
        return []
    ranked.sort(key=lambda x: x[0])
    return [idx for _, idx in ranked[:k]]


def _dijkstra_path(adjacency: dict[int, list[tuple[int, float]]], start: int, end: int) -> list[int]:
    dist: dict[int, float] = {start: 0.0}
    prev: dict[int, int] = {}
    heap: list[tuple[float, int]] = [(0.0, start)]
    visited: set[int] = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        if u == end:
            break
        for v, w in adjacency.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    if end not in dist:
        return []
    path = [end]
    cur = end
    while cur != start:
        cur = prev.get(cur)
        if cur is None:
            return []
        path.append(cur)
    path.reverse()
    return path


def _merge_segment_geometries(segments: list[LineString]) -> LineString | None:
    merged: list[tuple[float, float]] = []
    for seg in segments:
        coords = list(seg.coords)
        if len(coords) < 2:
            continue
        if not merged:
            merged.extend(coords)
            continue

        prev = Point(merged[-1])
        first = Point(coords[0])
        last = Point(coords[-1])
        if prev.distance(first) <= 1e-6:
            merged.extend(coords[1:])
        elif prev.distance(last) <= 1e-6:
            rev = list(reversed(coords))
            merged.extend(rev[1:])
        else:
            merged.extend(coords)

    if len(merged) < 2:
        return None
    return LineString(merged)


def _assign_chainage_fallback(sections: list[CrossSection]) -> None:
    for i, section in enumerate(sections):
        if i == len(sections) - 1:
            section.reach_length_left = 0.0
            section.reach_length_channel = 0.0
            section.reach_length_right = 0.0
            continue
        d = float(sections[i + 1].chainage_m - section.chainage_m)
        section.reach_length_left = d
        section.reach_length_channel = d
        section.reach_length_right = d


def _assign_lengths_from_segments(
    sections: list[CrossSection],
    left_segment_lengths_m: list[float],
    right_segment_lengths_m: list[float],
    centerline: LineString,
) -> None:
    if len(left_segment_lengths_m) != len(sections) - 1 or len(right_segment_lengths_m) != len(sections) - 1:
        _assign_chainage_fallback(sections)
        return

    centerline_stations = [_centerline_station(section, centerline) for section in sections]
    for i, section in enumerate(sections):
        if i == len(sections) - 1:
            section.reach_length_left = 0.0
            section.reach_length_channel = 0.0
            section.reach_length_right = 0.0
            continue

        fallback = float(sections[i + 1].chainage_m - section.chainage_m)
        left_len = float(left_segment_lengths_m[i])
        right_len = float(right_segment_lengths_m[i])
        channel_len = float(centerline_stations[i + 1] - centerline_stations[i])

        section.reach_length_left = _sanitize_reach_length(left_len, fallback)
        section.reach_length_channel = _sanitize_reach_length(channel_len, fallback)
        section.reach_length_right = _sanitize_reach_length(right_len, fallback)


def _sanitize_reach_length(value: float, fallback: float) -> float:
    if not math.isfinite(value) or value <= 0.0:
        return max(0.0, fallback)
    safe = float(value)
    if fallback > 0.0 and safe > 6.0 * fallback:
        return max(0.0, fallback)
    return safe


def _bank_point(section: CrossSection, side: str) -> Point:
    if len(section.cutline) < 2:
        raise ValueError(f"Cross-section at chainage {section.chainage_m} has no valid cutline.")
    (x0, y0), (x1, y1) = section.cutline[0], section.cutline[1]
    station_values = [float(p.station) for p in section.points]
    if not station_values:
        raise ValueError(f"Cross-section at chainage {section.chainage_m} has no station points.")
    smin = min(station_values)
    smax = max(station_values)
    span = max(smax - smin, 1e-9)

    if side == "left":
        target_station = float(section.left_bank_station)
    elif side == "right":
        target_station = float(section.right_bank_station)
    else:
        raise ValueError(f"Unsupported bank side: {side}")

    t = (target_station - smin) / span
    t = _clamp(t, 0.0, 1.0)
    return Point(x0 + t * (x1 - x0), y0 + t * (y1 - y0))


def _load_centerline(centerline_geojson: Path) -> LineString:
    import geopandas as gpd

    gdf = gpd.read_file(centerline_geojson)
    if gdf.empty:
        raise ValueError(f"No centerline geometry found in {centerline_geojson}")
    geom = gdf.geometry.iloc[0]
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        parts = [part for part in geom.geoms if isinstance(part, LineString) and part.length > 0.0]
        if parts:
            return max(parts, key=lambda p: p.length)
    raise ValueError("Centerline geometry must be a non-empty LineString.")


def _centerline_station(section: CrossSection, centerline: LineString) -> float:
    if len(section.cutline) < 2:
        return float(section.chainage_m)
    (x0, y0), (x1, y1) = section.cutline[0], section.cutline[1]
    mid = Point((x0 + x1) * 0.5, (y0 + y1) * 0.5)
    return float(centerline.project(mid))


def _load_contour_lines_near_centerline(
    dxf_path: Path,
    centerline: LineString,
    corridor_radius_m: float,
) -> list[LineString]:
    import geopandas as gpd

    gdf = gpd.read_file(dxf_path)
    if gdf.empty:
        return []
    layer_col = _find_column_case_insensitive(gdf.columns, "layer")

    def _iter_candidates(prefer_contours: bool) -> list[LineString]:
        lines: list[LineString] = []
        for idx, geom in enumerate(gdf.geometry):
            layer = ""
            if layer_col is not None:
                raw = gdf.iloc[idx][layer_col]
                layer = str(raw).strip().lower() if raw is not None else ""

            if _is_excluded_layer(layer):
                continue
            if prefer_contours and not _is_contour_layer(layer):
                continue
            if (not prefer_contours) and _is_centerline_layer(layer):
                continue

            for line in _flatten_lines(geom):
                if line.distance(centerline) <= corridor_radius_m:
                    lines.append(line)
        return lines

    preferred = _iter_candidates(prefer_contours=True)
    if preferred:
        return preferred
    return _iter_candidates(prefer_contours=False)


def _find_column_case_insensitive(columns: list[str], target: str) -> str | None:
    low = target.lower()
    for col in columns:
        if str(col).lower() == low:
            return str(col)
    return None


def _is_contour_layer(layer: str) -> bool:
    lname = layer.strip().lower()
    if not lname:
        return False
    return any(hint in lname for hint in _CONTOUR_LAYER_HINTS)


def _is_excluded_layer(layer: str) -> bool:
    lname = layer.strip().lower()
    if not lname:
        return False
    if _is_centerline_layer(lname):
        return True
    return any(hint in lname for hint in _EXCLUDED_LAYER_HINTS)


def _is_centerline_layer(layer: str) -> bool:
    lname = layer.strip().lower()
    return lname in _CENTERLINE_LAYER_HINTS


def _flatten_lines(geom: object) -> list[LineString]:
    if geom is None:
        return []
    if isinstance(geom, LineString):
        return [geom] if geom.length > 0.0 else []
    if isinstance(geom, MultiLineString):
        return [part for part in geom.geoms if isinstance(part, LineString) and part.length > 0.0]
    return []


def _write_debug_payload(payload: dict[str, object], path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write reach-length debug payload (%s): %s", path, exc)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _write_reach_length_overlay_dxf(
    source_dxf: Path,
    out_dxf: Path,
    left_anchor_points: list[Point],
    right_anchor_points: list[Point],
    left_route: _BankRouteResult,
    right_route: _BankRouteResult,
) -> bool:
    out_dxf.parent.mkdir(parents=True, exist_ok=True)
    try:
        import ezdxf
    except Exception:
        logger.warning(
            "ezdxf not installed; copied source DXF to %s without bank-path overlays.",
            out_dxf,
        )
        try:
            shutil.copy2(source_dxf, out_dxf)
            return False
        except Exception as exc:
            alt = _next_available_dxf_path(out_dxf)
            try:
                shutil.copy2(source_dxf, alt)
                logger.warning("Copied DXF to fallback path %s after lock on %s.", alt, out_dxf)
            except Exception:
                logger.warning("Failed to copy DXF to %s: %s", out_dxf, exc)
            return False

    try:
        doc = ezdxf.readfile(str(source_dxf))
        msp = doc.modelspace()
    except Exception as exc:
        logger.warning(
            "Failed to open source DXF for overlay (%s). Copying source to %s.",
            exc,
            out_dxf,
        )
        try:
            shutil.copy2(source_dxf, out_dxf)
            return False
        except Exception as copy_exc:
            logger.warning("Failed to copy DXF to %s: %s", out_dxf, copy_exc)
            return False

    _ensure_layer(doc, "BANK_PATH_LEFT", color=1)
    _ensure_layer(doc, "BANK_PATH_RIGHT", color=5)
    _ensure_layer(doc, "BANK_ANCHOR_LEFT", color=3)
    _ensure_layer(doc, "BANK_ANCHOR_RIGHT", color=4)
    _ensure_layer(doc, "BANK_SNAP_LEFT", color=2)
    _ensure_layer(doc, "BANK_SNAP_RIGHT", color=6)

    _add_line_to_dxf(msp, left_route.full_line, "BANK_PATH_LEFT")
    _add_line_to_dxf(msp, right_route.full_line, "BANK_PATH_RIGHT")

    anchor_radius = _marker_radius(left_anchor_points, right_anchor_points)
    snap_radius = _clamp(0.6 * anchor_radius, 0.8, max(1.0, anchor_radius))

    _add_points_to_dxf(msp, left_anchor_points, "BANK_ANCHOR_LEFT", anchor_radius)
    _add_points_to_dxf(msp, right_anchor_points, "BANK_ANCHOR_RIGHT", anchor_radius)
    _add_points_to_dxf(msp, left_route.snapped_points, "BANK_SNAP_LEFT", snap_radius)
    _add_points_to_dxf(msp, right_route.snapped_points, "BANK_SNAP_RIGHT", snap_radius)

    try:
        doc.saveas(str(out_dxf))
        return True
    except Exception as exc:
        logger.warning("Failed to save overlay DXF (%s). Trying fallback filename.", exc)
        try:
            alt = _next_available_dxf_path(out_dxf)
            doc.saveas(str(alt))
            logger.warning("Saved overlay DXF to fallback path: %s", alt)
            return True
        except Exception as copy_exc:
            logger.warning("Failed to save fallback DXF for %s: %s", out_dxf, copy_exc)
            return False


def _add_line_to_dxf(msp: object, line: LineString | None, layer: str) -> None:
    if line is None or len(line.coords) < 2:
        return
    try:
        msp.add_lwpolyline([(float(c[0]), float(c[1])) for c in line.coords], dxfattribs={"layer": layer})
    except Exception:
        pass


def _add_points_to_dxf(msp: object, points: list[Point], layer: str, radius: float) -> None:
    for p in points:
        try:
            msp.add_circle((float(p.x), float(p.y)), radius=float(radius), dxfattribs={"layer": layer})
        except Exception:
            continue


def _ensure_layer(doc: object, name: str, color: int) -> None:
    try:
        if name in doc.layers:
            return
        doc.layers.new(name, dxfattribs={"color": int(color)})
    except Exception:
        pass


def _marker_radius(left_points: list[Point], right_points: list[Point]) -> float:
    distances: list[float] = []
    for path in (left_points, right_points):
        for i in range(len(path) - 1):
            d = path[i].distance(path[i + 1])
            if d > 0.0 and math.isfinite(d):
                distances.append(float(d))
    if not distances:
        return 3.0
    med = statistics.median(distances)
    return _clamp(0.015 * med, 1.0, 12.0)


def _next_available_dxf_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix or ".dxf"
    parent = base_path.parent
    i = 1
    while True:
        cand = parent / f"{stem}_{i}{suffix}"
        if not cand.exists():
            return cand
        i += 1
