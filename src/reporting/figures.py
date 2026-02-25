from __future__ import annotations

from pathlib import Path


def figure_list_markdown(run_id: str, outputs_root: Path = Path("outputs")) -> str:
    run_dir = outputs_root / run_id
    if not run_dir.exists():
        return "_No output directory found._"
    figures = sorted([p for p in run_dir.rglob("*.png")])
    if not figures:
        return "_No figures generated yet._"
    return "\n".join([f"- {p.as_posix()}" for p in figures])
