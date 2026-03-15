from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from src.models import CrossSection, SectionPoint


_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.\d+|\d+\.|\.\d+|\d+)")
_CHAINAGE_DESC_RE = re.compile(r"chainage\s+([-+]?(?:\d+\.\d+|\d+))\s*m", re.IGNORECASE)


def parse_hecras_project(project_dir: Path) -> dict[str, object]:
    project_dir = project_dir.resolve()
    prj_path = _pick_project_file(project_dir)
    project_stem = prj_path.stem

    prj_meta = _parse_key_value_file(prj_path)
    current_plan_ref = str(prj_meta.get("Current Plan", "")).strip()
    plan_path = _resolve_project_ref(project_dir, project_stem, current_plan_ref) or _pick_latest(project_dir, "*.p[0-9][0-9]")
    plan_meta = _parse_key_value_file(plan_path) if plan_path else {}

    geom_ref = str(plan_meta.get("Geom File") or prj_meta.get("Geom File") or "").strip()
    flow_ref = str(plan_meta.get("Flow File") or prj_meta.get("Flow File") or "").strip()
    unsteady_ref = str(plan_meta.get("Unsteady File") or prj_meta.get("Unsteady File") or "").strip()

    geom_path = _resolve_project_ref(project_dir, project_stem, geom_ref)
    flow_path = _resolve_project_ref(project_dir, project_stem, flow_ref)
    unsteady_path = _resolve_project_ref(project_dir, project_stem, unsteady_ref)

    geometry_summary = parse_geometry_file(geom_path) if geom_path and geom_path.exists() else _empty_geometry_summary()
    flow_summary = parse_steady_flow_file(flow_path) if flow_path and flow_path.exists() else {}

    inventory = build_project_inventory(project_dir)
    source_snapshot = snapshot_project_tree(project_dir)

    model_types: list[str] = []
    if flow_path and flow_path.exists():
        model_types.append("steady")
    if unsteady_path and unsteady_path.exists():
        model_types.append("unsteady")
    if list(project_dir.glob("*.s[0-9][0-9]")):
        model_types.append("sediment_or_quasi_unsteady")
    if not model_types:
        model_types.append("unknown")

    return {
        "project_dir": str(project_dir),
        "project_name": project_dir.name,
        "project_file": str(prj_path),
        "project_stem": project_stem,
        "project_title": str(prj_meta.get("Proj Title", prj_path.name)),
        "current_plan_ref": current_plan_ref,
        "active_plan_file": str(plan_path) if plan_path else "",
        "active_plan_summary": _summarize_plan(plan_meta, plan_path),
        "geometry_file": str(geom_path) if geom_path else "",
        "steady_flow_file": str(flow_path) if flow_path else "",
        "unsteady_flow_file": str(unsteady_path) if unsteady_path else "",
        "model_types": model_types,
        "inventory": inventory,
        "geometry_summary": geometry_summary,
        "flow_summary": flow_summary,
        "source_snapshot": source_snapshot,
    }


