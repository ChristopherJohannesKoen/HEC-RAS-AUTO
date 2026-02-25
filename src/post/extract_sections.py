from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


REQUIRED_CHAINGAGES = [0.0, 1500.0, 3905.0]


def extract_required_sections(
    cross_sections_csv: Path,
    run_id: str,
    profile_values_csv: Path | None = None,
    signal_summary_csv: Path | None = None,
    output_root: Path = Path("outputs"),
) -> Path:
    out_dir = output_root / run_id / "sections"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(cross_sections_csv)
    out_table = out_dir / "required_sections.csv"

    profile_values = _load_profile_values(profile_values_csv) if profile_values_csv else {}
    signal_values = _load_signal_values(signal_summary_csv) if signal_summary_csv else {}
    rows = []
    for c in REQUIRED_CHAINGAGES:
        sec = _nearest_chainage_section(df, c)
        if sec.empty:
            continue
        sec = sec.sort_values("offset_m").copy()
        bed_min = float(sec["elevation_m"].min())
        values = _select_hydraulic_values(c, bed_min, profile_values, signal_values)
        water = values["water"]
        energy = values["energy"]
        velocity = values["velocity"]
        sec["water_level_m"] = water
        sec["energy_level_m"] = energy
        sec["velocity_mps"] = velocity
        sec["requested_chainage_m"] = c
        sec["hydraulic_source"] = values["source"]
        rows.append(sec)
        _plot_section(sec, out_dir / f"section_chainage_{int(c)}.png")

    if rows:
        final = pd.concat(rows, ignore_index=True)
    else:
        final = pd.DataFrame()
    final.to_csv(out_table, index=False)
    return out_table


def _nearest_chainage_section(df: pd.DataFrame, target: float) -> pd.DataFrame:
    if df.empty:
        return df
    chainages = sorted(df["chainage_m"].unique())
    nearest = min(chainages, key=lambda x: abs(float(x) - target))
    return df.loc[df["chainage_m"] == nearest].copy()


def _plot_section(sec: pd.DataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(sec["offset_m"], sec["elevation_m"], label="bed")
    ax.plot(sec["offset_m"], sec["water_level_m"], label="water surface")
    ax.plot(sec["offset_m"], sec["energy_level_m"], label="energy grade")
    ax.set_xlabel("Offset (m)")
    ax.set_ylabel("Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _load_signal_values(path: Path | None) -> dict[str, float]:
    if path is None or not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if df.empty or "signal" not in df.columns:
        return {}
    out: dict[str, float] = {}
    for signal in ("water_surface", "energy_grade", "velocity"):
        rows = df.loc[df["signal"] == signal]
        if rows.empty:
            continue
        out[signal] = float(rows.iloc[0]["mean"])
    return out


def _load_profile_values(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    required = {"chainage_m", "water_level_m", "energy_level_m", "velocity_mps"}
    if not required.issubset(set(df.columns)):
        return pd.DataFrame()
    return df.copy()


def _select_hydraulic_values(
    target_chainage: float,
    bed_min: float,
    profile_values: pd.DataFrame,
    signal_values: dict[str, float],
) -> dict[str, float | str]:
    if not profile_values.empty:
        idx = (profile_values["chainage_m"] - target_chainage).abs().idxmin()
        row = profile_values.loc[idx]
        return {
            "water": float(row["water_level_m"]),
            "energy": float(max(row["energy_level_m"], float(row["water_level_m"]) + 0.01)),
            "velocity": float(abs(row["velocity_mps"])),
            "source": "hdf_profile",
        }

    if signal_values:
        water = _estimate_wse(bed_min, signal_values.get("water_surface"))
        energy = _estimate_energy(water, signal_values.get("energy_grade"))
        velocity = _estimate_velocity(signal_values.get("velocity"))
        return {
            "water": water,
            "energy": energy,
            "velocity": velocity,
            "source": "signal_summary",
        }

    return {
        "water": bed_min + 1.0,
        "energy": bed_min + 1.2,
        "velocity": 1.0,
        "source": "fallback",
    }


def _estimate_wse(bed_min: float, signal_mean: float | None) -> float:
    if signal_mean is None:
        return bed_min + 1.0
    # Clamp extreme values while preserving data-driven tendency.
    if signal_mean < bed_min:
        return bed_min + 0.2
    return signal_mean


def _estimate_energy(wse: float, signal_mean: float | None) -> float:
    if signal_mean is None:
        return wse + 0.2
    return max(signal_mean, wse + 0.05)


def _estimate_velocity(signal_mean: float | None) -> float:
    if signal_mean is None:
        return 1.0
    v = abs(signal_mean)
    return min(max(v, 0.05), 20.0)
