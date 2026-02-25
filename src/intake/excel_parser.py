from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.models import SheetsConfig


def parse_excel_inputs(xlsx_path: Path, sheets: SheetsConfig, out_dir: Path = Path("data/processed")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_cfg = sheets.excel
    cols = excel_cfg.columns

    try:
        xs_df = pd.read_excel(xlsx_path, sheet_name=excel_cfg.cross_sections_sheet)
        _require_columns(
            xs_df,
            [cols.chainage, cols.station, cols.offset, cols.elevation],
            "cross sections",
        )
        xs_df = xs_df[[cols.chainage, cols.station, cols.offset, cols.elevation]].rename(
            columns={
                cols.chainage: "chainage_m",
                cols.station: "river_station",
                cols.offset: "offset_m",
                cols.elevation: "elevation_m",
            }
        )

        centerline_df = pd.read_excel(xlsx_path, sheet_name=excel_cfg.centerline_sheet)
        _require_columns(centerline_df, [cols.x, cols.y], "centerline")
        centerline_df = centerline_df[[cols.x, cols.y]].rename(columns={cols.x: "x", cols.y: "y"})
    except Exception:
        xs_df, centerline_df = _parse_assignment_style_workbook(
            xlsx_path=xlsx_path,
            cross_sections_sheet=excel_cfg.cross_sections_sheet,
            centerline_sheet=excel_cfg.centerline_sheet,
        )

    _write_df_with_optional_parquet(xs_df, out_dir / "cross_sections_raw")
    _write_df_with_optional_parquet(centerline_df, out_dir / "centerline_from_excel")


def _require_columns(df: pd.DataFrame, required: list[str], context: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {context} sheet: {missing}")


def _write_df_with_optional_parquet(df: pd.DataFrame, stem: Path) -> None:
    df.to_csv(stem.with_suffix(".csv"), index=False)
    try:
        df.to_parquet(stem.with_suffix(".parquet"), index=False)
    except Exception:
        # Parquet engine is optional for v1; CSV remains canonical fallback.
        pass


def _parse_assignment_style_workbook(
    xlsx_path: Path,
    cross_sections_sheet: str,
    centerline_sheet: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    xs_raw = pd.read_excel(xlsx_path, sheet_name=cross_sections_sheet, header=None)
    xs_rows: list[dict[str, float]] = []

    # Assignment workbook layout:
    # row 3: station labels (e.g., "Station 3905")
    # row 4: chainage labels (e.g., "Chainage 0")
    # row 5: headers "X (m)" and "Z (m)" per station block, repeated every 3 columns.
    for col in range(1, xs_raw.shape[1], 3):
        station_cell = xs_raw.iat[3, col] if col < xs_raw.shape[1] else None
        chainage_cell = xs_raw.iat[4, col] if col < xs_raw.shape[1] else None
        if pd.isna(station_cell) or pd.isna(chainage_cell):
            continue

        station = _extract_first_number(station_cell)
        chainage = _extract_first_number(chainage_cell)
        if station is None or chainage is None:
            continue

        x_col = col
        z_col = col + 1
        if z_col >= xs_raw.shape[1]:
            continue

        block = xs_raw.iloc[6:, [x_col, z_col]].copy()
        block.columns = ["offset_m", "elevation_m"]
        block["offset_m"] = pd.to_numeric(block["offset_m"], errors="coerce")
        block["elevation_m"] = pd.to_numeric(block["elevation_m"], errors="coerce")
        block = block.dropna(subset=["offset_m", "elevation_m"])
        if block.empty:
            continue

        for row in block.itertuples(index=False):
            xs_rows.append(
                {
                    "chainage_m": float(chainage),
                    "river_station": float(station),
                    "offset_m": float(row.offset_m),
                    "elevation_m": float(row.elevation_m),
                }
            )

    xs_df = pd.DataFrame(xs_rows)
    if xs_df.empty:
        raise ValueError("Could not parse any cross-section rows from assignment workbook format.")

    long_raw = pd.read_excel(xlsx_path, sheet_name=centerline_sheet, header=None)
    x_col, y_col = _find_centerline_xy_columns(long_raw)
    centerline_df = long_raw.iloc[2:, [x_col, y_col]].copy()
    centerline_df.columns = ["x", "y"]
    centerline_df["x"] = pd.to_numeric(centerline_df["x"], errors="coerce")
    centerline_df["y"] = pd.to_numeric(centerline_df["y"], errors="coerce")
    centerline_df = centerline_df.dropna(subset=["x", "y"]).reset_index(drop=True)
    if centerline_df.empty:
        raise ValueError("Could not parse river centerline x/y rows from workbook.")

    return xs_df, centerline_df


def _extract_first_number(value: object) -> float | None:
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return float(match.group(0))


def _find_centerline_xy_columns(df: pd.DataFrame) -> tuple[int, int]:
    # Prefer pair under "River Centreline" title in row 0.
    row0 = df.iloc[0].astype(str).tolist()
    rc_idx = next((i for i, v in enumerate(row0) if "river centreline" in str(v).lower()), None)
    if rc_idx is not None and rc_idx + 1 < df.shape[1]:
        return rc_idx, rc_idx + 1

    # Fallback to first two numeric-dense columns from row 2 onward.
    data = df.iloc[2:].apply(pd.to_numeric, errors="coerce")
    numeric_counts = data.notna().sum().sort_values(ascending=False)
    cols = list(numeric_counts.head(2).index)
    if len(cols) < 2:
        raise ValueError("Unable to detect centerline x/y columns.")
    return int(cols[0]), int(cols[1])