def build_project_inventory(project_dir: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    extension_counts: dict[str, int] = {}
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        ext = path.suffix.lower()
        extension_counts[ext] = extension_counts.get(ext, 0) + 1
        files.append(
            {
                "relative_path": rel,
                "size_bytes": int(path.stat().st_size),
                "extension": ext,
            }
        )
    return {
        "file_count": len(files),
        "extension_counts": extension_counts,
        "files": files,
    }


def snapshot_project_tree(project_dir: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    file_rows: list[dict[str, object]] = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        payload = path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        file_rows.append(
            {
                "relative_path": rel,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "project_dir": str(project_dir),
        "file_count": len(file_rows),
        "tree_sha256": digest.hexdigest(),
        "files": file_rows,
    }


def parse_geometry_file(geom_path: Path) -> dict[str, object]:
    lines = geom_path.read_text(encoding="cp1252", errors="ignore").splitlines()
    reach_name = ""
    river_name = ""
    reach_coords: list[tuple[float, float]] = []
    sections: list[CrossSection] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip()
        if line.startswith("River Reach="):
            river_name, reach_name = _parse_river_reach(line)
        elif line.startswith("Reach XY="):
            reach_coords, idx = _parse_reach_xy(lines, idx)
        elif line.startswith("Type RM Length L Ch R ="):
            section, idx = _parse_section_block(lines, idx, river_name=river_name, reach_name=reach_name)
            if section is not None:
                sections.append(section)
            continue
        idx += 1

    _assign_section_chainages(sections)

    return {
        "geometry_file": str(geom_path),
        "river_name": river_name,
        "reach_name": reach_name,
        "reach_coords": reach_coords,
        "cross_section_count": len(sections),
        "sections": sections,
    }


def write_project_geometry_outputs(geometry_summary: dict[str, object], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sections = list(geometry_summary.get("sections", []))
    section_json = out_dir / "cross_sections_from_project.json"
    section_csv = out_dir / "cross_sections_from_project.csv"
    station_map_csv = out_dir / "station_map.csv"
    summary_json = out_dir / "geometry_summary.json"

    payload = [_cross_section_to_payload(sec) for sec in sections]
    section_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rows: list[dict[str, float | str]] = []
    map_rows: list[dict[str, float]] = []
    for sec in sections:
        map_rows.append({"chainage_m": float(sec.chainage_m), "river_station": float(sec.river_station)})
        for point in sec.points:
            rows.append(
                {
                    "chainage_m": float(sec.chainage_m),
                    "river_station": float(sec.river_station),
                    "offset_m": float(point.station),
                    "elevation_m": float(point.elevation),
                    "left_bank_station": float(sec.left_bank_station),
                    "right_bank_station": float(sec.right_bank_station),
                    "mannings_left": float(sec.mannings_left),
                    "mannings_channel": float(sec.mannings_channel),
                    "mannings_right": float(sec.mannings_right),
                    "reach_length_left": float(sec.reach_length_left or 0.0),
                    "reach_length_channel": float(sec.reach_length_channel or 0.0),
                    "reach_length_right": float(sec.reach_length_right or 0.0),
                }
            )

    pd.DataFrame(rows).to_csv(section_csv, index=False)
    pd.DataFrame(map_rows).drop_duplicates().sort_values("chainage_m").to_csv(station_map_csv, index=False)
    summary_json.write_text(json.dumps(_geometry_summary_payload(geometry_summary), indent=2), encoding="utf-8")
    return {
        "sections_json": section_json,
        "sections_csv": section_csv,
        "station_map_csv": station_map_csv,
        "summary_json": summary_json,
    }


def parse_steady_flow_file(flow_path: Path) -> dict[str, object]:
    lines = flow_path.read_text(encoding="cp1252", errors="ignore").splitlines()
    summary: dict[str, object] = {
        "flow_file": str(flow_path),
        "title": "",
        "profile_names": [],
        "flow_locations": [],
        "boundary_conditions": {},
    }
    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip()
        if line.startswith("Flow Title="):
            summary["title"] = line.split("=", 1)[1].strip()
        elif line.startswith("Profile Names="):
            raw = line.split("=", 1)[1].strip()
            summary["profile_names"] = [name for name in raw.split() if name]
        elif line.startswith("River Rch & RM="):
            loc = _parse_flow_location(line)
            if idx + 1 < len(lines):
                vals = _extract_floats(lines[idx + 1])
                if vals:
                    loc["flow_values_cms"] = vals
            casted = summary["flow_locations"]
            if isinstance(casted, list):
                casted.append(loc)
            idx += 1
        elif line.startswith("Boundary for River Rch & Prof#="):
            summary["boundary_conditions"] = _parse_boundary_conditions(lines, idx)
        idx += 1
    return summary


def build_station_map_df(geometry_summary: dict[str, object]) -> pd.DataFrame:
    sections = list(geometry_summary.get("sections", []))
    rows = [{"chainage_m": float(sec.chainage_m), "river_station": float(sec.river_station)} for sec in sections]
    if not rows:
        return pd.DataFrame(columns=["chainage_m", "river_station"])
    return pd.DataFrame(rows).drop_duplicates().sort_values("chainage_m").reset_index(drop=True)


def build_flow_payload_from_summary(project_meta: dict[str, object], out_path: Path) -> Path:
    flow_summary = project_meta.get("flow_summary", {}) if isinstance(project_meta.get("flow_summary", {}), dict) else {}
    flow_locations = flow_summary.get("flow_locations", []) if isinstance(flow_summary, dict) else []
    upstream = 0.0
    tributary = 0.0
    upstream_station = 0.0
    tributary_station = 0.0
    if isinstance(flow_locations, list) and flow_locations:
        first = flow_locations[0]
        if isinstance(first, dict):
            upstream_station = float(first.get("river_station", 0.0))
            upstream_vals = first.get("flow_values_cms", [])
            if isinstance(upstream_vals, list) and upstream_vals:
                upstream = float(upstream_vals[0])
        if len(flow_locations) > 1:
            second = flow_locations[1]
            if isinstance(second, dict):
                tributary_station = float(second.get("river_station", 0.0))
                second_vals = second.get("flow_values_cms", [])
                if isinstance(second_vals, list) and second_vals:
                    tributary = float(second_vals[0])

    bc = flow_summary.get("boundary_conditions", {}) if isinstance(flow_summary, dict) else {}
    payload = {
        "upstream_flow_cms": upstream,
        "tributary_flow_cms": tributary,
        "upstream_station_hint": upstream_station,
        "tributary_station_hint": tributary_station,
        "upstream_normal_depth_slope": float(bc.get("upstream_slope", 0.0) or 0.0),
        "downstream_normal_depth_slope": float(bc.get("downstream_slope", 0.0) or 0.0),
        "source": "existing_project_extract",
        "project_name": str(project_meta.get("project_name", "")),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def _pick_project_file(project_dir: Path) -> Path:
    prjs = sorted(project_dir.glob("*.prj"))
    if not prjs:
        raise FileNotFoundError(f"No HEC-RAS project file (*.prj) found in {project_dir}")
    return prjs[0]


def _pick_latest(project_dir: Path, pattern: str) -> Path | None:
    matches = sorted(project_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _parse_key_value_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="cp1252", errors="ignore").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _resolve_project_ref(project_dir: Path, project_stem: str, ref: str) -> Path | None:
    ref = ref.strip()
    if not ref:
        return None
    direct = project_dir / ref
    if direct.exists():
        return direct
    if not ref.startswith(".") and not ref.lower().startswith(project_stem.lower() + "."):
        candidate = project_dir / f"{project_stem}.{ref}"
        if candidate.exists():
            return candidate
    suffixed = project_dir / f"{project_stem}{ref}"
    if suffixed.exists():
        return suffixed
    return direct


def _summarize_plan(plan_meta: dict[str, str], plan_path: Path | None) -> dict[str, object]:
    return {
        "plan_file": str(plan_path) if plan_path else "",
        "title": str(plan_meta.get("Plan Title", "")),
        "short_identifier": str(plan_meta.get("Short Identifier", "")),
        "geometry_ref": str(plan_meta.get("Geom File", "")),
        "flow_ref": str(plan_meta.get("Flow File", "")),
        "flow_regime": _detect_flow_regime(plan_meta, plan_path),
    }


def _detect_flow_regime(plan_meta: dict[str, str], plan_path: Path | None = None) -> str:
    lowered = {k.lower(): v.lower() for k, v in plan_meta.items()}
    if any("mixed flow" in v for v in lowered.values()):
        return "mixed"
    if any("supercritical" in v for v in lowered.values()):
        return "supercritical"
    if any("subcritical" in v for v in lowered.values()):
        return "subcritical"
    if plan_path and plan_path.exists():
        text = plan_path.read_text(encoding="cp1252", errors="ignore").lower()
        if "mixed flow" in text:
            return "mixed"
        if "supercritical flow" in text:
            return "supercritical"
        if "subcritical flow" in text:
            return "subcritical"
    return "unknown"


def _parse_river_reach(line: str) -> tuple[str, str]:
    raw = line.split("=", 1)[1]
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return raw.strip(), ""


def _parse_reach_xy(lines: list[str], idx: int) -> tuple[list[tuple[float, float]], int]:
    count_vals = _extract_floats(lines[idx])
    target_pairs = int(count_vals[0]) if count_vals else 0
    coords: list[tuple[float, float]] = []
    idx += 1
    while idx < len(lines) and len(coords) < target_pairs:
        line = lines[idx]
        if "=" in line and not line.lstrip().startswith(("-", "+", ".")):
            break
        vals = _extract_floats(line)
        while len(vals) >= 2:
            coords.append((vals[0], vals[1]))
            vals = vals[2:]
            if len(coords) >= target_pairs:
                break
        idx += 1
    return coords, idx - 1


def _parse_section_block(
    lines: list[str],
    idx: int,
    river_name: str,
    reach_name: str,
) -> tuple[CrossSection | None, int]:
    header_nums = _extract_floats(lines[idx])
    if len(header_nums) < 5:
        return None, idx + 1

    river_station = float(header_nums[1])
    reach_length_left = float(header_nums[2])
    reach_length_channel = float(header_nums[3])
    reach_length_right = float(header_nums[4])

    description_lines: list[str] = []
    point_vals: list[float] = []
    mann_vals: list[float] = []
    left_bank = None
    right_bank = None
    idx += 1
    while idx < len(lines):
        line = lines[idx].rstrip()
        if line.startswith("Type RM Length L Ch R ="):
            idx -= 1
            break
        if line.startswith("BEGIN DESCRIPTION:"):
            idx += 1
            while idx < len(lines) and not lines[idx].startswith("END DESCRIPTION:"):
                description_lines.append(lines[idx].strip())
                idx += 1
        elif line.startswith("#Sta/Elev="):
            idx += 1
            while idx < len(lines):
                probe = lines[idx].rstrip()
                if probe.startswith("#Mann=") or probe.startswith("Bank Sta=") or probe.startswith("Type RM Length L Ch R ="):
                    idx -= 1
                    break
                if probe.startswith("XS Rating Curve") or probe.startswith("XS HTab") or probe.startswith("Exp/Cntr="):
                    idx -= 1
                    break
                point_vals.extend(_extract_floats(probe))
                idx += 1
        elif line.startswith("#Mann="):
            idx += 1
            while idx < len(lines):
                probe = lines[idx].rstrip()
                if probe.startswith("Bank Sta=") or probe.startswith("Type RM Length L Ch R ="):
                    idx -= 1
                    break
                if probe.startswith("XS Rating Curve") or probe.startswith("XS HTab") or probe.startswith("Exp/Cntr="):
                    idx -= 1
                    break
                mann_vals.extend(_extract_floats(probe))
                idx += 1
        elif line.startswith("Bank Sta="):
            bank_vals = _extract_floats(line)
            if len(bank_vals) >= 2:
                left_bank = float(bank_vals[0])
                right_bank = float(bank_vals[1])
        idx += 1

    points = _points_from_values(point_vals)
    if len(points) < 2:
        return None, idx

    mann_left, mann_channel, mann_right = _mannings_from_values(mann_vals)
    if left_bank is None:
        left_bank = points[0].station
    if right_bank is None:
        right_bank = points[-1].station

    chainage_hint = _chainage_from_description(description_lines)
    section = CrossSection(
        chainage_m=float(chainage_hint if chainage_hint is not None else 0.0),
        river_station=river_station,
        river_name=river_name or "Unknown River",
        reach_name=reach_name or "Unknown Reach",
        cutline=[],
        points=points,
        left_bank_station=float(left_bank),
        right_bank_station=float(right_bank),
        mannings_left=float(mann_left),
        mannings_channel=float(mann_channel),
        mannings_right=float(mann_right),
        reach_length_left=reach_length_left,
        reach_length_channel=reach_length_channel,
        reach_length_right=reach_length_right,
        provenance=["hec_ras_project"],
        confidence=0.95,
    )
    return section, idx


def _chainage_from_description(lines: list[str]) -> float | None:
    for line in lines:
        match = _CHAINAGE_DESC_RE.search(line)
        if match:
            return float(match.group(1))
    return None


def _points_from_values(values: list[float]) -> list[SectionPoint]:
    usable = values[:-1] if len(values) % 2 else values
    points: list[SectionPoint] = []
    for idx in range(0, len(usable), 2):
        points.append(
            SectionPoint(
                station=float(usable[idx]),
                elevation=float(usable[idx + 1]),
                source="hec_ras_project",
            )
        )
    return points


def _mannings_from_values(values: list[float]) -> tuple[float, float, float]:
    if len(values) >= 8:
        return float(values[1]), float(values[4]), float(values[7])
    return 0.06, 0.04, 0.06


def _assign_section_chainages(sections: list[CrossSection]) -> None:
    if not sections:
        return
    if all(sec.chainage_m > 0 for sec in sections[1:]) or any(sec.chainage_m != 0 for sec in sections):
        sections.sort(key=lambda sec: sec.chainage_m)
        return

    stations = [sec.river_station for sec in sections]
    descending = stations == sorted(stations, reverse=True)
    max_station = max(stations)
    min_station = min(stations)
    for sec in sections:
        sec.chainage_m = float(max_station - sec.river_station if descending else sec.river_station - min_station)
    sections.sort(key=lambda sec: sec.chainage_m)


def _parse_flow_location(line: str) -> dict[str, object]:
    raw = line.split("=", 1)[1]
    parts = [p.strip() for p in raw.split(",")]
    station = _extract_floats(parts[-1])[0] if parts else 0.0
    return {
        "river_name": parts[0] if len(parts) > 0 else "",
        "reach_name": parts[1] if len(parts) > 1 else "",
        "river_station": station,
    }


def _parse_boundary_conditions(lines: list[str], idx: int) -> dict[str, object]:
    out: dict[str, object] = {}
    probe = idx + 1
    while probe < len(lines):
        line = lines[probe].rstrip()
        if line.startswith("Boundary for River Rch & Prof#=") or line.startswith("River Rch & RM="):
            break
        if line.startswith("Up Type="):
            vals = _extract_floats(line)
            out["upstream_type"] = int(vals[0]) if vals else 0
        elif line.startswith("Up Slope="):
            vals = _extract_floats(line)
            out["upstream_slope"] = float(vals[0]) if vals else 0.0
        elif line.startswith("Dn Type="):
            vals = _extract_floats(line)
            out["downstream_type"] = int(vals[0]) if vals else 0
        elif line.startswith("Dn Slope="):
            vals = _extract_floats(line)
            out["downstream_slope"] = float(vals[0]) if vals else 0.0
        probe += 1
    return out


def _cross_section_to_payload(section: CrossSection) -> dict[str, object]:
    return {
        "chainage_m": float(section.chainage_m),
        "river_station": float(section.river_station),
        "river_name": section.river_name,
        "reach_name": section.reach_name,
        "cutline": section.cutline,
        "left_bank_station": float(section.left_bank_station),
        "right_bank_station": float(section.right_bank_station),
        "mannings_left": float(section.mannings_left),
        "mannings_channel": float(section.mannings_channel),
        "mannings_right": float(section.mannings_right),
        "reach_length_left": float(section.reach_length_left or 0.0),
        "reach_length_channel": float(section.reach_length_channel or 0.0),
        "reach_length_right": float(section.reach_length_right or 0.0),
        "confidence": float(section.confidence),
        "provenance": list(section.provenance),
        "points": [
            {
                "station": float(point.station),
                "elevation": float(point.elevation),
                "source": point.source,
            }
            for point in section.points
        ],
    }


def _geometry_summary_payload(geometry_summary: dict[str, object]) -> dict[str, object]:
    sections = list(geometry_summary.get("sections", []))
    return {
        "geometry_file": str(geometry_summary.get("geometry_file", "")),
        "river_name": str(geometry_summary.get("river_name", "")),
        "reach_name": str(geometry_summary.get("reach_name", "")),
        "cross_section_count": int(geometry_summary.get("cross_section_count", 0)),
        "reach_coord_count": len(list(geometry_summary.get("reach_coords", []))),
        "river_stations": [float(sec.river_station) for sec in sections],
        "chainages_m": [float(sec.chainage_m) for sec in sections],
    }


def _empty_geometry_summary() -> dict[str, object]:
    return {
        "geometry_file": "",
        "river_name": "",
        "reach_name": "",
        "reach_coords": [],
        "cross_section_count": 0,
        "sections": [],
    }


def _extract_floats(text: str) -> list[float]:
    return [float(match) for match in _FLOAT_RE.findall(text)]
