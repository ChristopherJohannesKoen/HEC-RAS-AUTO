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
    bank_endpoint_constraints: list[dict[str, object]] | None = None,
    auto_transform_constraints: bool = False,
    snap_constrained_points: bool = False,
    enforce_constraints_on_cutline: bool = True,
) -> list[CrossSection]:
    ordered = sorted(sections, key=lambda s: s.chainage_m)
    if not ordered:
        return ordered

    if dxf_path is not None and centerline_geojson is not None and dxf_path.exists() and centerline_geojson.exists():
        debug_payload: dict[str, object] = {
            "method": "dxf_contour_guided_full_path",
            "dxf_path": str(dxf_path),
            "centerline_geojson": str(centerline_geojson),
            "auto_transform_constraints": bool(auto_transform_constraints),
            "snap_constrained_points": bool(snap_constrained_points),
            "enforce_constraints_on_cutline": bool(enforce_constraints_on_cutline),
        }
        try:
            centerline = _load_centerline(centerline_geojson)
            left_anchor = [_bank_point(section, side="left") for section in ordered]
            right_anchor = [_bank_point(section, side="right") for section in ordered]
            constraint_pre_offset = _infer_constraint_xy_offset_from_dxf_ucs(
                sections=ordered,
                left_anchor=left_anchor,
                right_anchor=right_anchor,
                constraints=bank_endpoint_constraints,
                dxf_path=dxf_path,
            )
            constraints_applied, constraint_transform, constrained_indices = _apply_bank_endpoint_constraints(
                sections=ordered,
                left_anchor=left_anchor,
                right_anchor=right_anchor,
                constraints=bank_endpoint_constraints,
                auto_transform_constraints=auto_transform_constraints,
                enforce_on_chainage_line=enforce_constraints_on_cutline,
                constraint_xy_offset=(
                    (float(constraint_pre_offset["dx"]), float(constraint_pre_offset["dy"]))
                    if constraint_pre_offset is not None
                    else None
                ),
            )
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
            if constraints_applied:
                debug_payload["bank_endpoint_constraints_applied"] = constraints_applied
            if constraint_pre_offset is not None:
                debug_payload["bank_endpoint_constraint_pre_offset"] = constraint_pre_offset
            if constraint_transform is not None:
                debug_payload["bank_endpoint_constraint_transform"] = constraint_transform

            if contour_lines:
                left_route = _route_bank_along_contours(
                    anchor_points=left_anchor,
                    contour_lines=contour_lines,
                    snap_max_dist_m=snap_max_dist_m,
                    fixed_indices=constrained_indices,
                    snap_fixed_points=snap_constrained_points,
                )
                right_route = _route_bank_along_contours(
                    anchor_points=right_anchor,
                    contour_lines=contour_lines,
                    snap_max_dist_m=snap_max_dist_m,
                    fixed_indices=constrained_indices,
                    snap_fixed_points=snap_constrained_points,
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
    fixed_indices: set[int] | None = None,
    snap_fixed_points: bool = False,
) -> _BankRouteResult:
    n = len(anchor_points)
    if n == 0:
        return _BankRouteResult([], [], [], [], None, 0, 0)
    if n == 1:
        return _BankRouteResult([anchor_points[0]], [float("nan")], [], [], None, 0, 0)

    snapped_points: list[Point] = []
    snap_distances: list[float] = []
    fixed = fixed_indices or set()
    for i, point in enumerate(anchor_points):
        if i in fixed and not snap_fixed_points:
            snapped_points.append(point)
            snap_distances.append(float("nan"))
            continue
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


