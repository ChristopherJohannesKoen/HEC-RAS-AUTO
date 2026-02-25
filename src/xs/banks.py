from __future__ import annotations

import numpy as np
import pandas as pd


def suggest_banks(section_df: pd.DataFrame) -> tuple[float, float, float]:
    """Return left bank, right bank, confidence in [0, 1]."""
    s = section_df.sort_values("offset_m")
    offsets = s["offset_m"].to_numpy(dtype=float)
    elev = s["elevation_m"].to_numpy(dtype=float)
    if len(offsets) < 5:
        return float(offsets[0]), float(offsets[-1]), 0.2

    thalweg_idx = int(np.argmin(elev))
    grad = np.gradient(elev, offsets)
    left_candidates = np.where(grad[:thalweg_idx] > np.percentile(grad[:thalweg_idx], 70))[0]
    right_candidates = np.where(grad[thalweg_idx:] < np.percentile(grad[thalweg_idx:], 30))[0]

    left_idx = int(left_candidates[-1]) if len(left_candidates) else max(thalweg_idx - 1, 0)
    right_idx = (
        int(thalweg_idx + right_candidates[0]) if len(right_candidates) else min(thalweg_idx + 1, len(offsets) - 1)
    )

    left_bank = float(offsets[left_idx])
    right_bank = float(offsets[right_idx])
    confidence = 0.8 if right_bank > left_bank else 0.3
    if right_bank <= left_bank:
        left_bank = float(offsets[0])
        right_bank = float(offsets[-1])
        confidence = 0.2
    return left_bank, right_bank, confidence
