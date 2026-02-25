from __future__ import annotations

import re
from pathlib import Path

import h5py

from src.common.exceptions import HECRASRunMissingError


def locate_run_results(run_id: str, runs_root: Path = Path("runs")) -> dict[str, str]:
    run_dir = runs_root / run_id / "ras_project"
    if not run_dir.exists():
        raise HECRASRunMissingError(f"Run project directory not found: {run_dir}")

    hdfs_all = sorted(run_dir.rglob("*.hdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    logs = sorted(run_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    plans = sorted(run_dir.glob("*.p[0-9][0-9]"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not plans:
        raise HECRASRunMissingError(
            f"No plan file (*.p##) found for run '{run_id}'. Compute may not have executed."
        )

    latest_plan = plans[0]
    plan_id = _plan_id_from_path(latest_plan)
    hdfs = _plan_hdfs_for_id(hdfs_all, plan_id)
    if not hdfs:
        hdfs = [p for p in hdfs_all if _is_plan_result_hdf(p)]

    # Reject HDFs that are not result-like by content (e.g., geometry-only files).
    hdfs = [p for p in hdfs if _contains_result_groups(p)]

    if not hdfs:
        geom_hdfs = [p for p in hdfs_all if not _is_plan_result_hdf(p)]
        hint = f" Geometry-like HDFs found: {[p.name for p in geom_hdfs]}" if geom_hdfs else ""
        raise HECRASRunMissingError(
            f"No plan-result HDF found for run '{run_id}'.{hint}"
        )

    return {
        "run_id": run_id,
        "hdf_path": str(hdfs[0]),
        "plan_path": str(latest_plan),
        "log_path": str(logs[0]) if logs else "",
        "run_project_dir": str(run_dir),
    }


def _is_plan_result_hdf(path: Path) -> bool:
    name = path.name.lower()
    if name == "terrain.hdf":
        return False
    if re.search(r"\.g\d\d\.hdf$", name):
        return False
    if "geometry" in name:
        return False
    return bool(re.search(r"\.p\d\d\.hdf$", name) or "plan" in name or "results" in name)


def _plan_id_from_path(path: Path) -> str:
    m = re.search(r"\.p(\d\d)$", path.name.lower())
    if not m:
        return ""
    return m.group(1)


def _plan_hdfs_for_id(paths: list[Path], plan_id: str) -> list[Path]:
    if not plan_id:
        return []
    out = []
    for p in paths:
        n = p.name.lower()
        if re.search(rf"\.p{plan_id}(\..+)?\.hdf$", n):
            out.append(p)
    return out


def _contains_result_groups(path: Path) -> bool:
    try:
        with h5py.File(path, "r") as hdf:
            keys: list[str] = []
            hdf.visit(keys.append)
    except Exception:
        return False

    lowered = [k.lower() for k in keys]
    if any(k.startswith("results") for k in lowered):
        return True
    if any("output" in k for k in lowered):
        return True
    if any("water surface" in k or "velocity" in k or "energy" in k for k in lowered):
        return True
    return False
