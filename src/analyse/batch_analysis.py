from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

import pandas as pd

from src.analyse.project_parser import (
    build_flow_payload_from_summary,
    build_station_map_df,
    parse_hecras_project,
    snapshot_project_tree,
    write_project_geometry_outputs,
)
from src.common.config import load_threshold_config
from src.common.exceptions import HECRASRunMissingError
from src.models import AIAgentConfig
from src.post.cad_export import export_floodline_dxf
from src.post.extract_sections import extract_all_sections
from src.post.floodline_mapper import export_energy_floodline
from src.post.long_profile import build_longitudinal_profile
from src.post.metrics import compute_metrics
from src.qa.hydraulic_qa import run_hydraulic_qa
from src.ras.controller_adapter import HECRASControllerAdapter
from src.ras.hdf_reader import (
    discover_hdf_paths,
    extract_hydraulic_signals,
    extract_numeric_datasets,
    extract_profile_values_with_station_map,
)
from src.ras.ras_log_parser import parse_ras_log
from src.ras.ras_shell import clone_shell_project
from src.ras.result_locator import locate_project_results
from src.reporting.ai_word_report import build_ai_word_report_from_context
from src.reporting.project_audit_report import build_project_ai_context, build_project_audit_report

logger = logging.getLogger(__name__)


def analyze_project_folders(
    source_root: Path,
    output_root: Path,
    ai_config: AIAgentConfig,
    strict: bool = False,
    compute_missing_results: bool = True,
    force_temp_compute: bool = False,
    thresholds_path: Path = Path("config/thresholds.yml"),
) -> Path:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    thresholds = load_threshold_config(thresholds_path)

    project_dirs = sorted([path for path in source_root.iterdir() if path.is_dir()], key=lambda p: p.name.lower())
    manifest_rows: list[dict[str, object]] = []

    for project_dir in project_dirs:
        try:
            result = _analyze_single_project(
                project_dir=project_dir,
                output_root=output_root,
                ai_config=ai_config,
                thresholds=thresholds,
                compute_missing_results=compute_missing_results,
                force_temp_compute=force_temp_compute,
            )
            manifest_rows.append(result)
        except Exception as exc:
            logger.exception("Project batch analysis failed for %s", project_dir)
            manifest_rows.append(
                {
                    "project_name": project_dir.name,
                    "project_dir": str(project_dir),
                    "status": "failed",
                    "error": str(exc),
                }
            )
            if strict:
                _write_batch_outputs(output_root, manifest_rows)
                raise

    return _write_batch_outputs(output_root, manifest_rows)


