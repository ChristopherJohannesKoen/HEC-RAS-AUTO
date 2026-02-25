from __future__ import annotations

from pathlib import Path

from src.common.config import load_automation_config


def test_automation_config_parses_defaults() -> None:
    cfg = load_automation_config(Path("config/automation.yml"))
    assert cfg.autopilot.mode == "guardrailed"
    assert cfg.autopilot.scenario2.fixed_multiplier > 1.0
    assert isinstance(cfg.autopilot.stop_on, list)
