from __future__ import annotations

import json
import statistics
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
    max_chainage = max((float(s.chainage_m) for s in sections), default=0.0)
    centerline_len = float(centerline.length)

    # Many student datasets carry chainage in meters while centerline map units
    # may be in a different scale/CRS. If lengths are mismatched, place sections
    # by normalized chainage fraction to avoid collapsing at one endpoint.
    use_normalized_chainage = (
        max_chainage > 0.0
        and centerline_len > 0.0
        and (centerline_len < 0.9 * max_chainage or centerline_len > 1.1 * max_chainage)
    )

    mapped_chainages: list[float] = []
    for s in sections:
        ch = float(s.chainage_m)
        if use_normalized_chainage and max_chainage > 0.0 and centerline_len > 0.0:
            frac = ch / max_chainage
            # Avoid exact endpoints where tangent/normal can become unstable.
            frac = max(0.001, min(0.999, frac))
            ch = frac * centerline_len
            if "chainage:normalized_to_centerline" not in s.provenance:
                s.provenance.append("chainage:normalized_to_centerline")
        mapped_chainages.append(ch)

    diffs = [mapped_chainages[i + 1] - mapped_chainages[i] for i in range(len(mapped_chainages) - 1)]
    positive_diffs = [d for d in diffs if d > 0]
    typical_spacing = statistics.median(positive_diffs) if positive_diffs else 25.0
    tangent_delta = max(1.0, 0.35 * typical_spacing)

    for i, s in enumerate(sections):
        chainage_for_line = mapped_chainages[i]

        pt = centerline.get_point_at_chainage(chainage_for_line)
        tx, ty = centerline.get_tangent_at_chainage(chainage_for_line, delta=tangent_delta)
        nx, ny = (-ty, tx)
        offsets = [p.station for p in s.points]
        width = max(offsets) - min(offsets) if len(offsets) >= 2 else 100.0
        width = max(width, 100.0)

        prev_spacing = mapped_chainages[i] - mapped_chainages[i - 1] if i > 0 else typical_spacing
        next_spacing = (
            mapped_chainages[i + 1] - mapped_chainages[i] if i < len(mapped_chainages) - 1 else typical_spacing
        )
        local_spacing = min(v for v in [prev_spacing, next_spacing, typical_spacing] if v > 0)
        max_half_by_spacing = max(12.0, 0.45 * local_spacing)
        half = min(width / 2.0, max_half_by_spacing)
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
