from __future__ import annotations

from pathlib import Path

from src.ras.ras_shell import clone_shell_project


def test_clone_shell_project_seeds_previous_run_files(tmp_path: Path) -> None:
    shell = tmp_path / "shell" / "ras_project"
    shell.mkdir(parents=True, exist_ok=True)
    (shell / "Meerlustkloof.prj").write_text("Proj Title=X\nSI Units\n", encoding="utf-8")

    prev = tmp_path / "ref" / "Previous run"
    prev.mkdir(parents=True, exist_ok=True)
    (prev / "EXAMPLE1.prj").write_text(
        "Proj Title=EX\nCurrent Plan=p01\nGeom File=g01\nFlow File=f01\nPlan File=p01\n",
        encoding="utf-8",
    )
    (prev / "EXAMPLE1.p01").write_text("Plan Title=P\nGeom File=g01\n", encoding="utf-8")
    (prev / "EXAMPLE1.f01").write_text("Flow Title=F\n", encoding="utf-8")
    (prev / "EXAMPLE1.g01").write_text("Geom Title=G\n", encoding="utf-8")

    old_cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        out = clone_shell_project(shell, run_id="r1", runs_root=Path("runs"))
    finally:
        os.chdir(old_cwd)

    if not out.is_absolute():
        out = tmp_path / out

    assert (out / "Meerlustkloof.p01").exists()
    assert (out / "Meerlustkloof.f01").exists()
    assert (out / "Meerlustkloof.g01").exists()
    prj = (out / "Meerlustkloof.prj").read_text(encoding="utf-8")
    assert "Current Plan=p01" in prj
    assert "Flow File=f01" in prj
