from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def build_project_audit_report(
    project_id: str,
    output_root: Path,
    project_meta: dict[str, object],
    compute_mode: str,
) -> Path:
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{project_id}_audit_report_draft.md"

    metrics_table = _load_csv_markdown(output_root / "tables" / "metrics.csv", rows=10)
    section_table = _load_csv_markdown(output_root / "sections" / "all_sections.csv", rows=24)
    hdf_table = _load_csv_markdown(output_root / "artifacts" / "hdf_hydraulic_signals.csv", rows=20)
    qa_md = _read_text(output_root / "qa" / "hydraulic_qa.md")
    inventory_path = output_root / "inventory" / "project_inventory.json"
    flow_summary_path = output_root / "inventory" / "flow_summary.json"
    geom_summary_path = output_root / "inventory" / "geometry_summary.json"
    batch_notes_path = output_root / "inventory" / "analysis_notes.json"

    model_types = ", ".join(project_meta.get("model_types", [])) if isinstance(project_meta.get("model_types"), list) else "unknown"
    active_plan = project_meta.get("active_plan_file", "")
    geometry_file = project_meta.get("geometry_file", "")
    flow_file = project_meta.get("steady_flow_file", "")
    source_snapshot = project_meta.get("source_snapshot", {}) if isinstance(project_meta.get("source_snapshot"), dict) else {}

    lines = [
        f"# {project_meta.get('project_name', project_id)} Hydraulic Audit",
        "",
        "## Summary",
        "",
        f"- Source folder: `{project_meta.get('project_dir', '')}`",
        f"- Active plan: `{active_plan}`",
        f"- Geometry file: `{geometry_file}`",
        f"- Steady flow file: `{flow_file}`",
        f"- Detected model types: `{model_types}`",
        f"- Compute mode: `{compute_mode}`",
        f"- Source folder unchanged: `{bool(source_snapshot)}`",
        "",
        "## Inventory",
        "",
        f"- Project inventory JSON: `{inventory_path}`",
        f"- Flow summary JSON: `{flow_summary_path}`",
        f"- Geometry summary JSON: `{geom_summary_path}`",
        f"- Analysis notes JSON: `{batch_notes_path}`",
        "",
        "## Hydraulic Signals",
        "",
        hdf_table or "_No hydraulic signal summary available._",
        "",
        "## Metrics",
        "",
        metrics_table or "_No metrics were computed for this project._",
        "",
        "## All Sections",
        "",
        section_table or "_No section table was generated for this project._",
        "",
        "## QA Notes",
        "",
        qa_md or "_No QA notes were generated for this project._",
        "",
        "## Limitations",
        "",
        "- This report is a read-only audit of an existing HEC-RAS project folder.",
        "- No file inside the source project folder was modified during analysis.",
        "- Floodline and CAD outputs are only included when map-space geometry is available.",
        "- Unsupported or missing project components are surfaced explicitly as partial-analysis gaps.",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def build_project_ai_context(
    project_meta: dict[str, object],
    output_root: Path,
    draft_report_path: Path,
    compute_mode: str,
) -> dict[str, str]:
    return {
        "prompt_text": (
            "Write a full hydraulic audit report for an existing HEC-RAS project folder. "
            "Use only the extracted project metadata, tables, plots, QA notes, and compute notes. "
            "State clearly that the source folder was not modified."
        ),
        "project_metadata_json": json.dumps(_safe_json(project_meta), indent=2)[:40000],
        "compute_mode": compute_mode,
        "report_draft_md": _read_text(draft_report_path, limit=40000),
        "metrics_csv": _read_text(output_root / "tables" / "metrics.csv", limit=20000),
        "required_sections_csv": _read_text(output_root / "sections" / "all_sections.csv", limit=20000),
        "hydraulic_qa_md": _read_text(output_root / "qa" / "hydraulic_qa.md", limit=12000),
        "regime_recommendation_md": _read_text(output_root / "qa" / "project_analysis.md", limit=12000),
        "inventory_json": _read_text(output_root / "inventory" / "project_inventory.json", limit=20000),
        "geometry_summary_json": _read_text(output_root / "inventory" / "geometry_summary.json", limit=20000),
        "flow_summary_json": _read_text(output_root / "inventory" / "flow_summary.json", limit=12000),
    }


def _load_csv_markdown(path: Path, rows: int = 20) -> str:
    if not path.exists():
        return ""
    try:
        df = pd.read_csv(path)
    except Exception:
        return ""
    if df.empty:
        return ""
    head = df.head(rows).fillna("")
    columns = [str(col) for col in head.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in head.iterrows():
        values = [str(row[col]).replace("\n", " ").replace("|", "\\|") for col in head.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _read_text(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]


def _safe_json(payload: dict[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(payload, default=str))
