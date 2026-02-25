from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from src.common.hashing import sha256_file
from src.models import ProjectConfig, ProjectManifest

logger = logging.getLogger(__name__)


def _required_file_map(config: ProjectConfig) -> dict[str, Path]:
    return {
        "info_xlsx": config.files.info_xlsx,
        "terrain_tif": config.files.terrain_tif,
        "projection_prj": config.files.projection_prj,
        "centerline_shp": config.files.centerline_shp,
        "kmz_right_bank_floodplain": config.kmz_points.chainage0_right_bank_floodplain,
        "kmz_right_bank_top": config.kmz_points.chainage0_right_bank_top,
    }


def _optional_file_map(config: ProjectConfig) -> dict[str, Path | None]:
    return {
        "contour_pdf": config.files.contour_pdf,
        "contour_dwg": config.files.contour_dwg,
        "kmz_station_0": config.kmz_points.station_0,
    }


def build_manifest(
    config: ProjectConfig,
    processed_dir: Path = Path("data/processed"),
    snapshot_dir: Path = Path("data/immutable_snapshot"),
) -> ProjectManifest:
    processed_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, Path] = {}
    hash_map: dict[str, str] = {}
    notes: list[str] = []

    for name, path in _required_file_map(config).items():
        if not path.exists():
            raise FileNotFoundError(f"Missing required input '{name}': {path}")
        files[name] = path
        hash_map[name] = sha256_file(path)
        _snapshot(path, snapshot_dir)

    for name, path in _optional_file_map(config).items():
        if path is None:
            continue
        if path.exists():
            files[name] = path
            hash_map[name] = sha256_file(path)
            _snapshot(path, snapshot_dir)
        else:
            note = f"Optional file missing: {name} -> {path}"
            notes.append(note)
            logger.warning(note)

    manifest = ProjectManifest(
        project_name=config.project.name,
        raw_dir=Path("data/raw"),
        target_crs_epsg=config.project.target_crs_epsg,
        files=files,
        hash_map=hash_map,
        notes=notes,
    )

    out_path = processed_dir / "project_manifest.json"
    out_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Wrote manifest: %s", out_path)
    return manifest


def _snapshot(src: Path, snapshot_dir: Path) -> None:
    dst = snapshot_dir / src.name
    if dst.exists():
        return
    shutil.copy2(src, dst)
