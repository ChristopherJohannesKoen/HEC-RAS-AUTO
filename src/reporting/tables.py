from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_metrics_markdown(run_id: str, outputs_root: Path = Path("outputs")) -> str:
    metrics_csv = outputs_root / run_id / "tables" / "metrics.csv"
    if not metrics_csv.exists():
        return "_No metrics file found._"
    df = pd.read_csv(metrics_csv)
    if df.empty:
        return "_Metrics file is empty._"
    return df.to_markdown(index=False)


def load_input_summary(run_id: str, runs_root: Path = Path("runs")) -> str:
    flow_csv = runs_root / run_id / "flow" / "steady_flow.csv"
    if not flow_csv.exists():
        return "_No steady-flow input found._"
    df = pd.read_csv(flow_csv)
    if df.empty:
        return "_Steady-flow table empty._"
    return df.to_markdown(index=False)
