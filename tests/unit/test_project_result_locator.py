from __future__ import annotations

from pathlib import Path

import h5py

from src.ras.result_locator import locate_project_results


def test_locate_project_results_prefers_active_plan(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "Model.prj").write_text("Current Plan=p02\n", encoding="cp1252")
    (project / "Model.p01").write_text("", encoding="utf-8")
    (project / "Model.p02").write_text("", encoding="utf-8")

    with h5py.File(project / "Model.g01.hdf", "w") as hdf:
        hdf.create_group("Geometry")
    with h5py.File(project / "Model.p02.hdf", "w") as hdf:
        hdf.create_group("Results")
        hdf.create_dataset("Results/Velocity", data=[1.0, 2.0, 3.0])

    result = locate_project_results(project, label="unit_project")
    assert result["plan_path"].endswith("Model.p02")
    assert result["hdf_path"].endswith("Model.p02.hdf")
