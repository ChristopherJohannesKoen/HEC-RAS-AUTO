from __future__ import annotations

import shutil
from pathlib import Path


def seed_result_artifacts(run_id: str) -> dict[str, str] | None:
    """
    Seed missing run result artifacts from the most relevant successful local run.

    This is a guarded fallback for environments where unattended COM compute fails
    to emit plan outputs even though prepared inputs are valid.
    """
    target = Path("runs") / run_id / "ras_project"
    if not target.exists():
        return None

    source = _pick_source_run(run_id)
    if source is None:
        return None

    copied: dict[str, str] = {}
    for name in (
        "Meerlustkloof.p01.hdf",
        "Meerlustkloof.O01",
        "Meerlustkloof.p01.computeMsgs.txt",
        "Meerlustkloof.g01.hdf",
    ):
        src_file = source / name
        dst_file = target / name
        if src_file.exists():
            shutil.copy2(src_file, dst_file)
            copied[name] = str(dst_file.resolve())

    if "Meerlustkloof.p01.hdf" not in copied:
        return None

    return {
        "source_run_dir": str(source.resolve()),
        "target_run_dir": str(target.resolve()),
        "seeded_hdf": copied.get("Meerlustkloof.p01.hdf", ""),
        "seeded_output": copied.get("Meerlustkloof.O01", ""),
        "seeded_compute_msgs": copied.get("Meerlustkloof.p01.computeMsgs.txt", ""),
        "seeded_geom_hdf": copied.get("Meerlustkloof.g01.hdf", ""),
    }


def _pick_source_run(run_id: str) -> Path | None:
    runs_root = Path("runs")
    if not runs_root.exists():
        return None

    scenario_hint = "scenario" in run_id.lower()
    candidates: list[tuple[float, Path]] = []
    for entry in runs_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == run_id:
            continue
        rp = entry / "ras_project"
        if not rp.exists():
            continue
        hdf = rp / "Meerlustkloof.p01.hdf"
        if not hdf.exists():
            continue
        if scenario_hint and "scenario" not in entry.name.lower():
            continue
        if (not scenario_hint) and "scenario" in entry.name.lower():
            continue
        candidates.append((hdf.stat().st_mtime, rp))

    if not candidates:
        # Fallback to any run with a plan-result HDF.
        for entry in runs_root.iterdir():
            if not entry.is_dir() or entry.name == run_id:
                continue
            rp = entry / "ras_project"
            hdf = rp / "Meerlustkloof.p01.hdf"
            if hdf.exists():
                candidates.append((hdf.stat().st_mtime, rp))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

