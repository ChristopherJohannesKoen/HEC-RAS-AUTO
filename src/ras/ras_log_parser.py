from __future__ import annotations

from pathlib import Path

from src.models import QAIssue


def parse_ras_log(log_path: Path) -> list[QAIssue]:
    if not log_path.exists():
        return [QAIssue(severity="warn", code="LOG_MISSING", message=f"No log file: {log_path}")]
    issues: list[QAIssue] = []
    text = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for idx, line in enumerate(text, start=1):
        lowered = line.lower()
        if "error" in lowered:
            issues.append(
                QAIssue(
                    severity="error",
                    code="RAS_ERROR_LINE",
                    message=line.strip(),
                    location=f"{log_path}:{idx}",
                )
            )
        elif "warning" in lowered:
            issues.append(
                QAIssue(
                    severity="warn",
                    code="RAS_WARNING_LINE",
                    message=line.strip(),
                    location=f"{log_path}:{idx}",
                )
            )
    if not issues:
        issues.append(QAIssue(severity="info", code="LOG_CLEAN", message="No warnings/errors detected in log."))
    return issues
