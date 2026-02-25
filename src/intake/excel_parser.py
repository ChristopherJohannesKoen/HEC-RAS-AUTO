from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models import SheetsConfig


def parse_excel_inputs(xlsx_path: Path, sheets: SheetsConfig, out_dir: Path = Path("data/processed")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_cfg = sheets.excel
    cols = excel_cfg.columns

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
    xs_df.to_parquet(out_dir / "cross_sections_raw.parquet", index=False)
    xs_df.to_csv(out_dir / "cross_sections_raw.csv", index=False)

    centerline_df = pd.read_excel(xlsx_path, sheet_name=excel_cfg.centerline_sheet)
    _require_columns(centerline_df, [cols.x, cols.y], "centerline")
    centerline_df = centerline_df[[cols.x, cols.y]].rename(columns={cols.x: "x", cols.y: "y"})
    centerline_df.to_parquet(out_dir / "centerline_from_excel.parquet", index=False)
    centerline_df.to_csv(out_dir / "centerline_from_excel.csv", index=False)


def _require_columns(df: pd.DataFrame, required: list[str], context: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {context} sheet: {missing}")
