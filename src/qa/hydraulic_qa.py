from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models import QAIssue, ThresholdConfig


def run_hydraulic_qa(
    metrics_csv: Path,
    log_issues: list[QAIssue],
    thresholds: ThresholdConfig,
) -> list[QAIssue]:
    issues: list[QAIssue] = []
    issues.extend(log_issues)
    if not metrics_csv.exists():
        issues.append(
            QAIssue(
                severity="error",
                code="METRICS_MISSING",
                message=f"Metrics CSV missing: {metrics_csv}",
            )
        )
        return issues

    df = pd.read_csv(metrics_csv)
    if df.empty:
        issues.append(QAIssue(severity="error", code="METRICS_EMPTY", message="Metrics table is empty."))
        return issues

    if "max_velocity_mps" in df.columns:
        vmax = float(df["max_velocity_mps"].max())
        if vmax > thresholds.qa.max_velocity_reasonableness_mps:
            issues.append(
                QAIssue(
                    severity="warn",
                    code="VELOCITY_HIGH",
                    message=f"Max velocity exceeds threshold: {vmax:.2f} m/s",
                )
            )
    if not any(i.severity == "error" for i in issues):
        issues.append(QAIssue(severity="info", code="HYD_QA_DONE", message="Hydraulic QA executed."))
    return issues