def _analyze_single_project(
    project_dir: Path,
    output_root: Path,
    ai_config: AIAgentConfig,
    thresholds,
    compute_missing_results: bool,
    force_temp_compute: bool,
) -> dict[str, object]:
    project_meta = parse_hecras_project(project_dir)
    project_id = _slugify(str(project_meta.get("project_name", project_dir.name)))
    project_out = output_root / project_id
    inventory_dir = project_out / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)

    _write_json(inventory_dir / "project_inventory.json", project_meta.get("inventory", {}))
    _write_json(inventory_dir / "project_metadata.json", project_meta)
    _write_json(inventory_dir / "flow_summary.json", project_meta.get("flow_summary", {}))
    _write_json(inventory_dir / "source_snapshot_before.json", project_meta.get("source_snapshot", {}))

    geometry_summary = project_meta.get("geometry_summary", {})
    geometry_outputs = write_project_geometry_outputs(geometry_summary, inventory_dir)
    station_map_df = build_station_map_df(geometry_summary)
    _write_json(inventory_dir / "geometry_summary.json", _safe_jsonable_geometry_summary(geometry_summary))

    analysis_notes: dict[str, object] = {
        "project_name": project_dir.name,
        "project_id": project_id,
        "source_folder_unchanged": True,
        "compute_mode": "existing_results",
        "messages": [],
        "artifacts": {},
    }

    result_info: dict[str, str] | None = None
    result_project_dir = project_dir
    existing_result_info: dict[str, str] | None = None
    steady_capable = "steady" in set(project_meta.get("model_types", []))

    try:
        existing_result_info = locate_project_results(project_dir, label=project_dir.name)
        analysis_notes["messages"].append("Existing result artifacts were found in the source project folder.")
    except HECRASRunMissingError as exc:
        analysis_notes["messages"].append(f"Existing results not found: {exc}")

    if force_temp_compute and steady_capable:
        try:
            result_info, result_project_dir = _compute_temp_copy(project_meta, project_id)
            analysis_notes["compute_mode"] = "temp_compute_clone_forced"
            analysis_notes["messages"].append(
                f"Computed a temporary clone under {result_project_dir} because force_temp_compute was enabled."
            )
        except Exception as exc:
            analysis_notes["messages"].append(f"Forced temp compute failed: {exc}")
            if existing_result_info is not None:
                result_info = existing_result_info
                result_project_dir = project_dir
                analysis_notes["compute_mode"] = "existing_results_after_compute_fallback"
                analysis_notes["messages"].append(
                    "Fell back to existing source-folder results after temp compute failure."
                )
            else:
                raise
    else:
        if existing_result_info is not None:
            result_info = existing_result_info
            analysis_notes["compute_mode"] = "existing_results"
            analysis_notes["messages"].append("Using existing result artifacts for downstream analysis.")
        elif compute_missing_results and steady_capable:
            result_info, result_project_dir = _compute_temp_copy(project_meta, project_id)
            analysis_notes["compute_mode"] = "temp_compute_clone"
            analysis_notes["messages"].append(
                f"Computed a temporary clone under {result_project_dir} because the source folder lacked usable results."
            )
        else:
            analysis_notes["compute_mode"] = "no_results_available"

    log_issues: list[dict[str, object]] = []
    if result_info is not None:
        artifact_dir = project_out / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _write_json(artifact_dir / "run_artifacts.json", result_info)

        hdf_path = Path(result_info["hdf_path"])
        _write_json(artifact_dir / "hdf_keys.json", discover_hdf_paths(hdf_path))
        extract_numeric_datasets(hdf_path, artifact_dir / "hdf_numeric_summary.csv")
        extract_hydraulic_signals(hdf_path, artifact_dir / "hdf_hydraulic_signals.csv")
        extract_profile_values_with_station_map(
            hdf_path=hdf_path,
            station_map=station_map_df,
            out_csv=artifact_dir / "hdf_profiles.csv",
        )
        if result_info.get("log_path"):
            log_issues = parse_ras_log(Path(result_info["log_path"]))
        analysis_notes["artifacts"] = {
            "hdf_path": str(hdf_path),
            "plan_path": result_info.get("plan_path", ""),
            "log_path": result_info.get("log_path", ""),
            "result_project_dir": str(result_project_dir),
        }

    sections_csv = geometry_outputs["sections_csv"]
    profile_csv = project_out / "artifacts" / "hdf_profiles.csv"
    signal_csv = project_out / "artifacts" / "hdf_hydraulic_signals.csv"
    all_sections_csv = extract_all_sections(
        cross_sections_csv=sections_csv,
        run_id=project_id,
        profile_values_csv=profile_csv if profile_csv.exists() else None,
        signal_summary_csv=signal_csv if signal_csv.exists() else None,
        output_root=output_root,
    )

    build_longitudinal_profile(all_sections_csv, run_id=project_id, output_root=output_root)

    floodline_path = None
    if _geometry_has_cutlines(geometry_summary):
        try:
            floodline_path = export_energy_floodline(
                sections_csv=all_sections_csv,
                run_id=project_id,
                target_epsg=3857,
                profile_values_csv=profile_csv if profile_csv.exists() else None,
                output_root=output_root,
                sections_json=geometry_outputs["sections_json"],
                allow_scalar_fallback=False,
            )
            if floodline_path.exists() and floodline_path.stat().st_size > 0:
                export_floodline_dxf(floodline_path, run_id=project_id, output_root=output_root)
        except Exception as exc:
            analysis_notes["messages"].append(f"Floodline export unavailable: {exc}")
            floodline_path = None
    else:
        analysis_notes["messages"].append(
            "Floodline and CAD outputs were skipped because the geometry file does not contain map-space cut lines."
        )

    confluence_chainage = _infer_confluence_chainage(project_meta, station_map_df)
    metrics_csv = compute_metrics(
        sections_csv=all_sections_csv,
        run_id=project_id,
        floodline_geojson=floodline_path,
        output_root=output_root,
        confluence_chainage_m=confluence_chainage,
    )

    qa_dir = project_out / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa_issues = run_hydraulic_qa(metrics_csv, log_issues=log_issues, thresholds=thresholds)
    (qa_dir / "hydraulic_qa.md").write_text(_issues_to_markdown("Hydraulic QA", qa_issues), encoding="utf-8")
    (qa_dir / "project_analysis.md").write_text(_analysis_notes_markdown(analysis_notes), encoding="utf-8")

    source_snapshot_after = snapshot_project_tree(project_dir)
    _write_json(inventory_dir / "source_snapshot_after.json", source_snapshot_after)
    analysis_notes["source_folder_unchanged"] = (
        source_snapshot_after.get("tree_sha256") == project_meta.get("source_snapshot", {}).get("tree_sha256")
    )
    _write_json(inventory_dir / "analysis_notes.json", analysis_notes)

    draft_report = build_project_audit_report(
        project_id=project_id,
        output_root=project_out,
        project_meta=project_meta,
        compute_mode=str(analysis_notes.get("compute_mode", "unknown")),
    )
    ai_context = build_project_ai_context(
        project_meta=project_meta,
        output_root=project_out,
        draft_report_path=draft_report,
        compute_mode=str(analysis_notes.get("compute_mode", "unknown")),
    )
    ai_artifacts = build_ai_word_report_from_context(
        report_id=project_id,
        context=ai_context,
        ai_config=ai_config,
        output_root=project_out,
        require_ai=True,
    )

    return {
        "project_name": project_dir.name,
        "project_id": project_id,
        "project_dir": str(project_dir),
        "status": "completed",
        "compute_mode": analysis_notes.get("compute_mode", "unknown"),
        "source_folder_unchanged": bool(analysis_notes.get("source_folder_unchanged", False)),
        "output_root": str(project_out),
        "reports": ai_artifacts,
        "draft_report": str(draft_report),
        "metrics_csv": str(metrics_csv),
        "sections_csv": str(all_sections_csv),
        "hdf_path": analysis_notes.get("artifacts", {}).get("hdf_path", "") if isinstance(analysis_notes.get("artifacts"), dict) else "",
    }