def _apply_bank_endpoint_constraints(
    sections: list[CrossSection],
    left_anchor: list[Point],
    right_anchor: list[Point],
    constraints: list[dict[str, object]] | None,
    auto_transform_constraints: bool,
    enforce_on_chainage_line: bool,
    constraint_xy_offset: tuple[float, float] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object] | None, set[int]]:
    if not constraints:
        return [], None, set()
    if not sections or len(left_anchor) != len(sections) or len(right_anchor) != len(sections):
        return [], None, set()

    applied: list[dict[str, object]] = []
    staged: list[dict[str, object]] = []
    constrained_indices: set[int] = set()
    dx = float(constraint_xy_offset[0]) if constraint_xy_offset is not None else 0.0
    dy = float(constraint_xy_offset[1]) if constraint_xy_offset is not None else 0.0
    for item in constraints:
        try:
            target_chainage = float(item.get("chainage_m"))  # type: ignore[arg-type]
            left_xy = item.get("left_xy")  # type: ignore[assignment]
            right_xy = item.get("right_xy")  # type: ignore[assignment]
            if not isinstance(left_xy, (list, tuple)) or len(left_xy) < 2:
                continue
            if not isinstance(right_xy, (list, tuple)) or len(right_xy) < 2:
                continue
            idx = min(range(len(sections)), key=lambda i: abs(float(sections[i].chainage_m) - target_chainage))
            nearest_chainage = float(sections[idx].chainage_m)
            constrained_indices.add(idx)
            left_raw = [float(left_xy[0]), float(left_xy[1])]
            right_raw = [float(right_xy[0]), float(right_xy[1])]
            staged.append(
                {
                    "target_chainage_m": target_chainage,
                    "matched_chainage_m": nearest_chainage,
                    "section_index": int(idx),
                    "left_xy_input": [left_raw[0], left_raw[1]],
                    "right_xy_input": [right_raw[0], right_raw[1]],
                    "left_xy_raw": [left_raw[0] + dx, left_raw[1] + dy],
                    "right_xy_raw": [right_raw[0] + dx, right_raw[1] + dy],
                    "left_z": _finite_or_none(float(item.get("left_z"))) if item.get("left_z") is not None else None,
                    "right_z": _finite_or_none(float(item.get("right_z"))) if item.get("right_z") is not None else None,
                    "pre_offset_applied": constraint_xy_offset is not None,
                    "pre_offset_dx": dx if constraint_xy_offset is not None else 0.0,
                    "pre_offset_dy": dy if constraint_xy_offset is not None else 0.0,
                }
            )
        except Exception:
            continue

    transform_meta: dict[str, object] | None = None
    apply_transform = False
    if auto_transform_constraints and len(staged) >= 2:
        src_points: list[tuple[float, float]] = []
        dst_points: list[tuple[float, float]] = []
        for row in staged:
            idx = int(row["section_index"])
            src_points.append((float(row["left_xy_raw"][0]), float(row["left_xy_raw"][1])))
            src_points.append((float(row["right_xy_raw"][0]), float(row["right_xy_raw"][1])))
            dst_points.append((float(left_anchor[idx].x), float(left_anchor[idx].y)))
            dst_points.append((float(right_anchor[idx].x), float(right_anchor[idx].y)))
        fit = _similarity_fit_2d(src_points, dst_points)
        if fit is not None:
            direct_rmse = _rmse_2d(src_points, dst_points)
            fit_rmse = float(fit["rmse"])
            if direct_rmse > 250.0 and fit_rmse < 120.0 and fit_rmse < 0.45 * max(direct_rmse, 1e-9):
                apply_transform = True
                transform_meta = {
                    "applied": True,
                    "reason": "constraint_points_not_in_model_frame",
                    "direct_rmse_m": direct_rmse,
                    "fit_rmse_m": fit_rmse,
                    "scale": float(fit["scale"]),
                    "rotation_deg": float(fit["rotation_deg"]),
                    "tx": float(fit["tx"]),
                    "ty": float(fit["ty"]),
                }
            else:
                transform_meta = {
                    "applied": False,
                    "direct_rmse_m": direct_rmse,
                    "fit_rmse_m": fit_rmse,
                    "scale": float(fit["scale"]),
                    "rotation_deg": float(fit["rotation_deg"]),
                    "tx": float(fit["tx"]),
                    "ty": float(fit["ty"]),
                }

    for row in staged:
        idx = int(row["section_index"])
        lx, ly = float(row["left_xy_raw"][0]), float(row["left_xy_raw"][1])
        rx, ry = float(row["right_xy_raw"][0]), float(row["right_xy_raw"][1])
        cut = sections[idx].cutline
        if apply_transform and transform_meta is not None:
            lx, ly = _apply_similarity_point(
                x=lx,
                y=ly,
                scale=float(transform_meta["scale"]),
                rotation_deg=float(transform_meta["rotation_deg"]),
                tx=float(transform_meta["tx"]),
                ty=float(transform_meta["ty"]),
            )
            rx, ry = _apply_similarity_point(
                x=rx,
                y=ry,
                scale=float(transform_meta["scale"]),
                rotation_deg=float(transform_meta["rotation_deg"]),
                tx=float(transform_meta["tx"]),
                ty=float(transform_meta["ty"]),
            )
        if enforce_on_chainage_line:
            lx, ly = _project_xy_to_cutline((lx, ly), sections[idx].cutline)
            rx, ry = _project_xy_to_cutline((rx, ry), sections[idx].cutline)
            l_t = _cutline_t((lx, ly), cut)
            r_t = _cutline_t((rx, ry), cut)
            if abs(l_t - r_t) < 0.01:
                l_def_t = _cutline_t((left_anchor[idx].x, left_anchor[idx].y), cut)
                r_def_t = _cutline_t((right_anchor[idx].x, right_anchor[idx].y), cut)
                lx, ly = _point_at_cutline_t(cut, l_def_t)
                rx, ry = _point_at_cutline_t(cut, r_def_t)
                row["projection_collapsed_adjusted"] = True
            else:
                row["projection_collapsed_adjusted"] = False
        left_anchor[idx] = Point(lx, ly)
        right_anchor[idx] = Point(rx, ry)

        row["left_xy"] = [float(lx), float(ly)]
        row["right_xy"] = [float(rx), float(ry)]
        row["transform_applied"] = bool(apply_transform)
        row["projected_to_chainage_line"] = bool(enforce_on_chainage_line)
        applied.append(row)

    return applied, transform_meta, constrained_indices


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


