#!/usr/bin/env python3
"""
Merge many Cape Farm Mapper elevation-profile CSV files into one long table.

The output is useful for QA, contour interpolation, or conversion to point features later.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge CFM profile CSV exports.")
    parser.add_argument("--profiles-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    files = sorted(args.profiles_dir.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSV files found in {args.profiles_dir}")

    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception as exc:
            print(f"Skipping {f.name}: {exc}")
            continue
        df.insert(0, "source_csv", f.name)
        df.insert(1, "line_id", f.stem)
        rows.append(df)

    if not rows:
        raise SystemExit("No readable CSV files were found.")

    out = pd.concat(rows, ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"Wrote {len(out):,} rows to {args.output}")


if __name__ == "__main__":
    main()
