from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_regime_recommendation(metrics_csv: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not metrics_csv.exists():
        out_path.write_text(
            "Flow Regime Recommendation\n[VERIFY] Metrics file missing; cannot recommend regime.\n",
            encoding="utf-8",
        )
        return out_path

    df = pd.read_csv(metrics_csv)
    if "max_velocity_mps" not in df.columns:
        out_path.write_text(
            "Flow Regime Recommendation\n[VERIFY] Velocity data missing; recommend manual regime check.\n",
            encoding="utf-8",
        )
        return out_path

    vmax = float(df["max_velocity_mps"].max())
    if vmax < 2.5:
        rec = "Subcritical candidate"
    elif vmax > 5.0:
        rec = "Mixed/Supercritical candidate"
    else:
        rec = "Mixed candidate"

    text = (
        "Flow Regime Recommendation\n"
        f"- Peak velocity observed: {vmax:.2f} m/s\n"
        f"- Recommended initial regime: {rec}\n"
        "- [VERIFY] Confirm with HEC-RAS profile behavior and warning diagnostics.\n"
    )
    out_path.write_text(text, encoding="utf-8")
    return out_path
