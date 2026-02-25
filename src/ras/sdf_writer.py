from __future__ import annotations

import json
from pathlib import Path


def write_rasimport_sdf(
    sections_json: Path,
    out_path: Path,
    river_name: str,
    reach_name: str,
) -> Path:
    sections = json.loads(sections_json.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("BEGIN HEADER:")
    lines.append("  UNITS: METRIC")
    lines.append("END HEADER:")
    lines.append("BEGIN STREAM NETWORK:")
    lines.append(f"  STREAM ID: {river_name}")
    lines.append(f"  REACH ID: {reach_name}")
    lines.append("END STREAM NETWORK:")
    lines.append("BEGIN CROSS-SECTIONS:")
    for sec in sections:
        lines.extend(_section_to_sdf(sec))
    lines.append("END CROSS-SECTIONS:")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _section_to_sdf(sec: dict) -> list[str]:
    cutline = sec.get("cutline", [])
    points = sec.get("points", [])
    out = [
        "  BEGIN XS:",
        f"    RIVER STATION: {sec['river_station']}",
        f"    CHAINAGE: {sec['chainage_m']}",
        f"    LEFT BANK: {sec['left_bank_station']}",
        f"    RIGHT BANK: {sec['right_bank_station']}",
        "    CUT LINE:",
    ]
    for xy in cutline:
        out.append(f"      {xy[0]},{xy[1]}")
    out.append("    STATION-ELEVATION:")
    for p in points:
        out.append(f"      {p['station']},{p['elevation']}")
    out.append("  END XS:")
    return out
