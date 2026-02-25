from __future__ import annotations

from pathlib import Path


ROOT = Path.cwd()
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
RUNS_DIR = ROOT / "runs"
OUTPUTS_DIR = ROOT / "outputs"
LOGS_DIR = ROOT / "logs"


def ensure_repo_paths() -> None:
    for path in [CONFIG_DIR, DATA_DIR, RAW_DIR, PROCESSED_DIR, RUNS_DIR, OUTPUTS_DIR, LOGS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def run_dir(run_id: str) -> Path:
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(run_id: str) -> Path:
    path = OUTPUTS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path
