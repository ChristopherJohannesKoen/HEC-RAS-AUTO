from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models import CrossSection


def assign_reach_lengths(sections: list[CrossSection]) -> list[CrossSection]:
    ordered = sorted(sections, key=lambda s: s.chainage_m)
    for i, section in enumerate(ordered):
        if i == len(ordered) - 1:
            section.reach_length_left = 0.0
            section.reach_length_channel = 0.0
            section.reach_length_right = 0.0
            continue
        d = float(ordered[i + 1].chainage_m - section.chainage_m)
        section.reach_length_left = d
        section.reach_length_channel = d
        section.reach_length_right = d
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
