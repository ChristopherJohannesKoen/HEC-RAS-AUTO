from __future__ import annotations

from pathlib import Path


def write_manual_compute_steps(run_project_dir: Path) -> Path:
    path = run_project_dir / "MANUAL_COMPUTE_STEPS.txt"
    project_name = next((p.name for p in run_project_dir.glob("*.prj")), "<project>.prj")
    text = (
        "Manual HEC-RAS Compute Gate\n"
        f"Project file: {project_name}\n"
        "1) Open THIS run-local project file (not the shell project).\n"
        "2) Verify plan references Geom File=g01 and Flow File=f01.\n"
        "3) Open Geometric Data and confirm cross sections exist (file-first staged geometry).\n"
        "4) Open Steady Flow Data and confirm values match ../flow/steady_flow.json.\n"
        "5) Compute steady flow plan and save project.\n"
        "6) Verify run artifacts exist before closing:\n"
        "   - geometry file (.g##)\n"
        "   - flow file (.f##)\n"
        "   - plan/output files (.p##, .o##, .hdf)\n"
        "\nOptional fallback (only if no geometry appears):\n"
        " - Import import/RASImport.sdf manually and save as new geometry, then recompute.\n"
    )
    path.write_text(text, encoding="utf-8")
    return path
