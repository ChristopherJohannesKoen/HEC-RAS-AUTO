from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.models import QAIssue, ThresholdConfig


def run_terrain_qa(profile_csv: Path, thresholds: ThresholdConfig) -> list[QAIssue]:
    df = pd.read_csv(profile_csv)
    issues: list[QAIssue] = []
    if df.empty:
        return [QAIssue(severity="error", code="PROFILE_EMPTY", message="Terrain profile is empty.")]

    valid = df["elevation_m"].notna().sum()
    nodata_fraction = 1.0 - (valid / len(df))
    if nodata_fraction > thresholds.terrain.max_nodata_fraction:
        issues.append(
            QAIssue(
                severity="error",
                code="NODATA_FRACTION",
                message=f"NoData fraction too high: {nodata_fraction:.2f}",
            )
        )

    diffs = np.abs(np.diff(df["elevation_m"].fillna(method="ffill").to_numpy(dtype=float)))
    if len(diffs) and float(diffs.max()) > thresholds.terrain.max_profile_jump_per_step_m:
        issues.append(
            QAIssue(
                severity="warn",
                code="PROFILE_JUMP",
                message=f"Large elevation jump detected: {float(diffs.max()):.2f} m",
            )
        )

    if not issues:
        issues.append(QAIssue(severity="info", code="TERRAIN_QA_OK", message="Terrain QA passed."))
    return issues
