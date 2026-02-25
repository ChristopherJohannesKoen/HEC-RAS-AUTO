from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models import CrossSection, SectionPoint


def load_cross_sections_from_csv(
    path: Path,
    river_name: str,
    reach_name: str,
    n_channel: float,
    n_floodplain: float,
) -> list[CrossSection]:
    df = pd.read_csv(path)
    required = {"chainage_m", "river_station", "offset_m", "elevation_m"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in cross-section CSV: {sorted(missing)}")

    sections: list[CrossSection] = []
    for (chainage, station), group in df.groupby(["chainage_m", "river_station"], dropna=False):
        g = group.sort_values("offset_m")
        points = [
            SectionPoint(station=float(row.offset_m), elevation=float(row.elevation_m), source="excel")
            for row in g.itertuples()
        ]
        if len(points) < 2:
            continue
        sections.append(
            CrossSection(
                chainage_m=float(chainage),
                river_station=float(station),
                river_name=river_name,
                reach_name=reach_name,
                cutline=[],
                points=points,
                left_bank_station=points[0].station,
                right_bank_station=points[-1].station,
                mannings_left=n_floodplain,
                mannings_channel=n_channel,
                mannings_right=n_floodplain,
                provenance=["excel"],
                confidence=0.5,
            )
        )

    sections.sort(key=lambda s: s.chainage_m)
    return sections
