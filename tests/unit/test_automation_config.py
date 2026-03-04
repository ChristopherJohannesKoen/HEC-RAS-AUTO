from __future__ import annotations

from pathlib import Path

from src.common.config import load_automation_config


def test_automation_config_parses_defaults() -> None:
    cfg = load_automation_config(Path("config/automation.yml"))
    assert cfg.autopilot.mode == "guardrailed"
    assert cfg.autopilot.scenario2.fixed_multiplier > 1.0
    assert cfg.autopilot.scenario2.tier_mode_enabled is True
    assert cfg.autopilot.scenario2.primary_tier == "average"
    assert len(cfg.autopilot.scenario2.tiers) >= 3
    tier_ids = {t.tier_id for t in cfg.autopilot.scenario2.tiers}
    assert {"lenient", "average", "conservative"}.issubset(tier_ids)
    assert isinstance(cfg.autopilot.stop_on, list)
