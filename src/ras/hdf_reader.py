from __future__ import annotations

from pathlib import Path

import h5py
import pandas as pd


def discover_hdf_paths(hdf_path: Path) -> list[str]:
    keys: list[str] = []
    with h5py.File(hdf_path, "r") as hdf:
        hdf.visit(keys.append)
    return keys


def extract_numeric_datasets(hdf_path: Path, out_csv: Path) -> Path:
    rows: list[dict[str, float | str | int]] = []
    with h5py.File(hdf_path, "r") as hdf:
        for key in discover_hdf_paths(hdf_path):
            obj = hdf.get(key)
            if not isinstance(obj, h5py.Dataset):
                continue
            if obj.dtype.kind not in {"i", "u", "f"}:
                continue
            size = int(obj.size)
            if size == 0:
                continue
            value = float(obj[()].mean()) if size > 1 else float(obj[()])
            rows.append({"dataset": key, "size": size, "mean_or_value": value})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return out_csv
