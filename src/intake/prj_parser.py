from __future__ import annotations

from pathlib import Path

import pyproj

from src.common.exceptions import CRSMismatchError


def parse_prj_epsg(prj_path: Path) -> int | None:
    text = prj_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    crs = pyproj.CRS.from_wkt(text)
    epsg = crs.to_epsg()
    return epsg


def validate_target_crs(prj_path: Path, target_epsg: int) -> int:
    parsed = parse_prj_epsg(prj_path)
    if parsed is None:
        return target_epsg
    if parsed != target_epsg:
        raise CRSMismatchError(
            f"CRS mismatch: PRJ indicates EPSG:{parsed} but config target is EPSG:{target_epsg}"
        )
    return parsed