def _compute_temp_copy(project_meta: dict[str, object], project_id: str) -> tuple[dict[str, str], Path]:
    project_dir = Path(str(project_meta["project_dir"]))
    run_id = f"analyse_{project_id}"
    run_project_dir = clone_shell_project(
        shell_dir=project_dir,
        run_id=run_id,
        preserve_project_files=True,
    )
    flow_json = build_flow_payload_from_summary(project_meta, Path("runs") / run_id / "flow" / "steady_flow.json")

    geometry_summary = project_meta.get("geometry_summary", {}) if isinstance(project_meta.get("geometry_summary", {}), dict) else {}
    river_name = str(geometry_summary.get("river_name", "") or "Unknown River")
    reach_name = str(geometry_summary.get("reach_name", "") or "Unknown Reach")
    adapter = HECRASControllerAdapter()
    adapter.run_compute(
        run_project_dir=run_project_dir,
        sdf_path=run_project_dir / "import" / "noop.sdf",
        flow_json=flow_json,
        river_name=river_name,
        reach_name=reach_name,
        strict=False,
        auto_close_instances=False,
        apply_flow_via_com=False,
        prefer_cli=True,
        allow_com_fallback=False,
    )
    return locate_project_results(run_project_dir, label=project_id), run_project_dir


def _geometry_has_cutlines(geometry_summary: dict[str, object]) -> bool:
    sections = geometry_summary.get("sections", [])
    if not isinstance(sections, list):
        return False
    return any(getattr(sec, "cutline", None) for sec in sections)


