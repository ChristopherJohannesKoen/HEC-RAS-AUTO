from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.post.extract_sections import extract_required_sections


def test_extract_required_sections_prefers_profile_values(tmp_path: Path) -> None:
    xs = pd.DataFrame(
        [
            {"chainage_m": 0.0, "offset_m": 0.0, "elevation_m": 1.0},
            {"chainage_m": 0.0, "offset_m": 10.0, "elevation_m": 2.0},
            {"chainage_m": 1500.0, "offset_m": 0.0, "elevation_m": 2.0},
            {"chainage_m": 1500.0, "offset_m": 10.0, "elevation_m": 3.0},
            {"chainage_m": 3905.0, "offset_m": 0.0, "elevation_m": 3.0},
            {"chainage_m": 3905.0, "offset_m": 10.0, "elevation_m": 4.0},
        ]
    )
    xs_csv = tmp_path / "xs.csv"
    xs.to_csv(xs_csv, index=False)

    profiles = pd.DataFrame(
        [
            {"chainage_m": 0.0, "water_level_m": 5.0, "energy_level_m": 5.2, "velocity_mps": 2.0},
            {"chainage_m": 1500.0, "water_level_m": 6.0, "energy_level_m": 6.2, "velocity_mps": 2.1},
            {"chainage_m": 3905.0, "water_level_m": 7.0, "energy_level_m": 7.2, "velocity_mps": 2.2},
        ]
    )
    profile_csv = tmp_path / "profiles.csv"
    profiles.to_csv(profile_csv, index=False)

    out = extract_required_sections(
        cross_sections_csv=xs_csv,
        run_id="r1",
        profile_values_csv=profile_csv,
        output_root=tmp_path / "outputs",
    )
    result = pd.read_csv(out)
    assert "hydraulic_source" in result.columns
    assert set(result["hydraulic_source"].unique()) == {"hdf_profile"}
