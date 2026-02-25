from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.models import ProjectConfig, SheetsConfig, ThresholdConfig
from src.models.scenario import ScenarioSpec


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in YAML: {path}")
    return data


def load_project_config(path: Path) -> ProjectConfig:
    return ProjectConfig.model_validate(load_yaml(path))


def load_threshold_config(path: Path) -> ThresholdConfig:
    return ThresholdConfig.model_validate(load_yaml(path))


def load_sheets_config(path: Path) -> SheetsConfig:
    return SheetsConfig.model_validate(load_yaml(path))


def load_scenario_spec(path: Path) -> ScenarioSpec:
    return ScenarioSpec.model_validate(load_yaml(path))
