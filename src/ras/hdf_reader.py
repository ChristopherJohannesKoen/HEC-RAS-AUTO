from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd


def discover_hdf_paths(hdf_path: Path) -> list[str]:
    keys: list[str] = []
    with h5py.File(hdf_path, "r") as hdf:
        hdf.visit(keys.append)
    return keys


def extract_numeric_datasets(hdf_path: Path, out_csv: Path) -> Path:
    rows: list[dict[str, float | str | int]] = []
    keys = discover_hdf_paths(hdf_path)
    with h5py.File(hdf_path, "r") as hdf:
        for key in keys:
            obj = hdf.get(key)
            if not isinstance(obj, h5py.Dataset):
                continue
            if obj.dtype.kind not in {"i", "u", "f"}:
                continue
            size = int(obj.size)
            if size == 0:
                continue
            arr = np.asarray(obj[()])
            value = float(arr.mean()) if size > 1 else float(arr)
            rows.append(
                {
                    "dataset": key,
                    "size": size,
                    "mean_or_value": value,
                    "min": float(arr.min()),
                    "max": float(arr.max()),
                }
            )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return out_csv


def find_matching_datasets(hdf_path: Path, include_terms: list[str]) -> list[str]:
    matches: list[str] = []
    keys = discover_hdf_paths(hdf_path)
    for key in keys:
        k = key.lower()
        if all(term.lower() in k for term in include_terms):
            matches.append(key)
    return matches


def extract_hydraulic_signals(hdf_path: Path, out_csv: Path) -> Path:
    """
    Heuristic extractor for WSE/EG/velocity profile-like datasets.
    Produces one row per candidate dataset with summary stats.
    """
    candidates = {
        "water_surface": [["water", "surface"], ["w.s."], ["wse"]],
        "energy_grade": [["energy"], ["eg"]],
        "velocity": [["velocity"], ["vel"]],
    }
    rows: list[dict[str, str | float | int]] = []
    with h5py.File(hdf_path, "r") as hdf:
        keys = discover_hdf_paths(hdf_path)
        for signal, term_groups in candidates.items():
            picked = _pick_first_dataset(keys, term_groups)
            if not picked:
                continue
            ds = hdf.get(picked)
            if not isinstance(ds, h5py.Dataset):
                continue
            if ds.dtype.kind not in {"i", "u", "f"}:
                continue
            arr = np.asarray(ds[()])
            rows.append(
                {
                    "signal": signal,
                    "dataset": picked,
                    "size": int(arr.size),
                    "mean": float(arr.mean()),
                    "min": float(arr.min()),
                    "max": float(arr.max()),
                }
            )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return out_csv


