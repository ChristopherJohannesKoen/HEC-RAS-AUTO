from __future__ import annotations

import json
from pathlib import Path

from src.reporting.submission_pack import build_submission_pack


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_submission_pack_includes_all_scenario_tiers(tmp_path: Path) -> None:
    out = tmp_path / "outputs"
    base = "prompt_live_run"
    runs = [
        f"{base}_scenario_2_lenient",
        f"{base}_scenario_2_average",
        f"{base}_scenario_2_conservative",
    ]
    primary = f"{base}_scenario_2_average"

    _touch(out / base / "tables" / "metrics.csv")
    _touch(out / base / "sections" / "required_sections.csv")
    _touch(out / base / "plots" / "longitudinal_profile.png")
    _touch(out / base / "cad" / "floodlines.dxf")
    _touch(out / base / "qa" / "hydraulic_qa.md")

    for rid in runs:
        _touch(out / rid / "tables" / "metrics.csv")
        _touch(out / rid / "sections" / "required_sections.csv")
        _touch(out / rid / "plots" / "longitudinal_profile.png")
        _touch(out / rid / "cad" / "floodlines.dxf")
        _touch(out / rid / "qa" / "hydraulic_qa.md")
        _touch(out / "reports" / f"{rid}_report_draft.md", text="scenario report")

    _touch(out / base / "comparison" / "scenario2_tier_comparison.csv")
    _touch(out / base / "comparison" / "scenario2_tier_envelope.csv")
    _touch(out / base / "comparison" / "scenario2_tier_overlay_profile.png")
    _touch(out / "reports" / f"{base}_report_draft.md", text="baseline report")
    _touch(out / "reports" / f"{base}_scenario_2_triad_report_draft.md", text="triad report")

    manifest_path = build_submission_pack(
        base_run_id=base,
        scenario_run_ids=runs,
        primary_scenario_run_id=primary,
        output_root=out,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["primary_scenario_run_id"] == primary
    assert set(payload["scenario_run_ids"]) == set(runs)
    assert set(payload["scenario_runs"].keys()) == set(runs)
