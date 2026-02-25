from __future__ import annotations

from pathlib import Path

import h5py
import pytest

from src.common.exceptions import HECRASRunMissingError
from src.ras.result_locator import locate_run_results


def test_result_locator_rejects_geometry_hdf(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "baseline" / "ras_project"
    run.mkdir(parents=True, exist_ok=True)
    (run / "Model.p01").write_text("", encoding="utf-8")
    (run / "Model.g01.hdf").write_text("", encoding="utf-8")

    with pytest.raises(HECRASRunMissingError):
        locate_run_results("baseline", runs_root=tmp_path / "runs")


def test_result_locator_accepts_plan_hdf(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "baseline" / "ras_project"
    run.mkdir(parents=True, exist_ok=True)
    (run / "Model.p01").write_text("", encoding="utf-8")
    with h5py.File(run / "Model.p01.hdf", "w") as hdf:
        hdf.create_group("Results")
        hdf.create_dataset("Results/Velocity", data=[1.2, 1.1, 0.9])
    out = locate_run_results("baseline", runs_root=tmp_path / "runs")
    assert out["plan_path"].endswith(".p01")
    assert out["hdf_path"].endswith(".p01.hdf")
