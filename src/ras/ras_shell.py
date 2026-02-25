from __future__ import annotations

import re
import shutil
import time
from pathlib import Path


def clone_shell_project(shell_dir: Path, run_id: str, runs_root: Path = Path("runs")) -> Path:
    if not shell_dir.exists():
        raise FileNotFoundError(f"Shell project directory does not exist: {shell_dir}")
    run_project_dir = runs_root / run_id / "ras_project"
    if run_project_dir.exists():
        _safe_remove_dir(run_project_dir)
    shutil.copytree(shell_dir, run_project_dir)
    _seed_project_from_previous_run(run_project_dir, previous_run_dir=Path("ref") / "Previous run")
    return run_project_dir


def stage_import_file(run_project_dir: Path, sdf_path: Path, import_name: str = "RASImport.sdf") -> Path:
    import_dir = run_project_dir / "import"
    import_dir.mkdir(parents=True, exist_ok=True)
    dst = import_dir / import_name
    shutil.copy2(sdf_path, dst)
    return dst


def _safe_remove_dir(path: Path, retries: int = 3, delay_sec: float = 0.5) -> None:
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            shutil.rmtree(path)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(delay_sec)
    if last_exc is not None:
        raise PermissionError(
            f"Could not remove existing run directory due to a file lock: {path}. "
            "Close any process using files in this directory and retry."
        ) from last_exc


def _seed_project_from_previous_run(run_project_dir: Path, previous_run_dir: Path) -> None:
    """
    If shell project lacks steady-flow plan context, seed minimal p/f/g files
    from a known-good prior run template under ref/Previous run.
    """
    project_file = next(run_project_dir.glob("*.prj"), None)
    if project_file is None:
        return
    project_stem = project_file.stem

    has_plan = any(run_project_dir.glob(f"{project_stem}.p[0-9][0-9]"))
    has_flow = any(run_project_dir.glob(f"{project_stem}.f[0-9][0-9]"))
    if has_plan and has_flow:
        _ensure_project_refs(project_file)
        return

    if not previous_run_dir.exists():
        _ensure_project_refs(project_file)
        return

    template_prj = next(previous_run_dir.glob("*.prj"), None)
    if template_prj is None:
        _ensure_project_refs(project_file)
        return
    template_stem = template_prj.stem

    copied_any = False
    for src in previous_run_dir.iterdir():
        if not src.is_file():
            continue
        # Accept extension like .p01/.f01/.g01/.r01 only (no .hdf/.o01 outputs).
        if re.match(r"^\.[pfgr][0-9][0-9]$", src.suffix.lower()) is None:
            continue
        if not src.name.lower().startswith(template_stem.lower() + "."):
            continue
        dst = run_project_dir / f"{project_stem}{src.suffix.lower()}"
        shutil.copy2(src, dst)
        copied_any = True

    if copied_any:
        _ensure_project_refs(project_file)
    else:
        _ensure_project_refs(project_file)


def _ensure_project_refs(project_file: Path) -> None:
    text = project_file.read_text(encoding="cp1252", errors="ignore")
    lines = text.splitlines()
    lines = _upsert_key_line(lines, "Current Plan", "p01")
    lines = _upsert_key_line(lines, "Geom File", "g01")
    lines = _upsert_key_line(lines, "Flow File", "f01")
    lines = _upsert_key_line(lines, "Plan File", "p01")
    # Keep legacy Windows encoding/newlines for maximum HEC-RAS compatibility.
    project_file.write_text("\r\n".join(lines) + "\r\n", encoding="cp1252")


def _upsert_key_line(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}"
            return lines
    # Insert near top for readability.
    insert_at = 1 if lines else 0
    lines.insert(insert_at, f"{prefix}{value}")
    return lines
