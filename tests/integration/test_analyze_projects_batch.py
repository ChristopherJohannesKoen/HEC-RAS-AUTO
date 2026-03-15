from __future__ import annotations

import json
from pathlib import Path

import h5py

from src.analyse.batch_analysis import analyze_project_folders
from src.models.agent import AIAgentConfig


def test_analyze_project_folders_generates_outputs_without_mutating_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "analyse"
    output_root = tmp_path / "outputs" / "analyse"
    project = source_root / "Baseline Example"
    project.mkdir(parents=True, exist_ok=True)

    (project / "Model.prj").write_text(
        "\n".join(
            [
                "Proj Title=Baseline Example",
                "Current Plan=p01",
                "Geom File=g01",
                "Flow File=f01",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    (project / "Model.p01").write_text(
        "\n".join(
            [
                "Plan Title=Existing Conditions Run",
                "Short Identifier=Existing",
                "Geom File=g01",
                "Flow File=f01",
                "Subcritical Flow",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    (project / "Model.f01").write_text(
        "\n".join(
            [
                "Flow Title=Steady Example",
                "Number of Profiles= 1",
                "Profile Names=Q100",
                "River Rch & RM=Example River,Main            ,100.000",
                "     375",
                "Boundary for River Rch & Prof#=Example River,Main            , 1",
                "Up Type= 3",
                "Up Slope=0.02",
                "Dn Type= 3",
                "Dn Slope=0.01",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    (project / "Model.g01").write_text(
        "\n".join(
            [
                "Geom Title=Example Geometry",
                "River Reach=Example River   ,Main",
                "Reach XY= 2",
                "0 0 10 0",
                "Type RM Length L Ch R = 1 ,100.000,10,10,10",
                "BEGIN DESCRIPTION:",
                "Auto-generated cross section at chainage 0.000 m",
                "END DESCRIPTION:",
                "#Sta/Elev= 4",
                "-10 290 -5 289 5 288 10 289",
                "#Mann= 3 ,0,0",
                "-10 .06 0 -5 .04 0 10 .06 0",
                "Bank Sta=-5,5",
                "XS Rating Curve= 0 ,0",
                "Type RM Length L Ch R = 1 ,0.000,0,0,0",
                "BEGIN DESCRIPTION:",
                "Auto-generated cross section at chainage 100.000 m",
                "END DESCRIPTION:",
                "#Sta/Elev= 4",
                "-8 280 -2 279 2 278 8 279",
                "#Mann= 3 ,0,0",
                "-8 .06 0 -2 .04 0 8 .06 0",
                "Bank Sta=-2,2",
                "XS Rating Curve= 0 ,0",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    with h5py.File(project / "Model.p01.hdf", "w") as hdf:
        hdf.create_group("Results")
        hdf.create_dataset("Results/Water Surface", data=[286.0, 279.0])
        hdf.create_dataset("Results/Energy Grade", data=[286.3, 279.2])
        hdf.create_dataset("Results/Velocity", data=[2.1, 1.8])
        hdf.create_dataset("Results/River Station", data=[100.0, 0.0])

    source_bytes_before = (project / "Model.g01").read_bytes()

    def _fake_ai_report(report_id: str, context: dict[str, str], ai_config: AIAgentConfig, output_root: Path, require_ai: bool = False):
        reports_dir = output_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md = reports_dir / f"{report_id}_final_ai_report.md"
        docx = reports_dir / f"{report_id}_final_ai_report.docx"
        md.write_text("# Stub AI Report\n", encoding="utf-8")
        docx.write_text("stub", encoding="utf-8")
        return {"markdown": str(md), "docx": str(docx), "debug": ""}

    monkeypatch.setattr("src.analyse.batch_analysis.build_ai_word_report_from_context", _fake_ai_report)

    manifest_path = analyze_project_folders(
        source_root=source_root,
        output_root=output_root,
        ai_config=AIAgentConfig(),
        strict=True,
        compute_missing_results=False,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["completed_count"] == 1
    project_out = output_root / "baseline_example"
    assert (project_out / "reports" / "baseline_example_audit_report_draft.md").exists()
    assert (project_out / "reports" / "baseline_example_final_ai_report.docx").exists()
    assert (project_out / "tables" / "metrics.csv").exists()
    assert (project_out / "sections" / "all_sections.csv").exists()
    assert (project_out / "inventory" / "source_snapshot_before.json").exists()
    assert (project_out / "inventory" / "source_snapshot_after.json").exists()
    assert (project / "Model.g01").read_bytes() == source_bytes_before


def test_analyze_project_folders_can_force_temp_compute(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "analyse"
    output_root = tmp_path / "outputs" / "analyse"
    project = source_root / "Forced Compute Example"
    project.mkdir(parents=True, exist_ok=True)

    (project / "Model.prj").write_text("Proj Title=Forced\nCurrent Plan=p01\nGeom File=g01\nFlow File=f01\n", encoding="cp1252")
    (project / "Model.p01").write_text("Plan Title=Existing\nGeom File=g01\nFlow File=f01\nSubcritical Flow\n", encoding="cp1252")
    (project / "Model.f01").write_text(
        "Flow Title=Steady Example\nNumber of Profiles= 1\nProfile Names=Q100\nRiver Rch & RM=Example River,Main            ,100.000\n     375\nBoundary for River Rch & Prof#=Example River,Main            , 1\nUp Type= 3\nUp Slope=0.02\nDn Type= 3\nDn Slope=0.01\n",
        encoding="cp1252",
    )
    (project / "Model.g01").write_text(
        "\n".join(
            [
                "Geom Title=Example Geometry",
                "River Reach=Example River   ,Main",
                "Reach XY= 2",
                "0 0 10 0",
                "Type RM Length L Ch R = 1 ,100.000,10,10,10",
                "BEGIN DESCRIPTION:",
                "Auto-generated cross section at chainage 0.000 m",
                "END DESCRIPTION:",
                "#Sta/Elev= 4",
                "-10 290 -5 289 5 288 10 289",
                "#Mann= 3 ,0,0",
                "-10 .06 0 -5 .04 0 10 .06 0",
                "Bank Sta=-5,5",
                "XS Rating Curve= 0 ,0",
                "Type RM Length L Ch R = 1 ,0.000,0,0,0",
                "BEGIN DESCRIPTION:",
                "Auto-generated cross section at chainage 100.000 m",
                "END DESCRIPTION:",
                "#Sta/Elev= 4",
                "-8 280 -2 279 2 278 8 279",
                "#Mann= 3 ,0,0",
                "-8 .06 0 -2 .04 0 8 .06 0",
                "Bank Sta=-2,2",
                "XS Rating Curve= 0 ,0",
            ]
        )
        + "\n",
        encoding="cp1252",
    )
    with h5py.File(project / "Model.p01.hdf", "w") as hdf:
        hdf.create_group("Results")
        hdf.create_dataset("Results/Water Surface", data=[286.0, 279.0])
        hdf.create_dataset("Results/Energy Grade", data=[286.3, 279.2])
        hdf.create_dataset("Results/Velocity", data=[2.1, 1.8])
        hdf.create_dataset("Results/River Station", data=[100.0, 0.0])

    called = {"count": 0}

    def _fake_ai_report(report_id: str, context: dict[str, str], ai_config: AIAgentConfig, output_root: Path, require_ai: bool = False):
        reports_dir = output_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md = reports_dir / f"{report_id}_final_ai_report.md"
        docx = reports_dir / f"{report_id}_final_ai_report.docx"
        md.write_text("# Stub AI Report\n", encoding="utf-8")
        docx.write_text("stub", encoding="utf-8")
        return {"markdown": str(md), "docx": str(docx), "debug": ""}

    def _fake_compute(project_meta: dict[str, object], project_id: str):
        called["count"] += 1
        return (
            {
                "hdf_path": str(project / "Model.p01.hdf"),
                "plan_path": str(project / "Model.p01"),
                "log_path": "",
                "run_project_dir": str(project),
            },
            project,
        )

    monkeypatch.setattr("src.analyse.batch_analysis.build_ai_word_report_from_context", _fake_ai_report)
    monkeypatch.setattr("src.analyse.batch_analysis._compute_temp_copy", _fake_compute)

    manifest_path = analyze_project_folders(
        source_root=source_root,
        output_root=output_root,
        ai_config=AIAgentConfig(),
        strict=True,
        compute_missing_results=False,
        force_temp_compute=True,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["completed_count"] == 1
    assert called["count"] == 1
    assert manifest["projects"][0]["compute_mode"] == "temp_compute_clone_forced"
