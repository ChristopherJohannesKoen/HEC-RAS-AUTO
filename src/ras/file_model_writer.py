from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString

from src.models import CrossSection


def stage_text_model_files(
    run_project_dir: Path,
    sections_json: Path,
    centerline_geojson: Path,
    flow_json: Path,
    river_name: str,
    reach_name: str,
) -> dict[str, Path]:
    """Write run-local HEC-RAS text inputs (g01/f01 + p01/prj refs)."""
    sections = _load_sections(sections_json)
    geom_path = run_project_dir / "Meerlustkloof.g01"
    flow_path = run_project_dir / "Meerlustkloof.f01"
    plan_path = run_project_dir / "Meerlustkloof.p01"
    project_path = run_project_dir / "Meerlustkloof.prj"

    write_geometry_file(
        sections=sections,
        centerline_geojson=centerline_geojson,
        out_path=geom_path,
        river_name=river_name,
        reach_name=reach_name,
    )
    write_steady_flow_file(
        flow_json=flow_json,
        out_path=flow_path,
        river_name=river_name,
        reach_name=reach_name,
    )
    patch_plan_file(plan_path=plan_path, geom_file="g01", flow_file="f01")
    patch_project_file(project_path=project_path, plan_file="p01", geom_file="g01", flow_file="f01")

    return {
        "geometry_file": geom_path,
        "flow_file": flow_path,
        "plan_file": plan_path,
        "project_file": project_path,
    }


