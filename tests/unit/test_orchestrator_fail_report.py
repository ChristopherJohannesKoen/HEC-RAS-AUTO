from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.orchestrator import AutopilotOrchestrator


def test_orchestrator_writes_fail_report(tmp_path: Path) -> None:
    orch = AutopilotOrchestrator(run_id="r1", output_root=tmp_path)

    def bad():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        orch.step("x", bad)

    fail = tmp_path / "r1" / "autopilot" / "fail_report.json"
    assert fail.exists()
    state = tmp_path / "r1" / "autopilot" / "state.json"
    assert state.exists()
