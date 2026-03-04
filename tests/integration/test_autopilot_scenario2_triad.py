from __future__ import annotations

from pathlib import Path

from src.cli import main as cli


class _DummyCfg:
    pass


class _DummyAIConfigWrap:
    class _AI:
        pass

    ai = _AI()


class _DummyAdvisor:
    def __init__(self, *_args, **_kwargs) -> None:
        self.last_prompt_type = "anomaly_triage"
        self.last_response_id = None

    def anomaly_triage(self, _msg: str) -> str:
        return "ok"


class _DummyOrchestrator:
    def __init__(self, run_id: str, *_args, **_kwargs) -> None:
        self._dir = Path("outputs") / run_id / "autopilot"
        self._dir.mkdir(parents=True, exist_ok=True)

    def step(self, _name: str, fn):
        return fn()

    def set_artifact(self, *_args, **_kwargs) -> None:
        return None

    def log_action(self, *_args, **_kwargs) -> None:
        return None

    def complete(self) -> None:
        return None


def test_autopilot_runs_named_scenario2_tiers(monkeypatch) -> None:
    called_run_ids: list[str] = []

    monkeypatch.setattr(cli, "load_project_config", lambda *_a, **_k: _DummyCfg())
    monkeypatch.setattr(cli, "load_ai_config", lambda *_a, **_k: _DummyAIConfigWrap())
    monkeypatch.setattr(cli, "OpenAIAdvisor", _DummyAdvisor)
    monkeypatch.setattr(cli, "AutopilotOrchestrator", _DummyOrchestrator)
    monkeypatch.setattr(
        cli,
        "stage_inputs_from_source",
        lambda *_a, **_k: {"copied": [], "missing": [], "skipped": [], "removed": []},
    )
    monkeypatch.setattr(cli, "run_doctor_checks", lambda *_a, **_k: {"python_ok": True})
    monkeypatch.setattr(cli, "summarize_doctor", lambda *_a, **_k: "ok")
    monkeypatch.setattr(cli, "init", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "ingest", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "complete_xs", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "build_geometry", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "prepare_run", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "run_hecras", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "import_results", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "analyze", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_enforce_real_hydraulics", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "compare", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "build_report_cmd", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "compare_scenario2_tiers", lambda *_a, **_k: {})
    monkeypatch.setattr(cli, "build_scenario2_triad_report", lambda *_a, **_k: Path("triad.md"))

    def _fake_apply(**kwargs) -> None:
        called_run_ids.append(str(kwargs["run_id"]))

    monkeypatch.setattr(cli, "apply_scenario_with_multiplier", _fake_apply)

    cli.autopilot(
        source="ref",
        run_id="triad_test_run",
        scenario2=True,
        sweep="",
        strict=False,
        config=Path("config/project.yml"),
        sheets=Path("config/sheets.yml"),
        thresholds=Path("config/thresholds.yml"),
        automation=Path("config/automation.yml"),
        ai=Path("config/ai.yml"),
    )

    assert "triad_test_run_scenario_2_lenient" in called_run_ids
    assert "triad_test_run_scenario_2_average" in called_run_ids
    assert "triad_test_run_scenario_2_conservative" in called_run_ids
