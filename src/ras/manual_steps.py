from __future__ import annotations

from pathlib import Path


def write_manual_compute_steps(run_project_dir: Path) -> Path:
    path = run_project_dir / "MANUAL_COMPUTE_STEPS.txt"
    project_name = next((p.name for p in run_project_dir.glob("*.prj")), "<project>.prj")
    text = (
        "Manual HEC-RAS Compute Gate\n"
        f"Project file: {project_name}\n"
        "1) Open THIS run-local project file (not the shell project).\n"
        "2) In Geometric Data window: File -> Import Geometry Data -> GIS Format (SDF).\n"
        "3) Select import/RASImport.sdf and complete import.\n"
        "4) Save Geometry Data (this should create/update a .g## file in this folder).\n"
        "5) Open Steady Flow Data and enter values from ../flow/steady_flow.json.\n"
        "6) Set boundary conditions (normal depth slopes as configured), then save flow data (.f##).\n"
        "7) Compute steady flow plan and save project.\n"
        "8) Verify run artifacts exist before closing:\n"
        "   - geometry file (.g##)\n"
        "   - flow file (.f##)\n"
        "   - plan/output files (.p##, .o##, .hdf)\n"
    )
    path.write_text(text, encoding="utf-8")
    return path
