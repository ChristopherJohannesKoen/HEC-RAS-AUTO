from __future__ import annotations

from pathlib import Path

from src.common.exceptions import HECRASRunMissingError


def locate_run_results(run_id: str, runs_root: Path = Path("runs")) -> dict[str, str]:
    run_dir = runs_root / run_id / "ras_project"
    if not run_dir.exists():
        raise HECRASRunMissingError(f"Run project directory not found: {run_dir}")

    hdfs = sorted(run_dir.rglob("*.hdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    logs = sorted(run_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not hdfs:
        raise HECRASRunMissingError(
            f"No HDF results found for run '{run_id}'. Complete manual compute first."
        )
    return {
        "run_id": run_id,
        "hdf_path": str(hdfs[0]),
        "log_path": str(logs[0]) if logs else "",
        "run_project_dir": str(run_dir),
    }
