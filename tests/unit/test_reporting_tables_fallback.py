from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.reporting import tables


def test_markdown_fallback_without_tabulate(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise ImportError("tabulate missing")

    monkeypatch.setattr(pd.DataFrame, "to_markdown", _raise)
    df = pd.DataFrame([{"a": 1, "b": 2}])
    md = tables._df_to_markdown_safe(df)
    assert "| a | b |" in md
    assert "| 1 | 2 |" in md


def test_load_input_summary_uses_fallback(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1" / "flow"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "steady_flow.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    def _raise(*args, **kwargs):
        raise ImportError("tabulate missing")

    monkeypatch.setattr(pd.DataFrame, "to_markdown", _raise)
    md = tables.load_input_summary("r1", runs_root=tmp_path / "runs")
    assert "| x | y |" in md