def _infer_confluence_chainage(project_meta: dict[str, object], station_map: pd.DataFrame) -> float | None:
    flow_summary = project_meta.get("flow_summary", {})
    if not isinstance(flow_summary, dict):
        return None
    flow_locations = flow_summary.get("flow_locations", [])
    if not isinstance(flow_locations, list) or len(flow_locations) < 2 or station_map.empty:
        return None
    target_station = float(flow_locations[1].get("river_station", math.nan))
    if math.isnan(target_station):
        return None
    ref = station_map.copy()
    ref["err"] = (ref["river_station"] - target_station).abs()
    row = ref.sort_values("err").iloc[0]
    return float(row["chainage_m"])


def _write_batch_outputs(output_root: Path, rows: list[dict[str, object]]) -> Path:
    manifest = {
        "project_count": len(rows),
        "completed_count": sum(1 for row in rows if row.get("status") == "completed"),
        "failed_count": sum(1 for row in rows if row.get("status") != "completed"),
        "projects": rows,
    }
    manifest_path = output_root / "batch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    index_lines = [
        "# Batch Analysis Index",
        "",
        f"- Projects processed: {manifest['project_count']}",
        f"- Completed: {manifest['completed_count']}",
        f"- Failed: {manifest['failed_count']}",
        "",
        "| Project | Status | Compute Mode | Report |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        report = ""
        reports = row.get("reports")
        if isinstance(reports, dict):
            report = str(reports.get("docx", ""))
        index_lines.append(
            f"| {row.get('project_name', '')} | {row.get('status', '')} | {row.get('compute_mode', '')} | {report} |"
        )
    (output_root / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return manifest_path


def _analysis_notes_markdown(notes: dict[str, object]) -> str:
    lines = ["# Project Analysis Notes", ""]
    lines.append(f"- Compute mode: `{notes.get('compute_mode', '')}`")
    lines.append(f"- Source folder unchanged: `{notes.get('source_folder_unchanged', False)}`")
    lines.append("")
    for msg in notes.get("messages", []):
        lines.append(f"- {msg}")
    return "\n".join(lines) + "\n"


def _issues_to_markdown(title: str, issues: list[object]) -> str:
    lines = [f"# {title}", ""]
    if not issues:
        lines.append("_No issues detected._")
        lines.append("")
        return "\n".join(lines)
    for issue in issues:
        severity = getattr(issue, "severity", "info")
        message = getattr(issue, "message", str(issue))
        lines.append(f"- [{severity}] {message}")
    lines.append("")
    return "\n".join(lines)


def _safe_jsonable_geometry_summary(geometry_summary: dict[str, object]) -> dict[str, object]:
    if not isinstance(geometry_summary, dict):
        return {}
    out = dict(geometry_summary)
    sections = out.get("sections", [])
    if isinstance(sections, list):
        out["sections"] = [
            {
                "chainage_m": float(sec.chainage_m),
                "river_station": float(sec.river_station),
                "river_name": sec.river_name,
                "reach_name": sec.reach_name,
                "left_bank_station": float(sec.left_bank_station),
                "right_bank_station": float(sec.right_bank_station),
                "point_count": len(sec.points),
            }
            for sec in sections
        ]
    return out


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned or "project"
