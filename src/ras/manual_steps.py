from __future__ import annotations

from pathlib import Path


def write_manual_compute_steps(run_project_dir: Path) -> Path:
    path = run_project_dir / "MANUAL_COMPUTE_STEPS.txt"
    text = (
        "Manual HEC-RAS Compute Gate\n"
        "1) Open this run-local HEC-RAS project (*.prj).\n"
        "2) Import geometry from import/RASImport.sdf.\n"
        "3) Verify river reach and cross sections visually.\n"
        "4) Verify steady flow payload from ../flow/steady_flow.json.\n"
        "5) Set boundary conditions (normal depth slope values as configured).\n"
        "6) Compute steady flow plan.\n"
        "7) Save project and close HEC-RAS.\n"
    )
    path.write_text(text, encoding="utf-8")
    return path