def write_geometry_file(
    sections: list[CrossSection],
    centerline_geojson: Path,
    out_path: Path,
    river_name: str,
    reach_name: str,
) -> Path:
    sections = sorted(sections, key=lambda s: s.river_station, reverse=True)
    reach_coords = _load_centerline_coords(centerline_geojson)
    if len(reach_coords) < 2:
        raise ValueError("Centerline must contain at least two coordinates to write geometry.")

    now = datetime.now().strftime("%b/%d/%Y %H:%M:%S")
    lines: list[str] = [
        "Geom Title=Auto Generated Geometry",
        "Program Version=6.60",
        "Viewing Rectangle= 0 , 1 , 1 , 0 ",
        "",
        f"River Reach={_fmt_name(river_name)},{_fmt_name(reach_name)}",
        f"Reach XY= {len(reach_coords)} ",
    ]
    lines.extend(_format_reach_xy_lines(reach_coords))
    mid = reach_coords[len(reach_coords) // 2]
    lines.append(f"Rch Text X Y={mid[0]:.6f},{mid[1]:.6f}")
    lines.append("Reverse River Text= 0 ")
    lines.append("")

    for idx, sec in enumerate(sections):
        length_l = float(sec.reach_length_left or 0.0)
        length_c = float(sec.reach_length_channel or 0.0)
        length_r = float(sec.reach_length_right or 0.0)
        if idx == len(sections) - 1:
            length_l = length_c = length_r = 0.0

        points = sorted(sec.points, key=lambda p: p.station)
        station_min = float(points[0].station)
        station_pairs = [(float(p.station) - station_min, float(p.elevation)) for p in points]
        left_bank = float(sec.left_bank_station) - station_min
        right_bank = float(sec.right_bank_station) - station_min
        first_station = station_pairs[0][0]
        last_station = station_pairs[-1][0]
        left_bank = max(first_station, min(left_bank, last_station))
        right_bank = max(left_bank, min(right_bank, last_station))
        cut = sec.cutline if sec.cutline else [(0.0, 0.0), (1.0, 1.0)]
        if len(cut) < 2:
            cut = [cut[0], cut[0]]
        cut_coords = [(float(x), float(y)) for x, y in cut]

        lines.append(
            "Type RM Length L Ch R = 1 ,"
            f"{_fmt_rm(sec.river_station)},"
            f"{_fmt_len(length_l)},{_fmt_len(length_c)},{_fmt_len(length_r)}"
        )
        lines.append("BEGIN DESCRIPTION:")
        lines.append(f"Auto-generated cross section at chainage {sec.chainage_m:.3f} m")
        lines.append("END DESCRIPTION:")
        lines.append(f"XS GIS Cut Line={len(cut_coords)}")
        lines.extend(_format_reach_xy_lines(cut_coords))
        lines.append(f"Node Last Edited Time={now}")
        lines.append(f"#Sta/Elev= {len(station_pairs)} ")
        lines.extend(_format_sta_elev_lines(station_pairs))
        lines.append("#Mann= 3 , 0 , 0 ")
        lines.append(
            f"{first_station:>8.3f}{sec.mannings_left:>8.3f}{0:>8}"
            f"{left_bank:>8.3f}{sec.mannings_channel:>8.3f}{0:>8}"
            f"{right_bank:>8.3f}{sec.mannings_right:>8.3f}{0:>8}"
        )
        lines.append(f"Bank Sta={left_bank:.3f},{right_bank:.3f}")
        lines.append("XS Rating Curve= 0 ,0")
        lines.append("Exp/Cntr=0.3,0.1")
        lines.append("")

    lines.extend(
        [
            "Use User Specified Reach Order=0",
            "GIS Units=METRIC",
            "GIS DTM Type=",
            "GIS DTM=",
            "GIS Stream Layer=",
            "GIS Cross Section Layer=",
            "GIS Map Projection=",
            "GIS Projection Zone=",
            "GIS Datum=",
            "GIS Vertical Datum=",
            "GIS Data Extents=,,,",
            "",
            "GIS Ratio Cuts To Invert=-1",
            "GIS Limit At Bridges=0",
            "Composite Channel Slope=5",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="cp1252")
    return out_path


def write_steady_flow_file(
    flow_json: Path,
    out_path: Path,
    river_name: str,
    reach_name: str,
) -> Path:
    payload = json.loads(flow_json.read_text(encoding="utf-8"))
    q_up = float(payload["upstream_flow_cms"])
    q_tr = float(payload["tributary_flow_cms"])
    q_total = q_up + q_tr
    us = float(payload.get("upstream_station_hint") or 3905.0)
    tr = float(payload.get("tributary_station_hint") or 2405.0)
    up_slope = float(payload.get("upstream_normal_depth_slope") or 0.0215)
    dn_slope = float(payload["downstream_normal_depth_slope"])

    river = _fmt_name(river_name)
    reach = _fmt_name(reach_name)
    us_rm = f"{us:>8.3f}"
    tr_rm = f"{tr:>8.3f}"
    lines = [
        "Flow Title=Auto Generated 100-year Flow",
        "Program Version=6.60",
        "Number of Profiles= 1 ",
        "Profile Names=Q100        ",
        f"River Rch & RM={river},{reach},{us_rm}",
        f"{q_up:>8.3f}",
        f"River Rch & RM={river},{reach},{tr_rm}",
        f"{q_total:>8.3f}",
        f"Boundary for River Rch & Prof#={river},{reach}, 1 ",
        "Up Type= 3 ",
        f"Up Slope={up_slope}",
        "Dn Type= 3 ",
        f"Dn Slope={dn_slope}",
        "DSS Import StartDate=",
        "DSS Import StartTime=",
        "DSS Import EndDate=",
        "DSS Import EndTime=",
        "DSS Import GetInterval= 0 ",
        "DSS Import Interval=",
        "DSS Import GetPeak= 0 ",
        "DSS Import FillOption= 0 ",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="cp1252")
    return out_path


def patch_plan_file(plan_path: Path, geom_file: str, flow_file: str) -> None:
    lines = _read_key_lines(plan_path)
    lines = _upsert_key_line(lines, "Geom File", geom_file)
    lines = _upsert_key_line(lines, "Flow File", flow_file)
    lines = _set_flow_regime(lines, "Mixed Flow")
    plan_path.write_text("\n".join(lines) + "\n", encoding="cp1252")


def patch_project_file(project_path: Path, plan_file: str, geom_file: str, flow_file: str) -> None:
    lines = _read_key_lines(project_path)
    lines = _upsert_key_line(lines, "Current Plan", plan_file)
    lines = _upsert_key_line(lines, "Plan File", plan_file)
    lines = _upsert_key_line(lines, "Geom File", geom_file)
    lines = _upsert_key_line(lines, "Flow File", flow_file)
    project_path.write_text("\n".join(lines) + "\n", encoding="cp1252")


def _read_key_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="cp1252", errors="ignore")
    lines = [ln.strip("\r") for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return [ln for ln in lines if ln.strip() != ""]


def _load_sections(sections_json: Path) -> list[CrossSection]:
    raw = json.loads(sections_json.read_text(encoding="utf-8"))
    return [CrossSection.model_validate(item) for item in raw]


def _load_centerline_coords(centerline_geojson: Path) -> list[tuple[float, float]]:
    gdf = gpd.read_file(centerline_geojson)
    if gdf.empty:
        return []
    geom = gdf.geometry.iloc[0]
    if isinstance(geom, MultiLineString):
        geom = max(geom.geoms, key=lambda g: g.length)
    if not isinstance(geom, LineString):
        return []
    coords = list(geom.coords)
    if len(coords) > 200:
        step = max(1, len(coords) // 200)
        coords = coords[::step]
        if coords[-1] != geom.coords[-1]:
            coords.append(geom.coords[-1])
    out: list[tuple[float, float]] = []
    for coord in coords:
        if len(coord) < 2:
            continue
        out.append((float(coord[0]), float(coord[1])))
    return out


def _format_reach_xy_lines(coords: list[tuple[float, float]]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(coords):
        x1, y1 = coords[i]
        if i + 1 < len(coords):
            x2, y2 = coords[i + 1]
            out.append(f"{x1:>16.6f}{y1:>16.6f}{x2:>16.6f}{y2:>16.6f}")
        else:
            out.append(f"{x1:>16.6f}{y1:>16.6f}")
        i += 2
    return out


def _format_sta_elev_lines(sta_elev: list[tuple[float, float]]) -> list[str]:
    lines: list[str] = []
    row: list[str] = []
    for i, (sta, elev) in enumerate(sta_elev, start=1):
        row.append(f"{sta:>8.3f}{elev:>8.3f}")
        if i % 5 == 0:
            lines.append("".join(row))
            row = []
    if row:
        lines.append("".join(row))
    return lines


def _upsert_key_line(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}"
            return lines
    insert_at = 1 if lines else 0
    lines.insert(insert_at, f"{prefix}{value}")
    return lines


def _set_flow_regime(lines: list[str], regime: str) -> list[str]:
    regimes = {"Subcritical Flow", "Supercritical Flow", "Mixed Flow"}
    for i, line in enumerate(lines):
        if line in regimes:
            lines[i] = regime
            return lines
    # Keep regime near the top of the plan definition if missing.
    insert_at = 4 if len(lines) >= 4 else len(lines)
    lines.insert(insert_at, regime)
    return lines


def _fmt_name(name: str) -> str:
    return f"{name:<16}"[:16]


def _fmt_rm(river_station: float) -> str:
    return f"{river_station:<8.3f}".rstrip()


def _fmt_len(value: float) -> str:
    return str(int(round(max(value, 0.0))))
