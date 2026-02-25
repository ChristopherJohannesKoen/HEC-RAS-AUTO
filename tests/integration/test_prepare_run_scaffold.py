from pathlib import Path

from src.ras.manual_steps import write_manual_compute_steps
from src.ras.ras_shell import clone_shell_project, stage_import_file


def test_prepare_run_scaffold(tmp_path: Path) -> None:
    shell = tmp_path / "shell"
    shell.mkdir(parents=True, exist_ok=True)
    (shell / "project.prj").write_text("dummy", encoding="utf-8")

    run_project = clone_shell_project(shell, run_id="baseline", runs_root=tmp_path / "runs")
    assert (run_project / "project.prj").exists()

    sdf = tmp_path / "RASImport.sdf"
    sdf.write_text("dummy sdf", encoding="utf-8")
    staged = stage_import_file(run_project, sdf)
    assert staged.exists()

    steps = write_manual_compute_steps(run_project)
    assert steps.exists()
