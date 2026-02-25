from __future__ import annotations

from pathlib import Path

from src.common.config import load_scenario_spec
from src.models.scenario import ScenarioSpec


def load_scenario(path: Path) -> ScenarioSpec:
    return load_scenario_spec(path)
