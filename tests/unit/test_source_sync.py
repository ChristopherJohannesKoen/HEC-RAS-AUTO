from __future__ import annotations

import os
from pathlib import Path

from src.common.config import load_project_config
from src.intake.source_sync import stage_inputs_from_source


def test_stage_inputs_from_source_copies_expected_files(tmp_path: Path) -> None:
    repo = tmp_path
    source = repo / "ref"
    source.mkdir(parents=True, exist_ok=True)
    raw = repo / "data" / "raw" / "meerlustkloof"
    raw.mkdir(parents=True, exist_ok=True)
    config_dir = repo / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    files = [
        "Meerlustkloof Info.xlsx",
        "Meerlustkloof_Geo.tif",
        "Meerlustkloof_Projection.prj",
        "Meerlustkloof_Projection.shp",
        "Meerlustkloof_Projection.dbf",
        "Meerlustkloof_Projection.shx",
        "Chainage 0m (Station 3905m) Right Bank Floodplain.kmz",
        "Chainage 0m (Station 3905m) Right Bank Top.kmz",
    ]
    for name in files:
        (source / name).write_text("x", encoding="utf-8")

    cfg_text = """
project:
  name: "x"
  river_name: "r"
  reach_name: "main"
  target_crs_epsg: 4326
files:
  info_xlsx: "data/raw/meerlustkloof/Meerlustkloof Info.xlsx"
  terrain_tif: "data/raw/meerlustkloof/Meerlustkloof_Geo.tif"
  projection_prj: "data/raw/meerlustkloof/Meerlustkloof_Projection.prj"
  centerline_shp: "data/raw/meerlustkloof/Meerlustkloof_Projection.shp"
kmz_points:
  chainage0_right_bank_floodplain: "data/raw/meerlustkloof/Chainage 0m (Station 3905m) Right Bank Floodplain.kmz"
  chainage0_right_bank_top: "data/raw/meerlustkloof/Chainage 0m (Station 3905m) Right Bank Top.kmz"
hydraulics:
  mannings_channel: 0.04
  mannings_floodplain: 0.06
  upstream_q_100: 375.0
  tributary_q_100: 550.0
  tributary_chainage_m: 1500.0
  upstream_normal_depth_slope: 0.0215
  downstream_normal_depth_slope: 0.00725
hec_ras:
  shell_project_dir: "shell/ras_project"
"""
    cfg_path = config_dir / "project.yml"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    cfg = load_project_config(cfg_path)

    old_cwd = Path.cwd()
    try:
        # Relative config paths resolve from repository root during normal CLI execution.
        os.chdir(repo)
        report = stage_inputs_from_source(cfg, source)
    finally:
        os.chdir(old_cwd)

    assert not report["missing"]
    assert (raw / "Meerlustkloof Info.xlsx").exists()
    assert (raw / "Meerlustkloof_Projection.dbf").exists()
