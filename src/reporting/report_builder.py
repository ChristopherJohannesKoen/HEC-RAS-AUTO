from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from src.reporting.figures import figure_list_markdown
from src.reporting.narrative import build_qa_status, build_summary, scenario_notes
from src.reporting.tables import load_input_summary, load_metrics_markdown


def build_report(
    run_id: str,
    template_path: Path = Path("templates/report.md.j2"),
    output_root: Path = Path("outputs"),
) -> Path:
    template = Template(template_path.read_text(encoding="utf-8"))
    rendered = template.render(
        run_id=run_id,
        summary=build_summary(run_id),
        input_summary=load_input_summary(run_id),
        qa_status=build_qa_status(run_id),
        metrics_table=load_metrics_markdown(run_id),
        figure_list=figure_list_markdown(run_id),
        scenario_notes=scenario_notes(run_id),
        assumptions=[
            "[VERIFY] Confirm bank station placements in HEC-RAS geometry editor.",
            "[VERIFY] Confirm selected flow regime (subcritical/supercritical/mixed).",
            "[VERIFY] Confirm energy-line-based floodline interpretation for final CAD deliverable.",
        ],
    )
    out_dir = output_root / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}_report_draft.md"
    out_path.write_text(rendered, encoding="utf-8")
    return out_path
