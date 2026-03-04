from __future__ import annotations

import json
from pathlib import Path

from src.models import SubmissionPackManifest


def build_submission_pack(
    base_run_id: str,
    scenario_run_id: str = "",
    scenario_run_ids: list[str] | None = None,
    primary_scenario_run_id: str = "",
    output_root: Path = Path("outputs"),
) -> Path:
    scenario_ids = [s for s in (scenario_run_ids or []) if str(s).strip()]
    if scenario_run_id and scenario_run_id not in scenario_ids:
        scenario_ids.append(scenario_run_id)
    if not scenario_ids and scenario_run_id:
        scenario_ids = [scenario_run_id]
    primary = primary_scenario_run_id or (scenario_run_id if scenario_run_id else "")
    if not primary and scenario_ids:
        primary = scenario_ids[0]

    submission_dir = output_root / base_run_id / "submission"
    submission_dir.mkdir(parents=True, exist_ok=True)
    manifest = SubmissionPackManifest(
        run_id=base_run_id,
        baseline_artifacts=_collect_run_artifacts(base_run_id, output_root),
        scenario_artifacts=_collect_run_artifacts(primary, output_root) if primary else {},
        scenario_runs={rid: _collect_run_artifacts(rid, output_root) for rid in scenario_ids},
        scenario_run_ids=scenario_ids,
        primary_scenario_run_id=primary,
        comparison_artifacts=_collect_comparison_artifacts(base_run_id, scenario_ids, output_root),
        report_paths=_collect_reports(base_run_id, scenario_ids, output_root),
        cad_paths=_collect_cad(base_run_id, scenario_ids, output_root),
        qa_paths=_collect_qa(base_run_id, scenario_ids, output_root),
        unresolved_verify_items=_collect_verify_items(base_run_id, scenario_ids, output_root),
    )
    manifest_path = submission_dir / "manifest.json"
    manifest.manifest_path = manifest_path
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    index_path = submission_dir / "README.md"
    index_path.write_text(_manifest_to_markdown(manifest), encoding="utf-8")
    return manifest_path


def _collect_run_artifacts(run_id: str, output_root: Path) -> dict[str, str]:
    out = {}
    for rel in [
        f"{run_id}/tables/metrics.csv",
        f"{run_id}/sections/required_sections.csv",
        f"{run_id}/plots/longitudinal_profile.png",
    ]:
        p = output_root / rel
        if p.exists():
            out[Path(rel).name] = str(p)
    exact_floodline = output_root / run_id / "gis" / "energy_floodline.geojson"
    if exact_floodline.exists():
        out["energy_floodline.geojson"] = str(exact_floodline)
    else:
        fallbacks = sorted((output_root / run_id / "gis").glob("energy_floodline_*.geojson")) if (output_root / run_id / "gis").exists() else []
        if fallbacks:
            out[fallbacks[-1].name] = str(fallbacks[-1])
    return out


def _collect_comparison_artifacts(base_run_id: str, scenario_run_ids: list[str], output_root: Path) -> dict[str, str]:
    out = {}
    candidates: list[Path] = [output_root / base_run_id / "comparison" / "scenario2_sweep_envelope.csv"]
    candidates.extend(
        [
            output_root / base_run_id / "comparison" / "scenario2_tier_comparison.csv",
            output_root / base_run_id / "comparison" / "scenario2_tier_envelope.csv",
            output_root / base_run_id / "comparison" / "scenario2_tier_overlay_profile.png",
        ]
    )
    for rid in scenario_run_ids:
        candidates.extend(
            [
                output_root / rid / "comparison" / "comparison_table.csv",
                output_root / rid / "comparison" / "overlay_longitudinal_profile.png",
            ]
        )
    for p in candidates:
        if p.exists():
            out[p.name] = str(p)
    return out


def _collect_reports(base_run_id: str, scenario_run_ids: list[str], output_root: Path) -> list[str]:
    out: list[str] = []
    reports_dir = output_root / "reports"
    exact: list[Path] = [
        reports_dir / f"{base_run_id}_report_draft.md",
        reports_dir / f"{base_run_id}_final_ai_report.md",
        reports_dir / f"{base_run_id}_final_ai_report.docx",
        reports_dir / f"{base_run_id}_scenario_2_triad_report_draft.md",
    ]
    for rid in scenario_run_ids:
        exact.extend(
            [
                reports_dir / f"{rid}_report_draft.md",
                reports_dir / f"{rid}_final_ai_report.md",
                reports_dir / f"{rid}_final_ai_report.docx",
            ]
        )
    for p in exact:
        if p.exists():
            out.append(str(p))

    # Include fallback DOCX names (e.g. when default file is locked and writer
    # emits <run>_final_ai_report_YYYYmmdd_HHMMSS.docx).
    for run_id in [base_run_id, *scenario_run_ids]:
        pattern = f"{run_id}_final_ai_report_*.docx"
        for p in sorted(reports_dir.glob(pattern)):
            sp = str(p)
            if sp not in out:
                out.append(sp)
    return out


def _collect_cad(base_run_id: str, scenario_run_ids: list[str], output_root: Path) -> list[str]:
    out = []
    for run_id in [base_run_id, *scenario_run_ids]:
        cad_dir = output_root / run_id / "cad"
        exact = cad_dir / "floodlines.dxf"
        if exact.exists():
            out.append(str(exact))
            continue
        fallbacks = sorted(cad_dir.glob("floodlines_*.dxf")) if cad_dir.exists() else []
        if fallbacks:
            out.append(str(fallbacks[-1]))
    return out


def _collect_qa(base_run_id: str, scenario_run_ids: list[str], output_root: Path) -> list[str]:
    out = []
    for run in [base_run_id, *scenario_run_ids]:
        qa_dir = output_root / run / "qa"
        if not qa_dir.exists():
            continue
        for p in qa_dir.glob("*.md"):
            out.append(str(p))
    return out


def _collect_verify_items(base_run_id: str, scenario_run_ids: list[str], output_root: Path) -> list[str]:
    items: list[str] = []
    report_dir = output_root / "reports"
    for run in [base_run_id, *scenario_run_ids]:
        p = report_dir / f"{run}_report_draft.md"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "[VERIFY]" in line or "[CITE]" in line:
                items.append(f"{p.name}: {line.strip()}")
    return items


def _manifest_to_markdown(manifest: SubmissionPackManifest) -> str:
    payload = json.loads(manifest.model_dump_json())
    lines = ["# Submission Pack", ""]
    lines.append("## Baseline Artifacts")
    for k, v in payload.get("baseline_artifacts", {}).items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Scenario Artifacts")
    for k, v in payload.get("scenario_artifacts", {}).items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Scenario Runs")
    lines.append(f"- Primary: `{payload.get('primary_scenario_run_id', '')}`")
    for rid, artifacts in payload.get("scenario_runs", {}).items():
        lines.append(f"- `{rid}`")
        for k, v in artifacts.items():
            lines.append(f"  - {k}: `{v}`")
    lines.append("")
    lines.append("## Comparison Artifacts")
    for k, v in payload.get("comparison_artifacts", {}).items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Reports")
    for v in payload.get("report_paths", []):
        lines.append(f"- `{v}`")
    lines.append("")
    lines.append("## Unresolved [VERIFY]/[CITE]")
    unresolved = payload.get("unresolved_verify_items", [])
    if unresolved:
        for item in unresolved:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)
