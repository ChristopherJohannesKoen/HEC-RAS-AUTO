from __future__ import annotations

import shutil
from pathlib import Path

from src.models import ProjectConfig


def stage_inputs_from_source(
    config: ProjectConfig,
    source_dir: Path,
    overwrite: bool = True,
    purge_missing: bool = False,
) -> dict[str, list[str]]:
    """
    Copy required raw inputs from a source folder (e.g. ref/) into configured paths.
    Search is recursive by filename to support arbitrary source subfolder layouts.
    """
    if not source_dir.exists():
        raise FileNotFoundError(f"Source folder not found: {source_dir}")

    copied: list[str] = []
    missing: list[str] = []
    skipped: list[str] = []
    removed: list[str] = []

    expected = _expected_paths(config)
    for target in expected:
        if target is None:
            continue
        target = Path(target)
        match = _find_by_name(source_dir, target.name)
        if match is None:
            missing.append(target.name)
            if purge_missing:
                removed.extend(_remove_target_if_exists(target))
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if match.resolve() == target.resolve():
            skipped.append(str(target))
            continue
        if target.exists() and not overwrite:
            skipped.append(str(target))
        else:
            shutil.copy2(match, target)
            copied.append(str(target))

        if target.suffix.lower() == ".shp":
            copied.extend(_copy_shapefile_sidecars(match, target, overwrite))

    return {"copied": copied, "missing": missing, "skipped": skipped, "removed": removed}


def _expected_paths(config: ProjectConfig) -> list[Path | None]:
    return [
        config.files.contour_pdf,
        config.files.contour_dwg,
        config.files.info_xlsx,
        config.files.terrain_tif,
        config.files.projection_prj,
        config.files.centerline_shp,
        config.kmz_points.station_0,
        config.kmz_points.chainage0_right_bank_floodplain,
        config.kmz_points.chainage0_right_bank_top,
    ]


def _find_by_name(source_dir: Path, filename: str) -> Path | None:
    for p in source_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() == filename.lower():
            return p
    return None


def _copy_shapefile_sidecars(source_shp: Path, target_shp: Path, overwrite: bool) -> list[str]:
    copied: list[str] = []
    for ext in (".dbf", ".shx", ".prj", ".cpg", ".qmd"):
        src = source_shp.with_suffix(ext)
        if not src.exists():
            continue
        dst = target_shp.with_suffix(ext)
        if dst.exists() and not overwrite:
            continue
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def _remove_target_if_exists(target: Path) -> list[str]:
    removed: list[str] = []
    try:
        if target.exists():
            target.unlink()
            removed.append(str(target))
    except Exception:
        return removed

    if target.suffix.lower() == ".shp":
        for ext in (".dbf", ".shx", ".prj", ".cpg", ".qmd"):
            side = target.with_suffix(ext)
            try:
                if side.exists():
                    side.unlink()
                    removed.append(str(side))
            except Exception:
                continue
    return removed