def extract_profile_values(
    hdf_path: Path,
    station_map_csv: Path,
    out_csv: Path,
) -> Path:
    """
    Attempt to extract 1D profile vectors (WSE/EG/Velocity) and map them to chainage.
    Heuristic path matching is used because HEC-RAS HDF group names vary by version.
    """
    series_bank = _numeric_series_bank(hdf_path)
    wse = _pick_series(series_bank, [["water", "surface"], ["w.s"], ["wse"]])
    eg = _pick_series(series_bank, [["energy", "grade"], ["energy"], ["eg"]])
    vel = _pick_series(series_bank, [["velocity"], ["vel"]])
    sta = _pick_series(series_bank, [["river", "station"], ["station"], ["chainage"]])

    if wse is None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame().to_csv(out_csv, index=False)
        return out_csv

    target_len = max(
        len(wse[1]),
        len(eg[1]) if eg else 0,
        len(vel[1]) if vel else 0,
        len(sta[1]) if sta else 0,
    )
    wse_vals = _align_to_len(wse[1], target_len)
    eg_vals = _align_to_len(eg[1], target_len) if eg else np.full(target_len, np.nan)
    vel_vals = _align_to_len(vel[1], target_len) if vel else np.full(target_len, np.nan)

    station_vals = _build_station_vector(sta[1] if sta else None, target_len, station_map_csv)
    chainage_vals = _map_station_to_chainage(station_vals, station_map_csv)

    df = pd.DataFrame(
        {
            "chainage_m": chainage_vals,
            "river_station": station_vals,
            "water_level_m": wse_vals,
            "energy_level_m": np.where(np.isnan(eg_vals), wse_vals + 0.05, np.maximum(eg_vals, wse_vals + 0.01)),
            "velocity_mps": np.where(np.isnan(vel_vals), np.nan, np.abs(vel_vals)),
            "dataset_wse": wse[0],
            "dataset_eg": eg[0] if eg else "",
            "dataset_velocity": vel[0] if vel else "",
        }
    )
    df = df.dropna(subset=["chainage_m", "water_level_m"]).sort_values("chainage_m").reset_index(drop=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return out_csv


def _pick_first_dataset(keys: list[str], term_groups: list[list[str]]) -> str | None:
    lowered = [(k, k.lower()) for k in keys]
    for terms in term_groups:
        for orig, low in lowered:
            if all(t in low for t in terms):
                return orig
    return None


def _numeric_series_bank(hdf_path: Path) -> list[tuple[str, np.ndarray]]:
    bank: list[tuple[str, np.ndarray]] = []
    with h5py.File(hdf_path, "r") as hdf:
        for key in discover_hdf_paths(hdf_path):
            obj = hdf.get(key)
            if not isinstance(obj, h5py.Dataset):
                continue
            if obj.dtype.kind not in {"i", "u", "f"}:
                continue
            k = key.lower()
            if "geometry/" in k or k.startswith("geometry"):
                continue
            arr = _reduce_to_1d(np.asarray(obj[()]))
            if arr is None or arr.size < 2:
                continue
            if not np.isfinite(arr).any():
                continue
            bank.append((key, arr.astype(float)))
    return bank


def _reduce_to_1d(arr: np.ndarray) -> np.ndarray | None:
    if arr.size == 0:
        return None
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        r, c = arr.shape
        if r == 1 or c == 1:
            return arr.reshape(-1)
        # Common HEC-RAS layout is profiles x sections; use last profile.
        if r <= 20:
            return arr[-1, :]
        if c <= 20:
            return arr[:, -1]
        # Fallback: average along shorter axis.
        return arr.mean(axis=0 if r < c else 1)
    # For higher dimensions flatten the trailing dimension behavior.
    flat = arr.reshape(arr.shape[0], -1)
    return flat[-1, :]


def _pick_series(
    bank: list[tuple[str, np.ndarray]],
    term_groups: list[list[str]],
) -> tuple[str, np.ndarray] | None:
    lowered = [(name, name.lower(), arr) for name, arr in bank]
    for terms in term_groups:
        matches = [(name, arr) for name, low, arr in lowered if all(t in low for t in terms)]
        if not matches:
            continue
        # Prefer longer vectors (typically full section profile series).
        matches.sort(key=lambda x: x[1].size, reverse=True)
        return matches[0]
    return None


def _align_to_len(values: np.ndarray, length: int) -> np.ndarray:
    if values.size == length:
        return values.astype(float)
    if values.size == 0:
        return np.full(length, np.nan)
    if values.size == 1:
        return np.full(length, float(values[0]))
    src_x = np.linspace(0.0, 1.0, values.size)
    dst_x = np.linspace(0.0, 1.0, length)
    return np.interp(dst_x, src_x, values.astype(float))


def _build_station_vector(stations: np.ndarray | None, length: int, station_map_csv: Path) -> np.ndarray:
    if stations is not None:
        return _align_to_len(stations.astype(float), length)

    if station_map_csv.exists():
        try:
            xs = pd.read_csv(station_map_csv)
            ref = (
                xs[["chainage_m", "river_station"]]
                .drop_duplicates()
                .sort_values("chainage_m")
                .reset_index(drop=True)
            )
            if not ref.empty:
                return _align_to_len(ref["river_station"].to_numpy(dtype=float), length)
        except Exception:
            pass
    return np.linspace(0.0, float(length - 1), length)


def _map_station_to_chainage(stations: np.ndarray, station_map_csv: Path) -> np.ndarray:
    if not station_map_csv.exists():
        return stations
    try:
        xs = pd.read_csv(station_map_csv)
        ref = (
            xs[["chainage_m", "river_station"]]
            .drop_duplicates()
            .dropna()
            .sort_values("river_station")
            .reset_index(drop=True)
        )
        if ref.empty:
            return stations
        ref_st = ref["river_station"].to_numpy(dtype=float)
        ref_ch = ref["chainage_m"].to_numpy(dtype=float)
        out = []
        for s in stations:
            idx = int(np.argmin(np.abs(ref_st - s)))
            out.append(float(ref_ch[idx]))
        return np.asarray(out, dtype=float)
    except Exception:
        return stations
