from __future__ import annotations

import json
from pathlib import Path

from src.models import SubmissionPackManifest


def build_submission_pack(
    base_run_id: str,
    scenario_run_id: str,
    output_root: Path = Path("outputs"),
) -> Path:
    submission_dir = output_root / base_run_id / "submission"
    submission_dir.mkdir(parents=True, exist_ok=True)
    manifest = SubmissionPackManifest(
        run_id=base_run_id,
        baseline_artifacts=_collect_run_artifacts(base_run_id, output_root),
        scenario_artifacts=_collect_run_artifacts(scenario_run_id, output_root),
        comparison_artifacts=_collect_comparison_artifacts(base_run_id, scenario_run_id, output_root),
        report_paths=_collect_reports(base_run_id, scenario_run_id, output_root),
        cad_paths=_collect_cad(base_run_id, scenario_run_id, output_root),
        qa_paths=_collect_qa(base_run_id, scenario_run_id, output_root),
        unresolved_verify_items=_collect_verify_items(base_run_id, scenario_run_id, output_root),
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
        f"{run_id}/gis/energy_floodline.geojson",
    ]:
        p = output_root / rel
        if p.exists():
            out[Path(rel).name] = str(p)
    return out


def _collect_comparison_artifacts(base_run_id: str, scenario_run_id: str, output_root: Path) -> dict[str, str]:
    out = {}
    candidates = [
        output_root / scenario_run_id / "comparison" / "comparison_table.csv",
        output_root / scenario_run_id / "comparison" / "overlay_longitudinal_profile.png",
        output_root / base_run_id / "comparison" / "scenario2_sweep_envelope.csv",
    ]
    for p in candidates:
        if p.exists():
            out[p.name] = str(p)
    return out


def _collect_reports(base_run_id: str, scenario_run_id: str, output_root: Path) -> list[str]:
    out = []
    for p in [
        output_root / "reports" / f"{base_run_id}_report_draft.md",
        output_root / "reports" / f"{scenario_run_id}_report_draft.md",
    ]:
        if p.exists():
            out.append(str(p))
    return out


def _collect_cad(base_run_id: str, scenario_run_id: str, output_root: Path) -> list[str]:
    out = []
    for p in [
        output_root / base_run_id / "cad" / "floodlines.dxf",
        output_root / scenario_run_id / "cad" / "floodlines.dxf",
    ]:
        if p.exists():
            out.append(str(p))
    return out


def _collect_qa(base_run_id: str, scenario_run_id: str, output_root: Path) -> list[str]:
    out = []
    for run in [base_run_id, scenario_run_id]:
        qa_dir = output_root / run / "qa"
        if not qa_dir.exists():
            continue
        for p in qa_dir.glob("*.md"):
            out.append(str(p))
    return out


def _collect_verify_items(base_run_id: str, scenario_run_id: str, output_root: Path) -> list[str]:
    items: list[str] = []
    report_dir = output_root / "reports"
    for run in [base_run_id, scenario_run_id]:
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
