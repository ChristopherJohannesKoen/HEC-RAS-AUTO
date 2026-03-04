from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def compare_runs(base_run: str, other_run: str, outputs_root: Path = Path("outputs")) -> tuple[Path, Path]:
    base_metrics = outputs_root / base_run / "tables" / "metrics.csv"
    other_metrics = outputs_root / other_run / "tables" / "metrics.csv"
    if not base_metrics.exists() or not other_metrics.exists():
        raise FileNotFoundError("Missing metrics.csv for baseline or scenario run.")

    b = pd.read_csv(base_metrics)
    o = pd.read_csv(other_metrics)
    if b.empty or o.empty:
        raise ValueError("Metrics missing content for comparison.")

    row_b = b.iloc[0]
    row_o = o.iloc[0]
    comp = pd.DataFrame(
        [
            {
                "metric": "max_wse_m",
                "baseline": row_b["max_wse_m"],
                "scenario": row_o["max_wse_m"],
                "delta": row_o["max_wse_m"] - row_b["max_wse_m"],
            },
            {
                "metric": "max_energy_level_m",
                "baseline": _num(row_b, "max_energy_level_m"),
                "scenario": _num(row_o, "max_energy_level_m"),
                "delta": _num(row_o, "max_energy_level_m") - _num(row_b, "max_energy_level_m"),
            },
            {
                "metric": "max_velocity_mps",
                "baseline": row_b["max_velocity_mps"],
                "scenario": row_o["max_velocity_mps"],
                "delta": row_o["max_velocity_mps"] - row_b["max_velocity_mps"],
            },
            {
                "metric": "flood_extent_area_ha",
                "baseline": _num(row_b, "flood_extent_area_ha"),
                "scenario": _num(row_o, "flood_extent_area_ha"),
                "delta": _num(row_o, "flood_extent_area_ha") - _num(row_b, "flood_extent_area_ha"),
            },
        ]
    )
    out_dir = outputs_root / other_run / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / "comparison_table.csv"
    comp.to_csv(table_path, index=False)

    profile_path = out_dir / "overlay_longitudinal_profile.png"
    _plot_overlay(base_run, other_run, outputs_root, profile_path)
    return table_path, profile_path


def _plot_overlay(base_run: str, other_run: str, outputs_root: Path, out_path: Path) -> None:
    bg = _profile_for_overlay(base_run, outputs_root)
    og = _profile_for_overlay(other_run, outputs_root)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(bg["chainage_m"], bg["wse"], label=f"{base_run} WSE")
    ax.plot(og["chainage_m"], og["wse"], label=f"{other_run} WSE")
    ax.set_xlabel("Chainage (m)")
    ax.set_ylabel("Water Surface Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def compare_scenario2_tiers(
    base_run: str,
    tier_runs: dict[str, str],
    outputs_root: Path = Path("outputs"),
) -> dict[str, str]:
    if not tier_runs:
        raise ValueError("No tier runs provided for Scenario 2 triad comparison.")

    out_dir = outputs_root / base_run / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_metrics = pd.read_csv(outputs_root / base_run / "tables" / "metrics.csv")
    if baseline_metrics.empty:
        raise ValueError("Baseline metrics are empty for triad comparison.")
    b = baseline_metrics.iloc[0]

    rows: list[dict[str, object]] = []
    for tier, rid in tier_runs.items():
        p = outputs_root / rid / "tables" / "metrics.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if df.empty:
            continue
        r = df.iloc[0]
        rows.append(
            {
                "tier": tier,
                "run_id": rid,
                "max_wse_m": _num(r, "max_wse_m"),
                "delta_max_wse_m": _num(r, "max_wse_m") - _num(b, "max_wse_m"),
                "max_velocity_mps": _num(r, "max_velocity_mps"),
                "delta_max_velocity_mps": _num(r, "max_velocity_mps") - _num(b, "max_velocity_mps"),
                "flood_extent_area_ha": _num(r, "flood_extent_area_ha"),
                "delta_flood_extent_area_ha": _num(r, "flood_extent_area_ha") - _num(b, "flood_extent_area_ha"),
                "max_energy_level_m": _num(r, "max_energy_level_m"),
                "delta_max_energy_level_m": _num(r, "max_energy_level_m") - _num(b, "max_energy_level_m"),
            }
        )
    if not rows:
        raise ValueError("No scenario tier metrics found for triad comparison.")

    detail = pd.DataFrame(rows)
    detail_path = out_dir / "scenario2_tier_comparison.csv"
    detail.to_csv(detail_path, index=False)

    envelope = pd.DataFrame(
        [
            _envelope_row("max_wse_m", float(_num(b, "max_wse_m")), detail["max_wse_m"], detail["delta_max_wse_m"]),
            _envelope_row(
                "max_velocity_mps",
                float(_num(b, "max_velocity_mps")),
                detail["max_velocity_mps"],
                detail["delta_max_velocity_mps"],
            ),
            _envelope_row(
                "flood_extent_area_ha",
                float(_num(b, "flood_extent_area_ha")),
                detail["flood_extent_area_ha"],
                detail["delta_flood_extent_area_ha"],
            ),
            _envelope_row(
                "max_energy_level_m",
                float(_num(b, "max_energy_level_m")),
                detail["max_energy_level_m"],
                detail["delta_max_energy_level_m"],
            ),
        ]
    )
    envelope_path = out_dir / "scenario2_tier_envelope.csv"
    envelope.to_csv(envelope_path, index=False)

    overlay_path = out_dir / "scenario2_tier_overlay_profile.png"
    _plot_tier_overlay(base_run=base_run, tier_runs=tier_runs, outputs_root=outputs_root, out_path=overlay_path)
    return {
        "tier_comparison": str(detail_path),
        "tier_envelope": str(envelope_path),
        "tier_overlay_profile": str(overlay_path),
    }


