from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.scenarios.scenario_compare import compare_runs, compare_scenario2_tiers


def _write_metrics(path: Path, run_id: str, wse: float, v: float, flood_ha: float, energy: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "run_id": run_id,
                "max_wse_m": wse,
                "max_wse_chainage_m": 1500.0,
                "max_energy_level_m": energy,
                "max_energy_chainage_m": 1500.0,
                "max_velocity_mps": v,
                "max_velocity_chainage_m": 1500.0,
                "flood_extent_area_m2": flood_ha * 10000.0,
                "flood_extent_area_ha": flood_ha,
            }
        ]
    ).to_csv(path, index=False)


def _write_profile(path: Path, wse_start: float, wse_end: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"chainage_m": 0.0, "water_level_m": wse_start},
            {"chainage_m": 1500.0, "water_level_m": (wse_start + wse_end) / 2.0},
            {"chainage_m": 3905.0, "water_level_m": wse_end},
        ]
    ).to_csv(path, index=False)


def test_compare_runs_includes_flood_extent_delta(tmp_path: Path) -> None:
    out = tmp_path / "outputs"
    _write_metrics(out / "base" / "tables" / "metrics.csv", "base", wse=10.0, v=2.0, flood_ha=5.0, energy=10.5)
    _write_metrics(out / "s2" / "tables" / "metrics.csv", "s2", wse=11.0, v=2.2, flood_ha=5.8, energy=11.4)
    _write_profile(out / "base" / "artifacts" / "hdf_profiles.csv", 10.0, 9.0)
    _write_profile(out / "s2" / "artifacts" / "hdf_profiles.csv", 11.0, 10.0)

    table, profile = compare_runs("base", "s2", outputs_root=out)
    assert table.exists()
    assert profile.exists()
    df = pd.read_csv(table)
    assert "flood_extent_area_ha" in set(df["metric"].tolist())


def test_compare_scenario2_tiers_builds_combined_artifacts(tmp_path: Path) -> None:
    out = tmp_path / "outputs"
    _write_metrics(out / "base" / "tables" / "metrics.csv", "base", wse=10.0, v=2.0, flood_ha=5.0, energy=10.5)
    _write_profile(out / "base" / "artifacts" / "hdf_profiles.csv", 10.0, 9.0)

    tiers = {
        "lenient": ("base_scenario_2_lenient", 10.6, 2.1, 5.3, 11.1),
        "average": ("base_scenario_2_average", 11.1, 2.3, 5.9, 11.6),
        "conservative": ("base_scenario_2_conservative", 12.0, 2.6, 6.8, 12.5),
    }
    tier_runs: dict[str, str] = {}
    for tier, (rid, wse, vel, flood_ha, energy) in tiers.items():
        tier_runs[tier] = rid
        _write_metrics(out / rid / "tables" / "metrics.csv", rid, wse=wse, v=vel, flood_ha=flood_ha, energy=energy)
        _write_profile(out / rid / "artifacts" / "hdf_profiles.csv", wse, wse - 1.0)

    paths = compare_scenario2_tiers(base_run="base", tier_runs=tier_runs, outputs_root=out)
    assert Path(paths["tier_comparison"]).exists()
    assert Path(paths["tier_envelope"]).exists()
    assert Path(paths["tier_overlay_profile"]).exists()

    comp = pd.read_csv(paths["tier_comparison"])
    assert set(comp["tier"].tolist()) == {"lenient", "average", "conservative"}
    assert "delta_flood_extent_area_ha" in comp.columns
