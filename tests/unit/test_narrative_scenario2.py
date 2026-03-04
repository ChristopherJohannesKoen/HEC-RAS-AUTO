from __future__ import annotations

import json
from pathlib import Path

from src.reporting.narrative import scenario_notes


def test_scenario_notes_detects_nested_scenario2_run_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    run_id = "prompt_live_run_scenario_2_conservative"
    meta = tmp_path / "runs" / run_id / "flow" / "scenario_metadata.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"tier_id": "conservative"}), encoding="utf-8")
    text = scenario_notes(run_id)
    assert "Scenario 2" in text
    assert "conservative" in text.lower()
