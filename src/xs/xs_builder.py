from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from shapely.geometry import LineString

from src.geo.centerline import load_centerline
from src.xs.banks import suggest_banks
from src.xs.xs_loader import load_cross_sections_from_csv


def build_cross_sections(
    centerline_geojson: Path,
    xs_csv: Path,
    river_name: str,
    reach_name: str,
    n_channel: float,
    n_floodplain: float,
    out_dir: Path = Path("data/processed"),
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    centerline = load_centerline(centerline_geojson)
    sections = load_cross_sections_from_csv(xs_csv, river_name, reach_name, n_channel, n_floodplain)

    for s in sections:
        pt = centerline.get_point_at_chainage(s.chainage_m)
        nx, ny = centerline.get_normal_at_chainage(s.chainage_m)
        offsets = [p.station for p in s.points]
        width = max(offsets) - min(offsets) if len(offsets) >= 2 else 100.0
        width = max(width, 100.0)
        half = width / 2.0
        x0 = pt.x - nx * half
        y0 = pt.y - ny * half
        x1 = pt.x + nx * half
        y1 = pt.y + ny * half
        s.cutline = [(x0, y0), (x1, y1)]

        section_df = pd.DataFrame(
            {"offset_m": [p.station for p in s.points], "elevation_m": [p.elevation for p in s.points]}
        )
        left_bank, right_bank, confidence = suggest_banks(section_df)
        s.left_bank_station = left_bank
        s.right_bank_station = right_bank
        s.confidence = confidence
        if "bank:auto" not in s.provenance:
            s.provenance.append("bank:auto")

    out_json = out_dir / "cross_sections_final.json"
    out_json.write_text(json.dumps([s.model_dump() for s in sections], indent=2), encoding="utf-8")
    _write_flat_csv(sections, out_dir / "cross_sections_final.csv")
    return out_json


def _write_flat_csv(sections: list, path: Path) -> None:
    rows = []
    for s in sections:
        for p in s.points:
            rows.append(
                {
                    "chainage_m": s.chainage_m,
                    "river_station": s.river_station,
                    "offset_m": p.station,
                    "elevation_m": p.elevation,
                    "left_bank_station": s.left_bank_station,
                    "right_bank_station": s.right_bank_station,
                    "cutline_wkt": LineString(s.cutline).wkt if s.cutline else "",
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)
