from __future__ import annotations

import shutil
from pathlib import Path


def clone_shell_project(shell_dir: Path, run_id: str, runs_root: Path = Path("runs")) -> Path:
    if not shell_dir.exists():
        raise FileNotFoundError(f"Shell project directory does not exist: {shell_dir}")
    run_project_dir = runs_root / run_id / "ras_project"
    if run_project_dir.exists():
        shutil.rmtree(run_project_dir)
    shutil.copytree(shell_dir, run_project_dir)
    return run_project_dir


def stage_import_file(run_project_dir: Path, sdf_path: Path, import_name: str = "RASImport.sdf") -> Path:
    import_dir = run_project_dir / "import"
    import_dir.mkdir(parents=True, exist_ok=True)
    dst = import_dir / import_name
    shutil.copy2(sdf_path, dst)
    return dst
