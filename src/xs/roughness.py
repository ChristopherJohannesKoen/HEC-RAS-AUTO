from __future__ import annotations

from src.models import CrossSection


def apply_baseline_roughness(
    sections: list[CrossSection], n_channel: float, n_floodplain: float
) -> list[CrossSection]:
    for s in sections:
        s.mannings_left = n_floodplain
        s.mannings_channel = n_channel
        s.mannings_right = n_floodplain
        if "roughness:baseline" not in s.provenance:
            s.provenance.append("roughness:baseline")
    return sections