def _plot_tier_overlay(
    base_run: str,
    tier_runs: dict[str, str],
    outputs_root: Path,
    out_path: Path,
) -> None:
    base = _profile_for_overlay(base_run, outputs_root)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(base["chainage_m"], base["wse"], label=f"{base_run} baseline", linewidth=2.2, color="#1f77b4")
    tier_colors = {
        "lenient": "#2ca02c",
        "average": "#ff7f0e",
        "conservative": "#d62728",
    }
    for tier, rid in tier_runs.items():
        p = _profile_for_overlay(rid, outputs_root)
        ax.plot(
            p["chainage_m"],
            p["wse"],
            label=f"{tier} ({rid})",
            linewidth=1.8,
            color=tier_colors.get(tier, None),
        )
    ax.set_xlabel("Chainage (m)")
    ax.set_ylabel("Water Surface Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _profile_for_overlay(run_id: str, outputs_root: Path) -> pd.DataFrame:
    hdf_profile = outputs_root / run_id / "artifacts" / "hdf_profiles.csv"
    if hdf_profile.exists():
        df = pd.read_csv(hdf_profile)
        if not df.empty and {"chainage_m", "water_level_m"}.issubset(df.columns):
            return (
                df.groupby("chainage_m", as_index=False)
                .agg(wse=("water_level_m", "max"))
                .sort_values("chainage_m")
            )
    sections = outputs_root / run_id / "sections" / "required_sections.csv"
    df = pd.read_csv(sections)
    return (
        df.groupby("chainage_m", as_index=False)
        .agg(wse=("water_level_m", "max"))
        .sort_values("chainage_m")
    )


def _envelope_row(metric: str, baseline: float, scenario_vals: pd.Series, delta_vals: pd.Series) -> dict[str, float | str]:
    return {
        "metric": metric,
        "baseline": float(baseline),
        "scenario_min": float(scenario_vals.min()),
        "scenario_max": float(scenario_vals.max()),
        "delta_min": float(delta_vals.min()),
        "delta_max": float(delta_vals.max()),
    }


def _num(row: pd.Series, key: str) -> float:
    val = row.get(key, float("nan"))
    try:
        return float(val)
    except Exception:
        return float("nan")