def _project_xy_to_cutline(xy: tuple[float, float], cutline: list[tuple[float, float]]) -> tuple[float, float]:
    if len(cutline) < 2:
        return float(xy[0]), float(xy[1])
    p = Point(float(xy[0]), float(xy[1]))
    line = LineString([(float(c[0]), float(c[1])) for c in cutline[:2]])
    if line.length <= 0.0:
        return float(xy[0]), float(xy[1])
    s = float(line.project(p))
    q = line.interpolate(s)
    return float(q.x), float(q.y)


def _cutline_t(xy: tuple[float, float], cutline: list[tuple[float, float]]) -> float:
    if len(cutline) < 2:
        return 0.0
    line = LineString([(float(c[0]), float(c[1])) for c in cutline[:2]])
    if line.length <= 0.0:
        return 0.0
    s = float(line.project(Point(float(xy[0]), float(xy[1]))))
    return _clamp(s / float(line.length), 0.0, 1.0)


def _point_at_cutline_t(cutline: list[tuple[float, float]], t: float) -> tuple[float, float]:
    if len(cutline) < 2:
        return 0.0, 0.0
    line = LineString([(float(c[0]), float(c[1])) for c in cutline[:2]])
    if line.length <= 0.0:
        return float(cutline[0][0]), float(cutline[0][1])
    q = line.interpolate(_clamp(float(t), 0.0, 1.0) * float(line.length))
    return float(q.x), float(q.y)


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


def _infer_constraint_xy_offset_from_dxf_ucs(
    sections: list[CrossSection],
    left_anchor: list[Point],
    right_anchor: list[Point],
    constraints: list[dict[str, object]] | None,
    dxf_path: Path,
) -> dict[str, float] | None:
    if not constraints:
        return None
    if not sections or len(left_anchor) != len(sections) or len(right_anchor) != len(sections):
        return None
    ucs = _read_dxf_ucs_origin_xy(dxf_path)
    if ucs is None:
        return None
    ox, oy = float(ucs[0]), float(ucs[1])
    if abs(ox) + abs(oy) < 1e-9:
        return None

    staged: list[tuple[tuple[float, float], tuple[float, float], int]] = []
    for item in constraints:
        try:
            target_chainage = float(item.get("chainage_m"))  # type: ignore[arg-type]
            left_xy = item.get("left_xy")  # type: ignore[assignment]
            right_xy = item.get("right_xy")  # type: ignore[assignment]
            if not isinstance(left_xy, (list, tuple)) or len(left_xy) < 2:
                continue
            if not isinstance(right_xy, (list, tuple)) or len(right_xy) < 2:
                continue
            idx = min(range(len(sections)), key=lambda i: abs(float(sections[i].chainage_m) - target_chainage))
            staged.append(
                (
                    (float(left_xy[0]), float(left_xy[1])),
                    (float(right_xy[0]), float(right_xy[1])),
                    int(idx),
                )
            )
        except Exception:
            continue
    if not staged:
        return None

    def _rmse(dx: float, dy: float) -> float:
        errs: list[float] = []
        for (lx, ly), (rx, ry), idx in staged:
            errs.append(math.hypot((lx + dx) - float(left_anchor[idx].x), (ly + dy) - float(left_anchor[idx].y)))
            errs.append(math.hypot((rx + dx) - float(right_anchor[idx].x), (ry + dy) - float(right_anchor[idx].y)))
        if not errs:
            return float("inf")
        return float(math.sqrt(sum(e * e for e in errs) / len(errs)))

    rmse_none = _rmse(0.0, 0.0)
    rmse_plus = _rmse(ox, oy)
    rmse_minus = _rmse(-ox, -oy)
    best_rmse, best_dx, best_dy, best_mode = min(
        [
            (rmse_none, 0.0, 0.0, "none"),
            (rmse_plus, ox, oy, "plus_ucsorg"),
            (rmse_minus, -ox, -oy, "minus_ucsorg"),
        ],
        key=lambda t: t[0],
    )

    # Only apply offset when it materially improves alignment.
    if best_mode == "none":
        return None
    if not math.isfinite(best_rmse) or not math.isfinite(rmse_none):
        return None
    if best_rmse >= (0.45 * max(rmse_none, 1e-9)):
        return None
    if (rmse_none - best_rmse) < 80.0:
        return None

    return {
        "dx": float(best_dx),
        "dy": float(best_dy),
        "ucs_origin_x": ox,
        "ucs_origin_y": oy,
        "mode": 1.0 if best_mode == "plus_ucsorg" else -1.0,
        "rmse_none_m": float(rmse_none),
        "rmse_best_m": float(best_rmse),
    }


def _read_dxf_ucs_origin_xy(dxf_path: Path) -> tuple[float, float] | None:
    try:
        import ezdxf
    except Exception:
        return None
    try:
        doc = ezdxf.readfile(str(dxf_path))
        hdr = doc.header
        raw = hdr.get("$UCSORG")
        if not raw or len(raw) < 2:
            return None
        return float(raw[0]), float(raw[1])
    except Exception:
        return None


def _similarity_fit_2d(
    src_points: list[tuple[float, float]],
    dst_points: list[tuple[float, float]],
) -> dict[str, float] | None:
    if len(src_points) != len(dst_points) or len(src_points) < 2:
        return None
    n = float(len(src_points))
    mxs = sum(p[0] for p in src_points) / n
    mys = sum(p[1] for p in src_points) / n
    mxd = sum(p[0] for p in dst_points) / n
    myd = sum(p[1] for p in dst_points) / n

    src_c = [(x - mxs, y - mys) for x, y in src_points]
    dst_c = [(x - mxd, y - myd) for x, y in dst_points]
    var_src = sum((x * x + y * y) for x, y in src_c) / n
    if var_src <= 0:
        return None

    cxx = sum(dx * sx for (sx, sy), (dx, dy) in zip(src_c, dst_c)) / n
    cxy = sum(dx * sy for (sx, sy), (dx, dy) in zip(src_c, dst_c)) / n
    cyx = sum(dy * sx for (sx, sy), (dx, dy) in zip(src_c, dst_c)) / n
    cyy = sum(dy * sy for (sx, sy), (dx, dy) in zip(src_c, dst_c)) / n

    # 2x2 SVD via numpy for robustness
    try:
        import numpy as np
    except Exception:
        return None
    cov = np.array([[cxx, cxy], [cyx, cyy]], dtype=float)
    u, svals, vt = np.linalg.svd(cov)
    d = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[-1, -1] = -1.0
    r = u @ d @ vt
    scale = float(np.trace(np.diag(svals) @ d) / var_src)
    tx = float(mxd - scale * (r[0, 0] * mxs + r[0, 1] * mys))
    ty = float(myd - scale * (r[1, 0] * mxs + r[1, 1] * mys))
    theta = float(math.degrees(math.atan2(r[1, 0], r[0, 0])))

    pred = [ _apply_similarity_point(x, y, scale, theta, tx, ty) for x, y in src_points ]
    rmse = _rmse_2d(pred, dst_points)
    return {
        "scale": scale,
        "rotation_deg": theta,
        "tx": tx,
        "ty": ty,
        "rmse": rmse,
    }


def _apply_similarity_point(
    x: float,
    y: float,
    scale: float,
    rotation_deg: float,
    tx: float,
    ty: float,
) -> tuple[float, float]:
    th = math.radians(rotation_deg)
    c = math.cos(th)
    s = math.sin(th)
    xr = scale * (c * x - s * y) + tx
    yr = scale * (s * x + c * y) + ty
    return float(xr), float(yr)


def _rmse_2d(
    p: list[tuple[float, float]],
    q: list[tuple[float, float]],
) -> float:
    if not p or len(p) != len(q):
        return float("inf")
    se = 0.0
    for (x1, y1), (x2, y2) in zip(p, q):
        dx = x1 - x2
        dy = y1 - y2
        se += dx * dx + dy * dy
    return float(math.sqrt(se / len(p)))


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
        _force_world_ucs(doc)
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


def _force_world_ucs(doc: object) -> None:
    """Normalize UCS header vars so AutoCAD reads coordinates in WCS."""
    try:
        hdr = doc.header
        hdr["$UCSORG"] = (0.0, 0.0, 0.0)
        hdr["$UCSXDIR"] = (1.0, 0.0, 0.0)
        hdr["$UCSYDIR"] = (0.0, 1.0, 0.0)
        hdr["$UCSNAME"] = ""
        hdr["$PUCSORG"] = (0.0, 0.0, 0.0)
        hdr["$PUCSXDIR"] = (1.0, 0.0, 0.0)
        hdr["$PUCSYDIR"] = (0.0, 1.0, 0.0)
        hdr["$PUCSNAME"] = ""
        hdr["$WORLDVIEW"] = 1
    except Exception:
        pass


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
