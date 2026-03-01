from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import typer

from src.common.config import (
    load_ai_config,
    load_agent_config,
    load_automation_config,
    load_project_config,
    load_retrieval_config,
    load_sheets_config,
    load_threshold_config,
)
from src.common.doctor import run_doctor_checks, summarize_doctor
from src.common.logging import configure_logging
from src.common.paths import ensure_repo_paths
from src.agent.orchestrator import AutopilotOrchestrator, OpenAIAdvisor
from src.agent.citation_scorer import filter_citations, score_citations
from src.agent.prompt_compiler import PromptCompiler
from src.agent.retrieval import WebCitationRetriever
from src.agent.task_engine import TaskEngine
from src.intake.dxf_centerline_parser import parse_centerline_dxf
from src.intake.excel_parser import parse_excel_inputs
from src.intake.kmz_parser import parse_kmz_map, write_reference_points
from src.intake.manifest_builder import build_manifest
from src.intake.prj_parser import validate_target_crs
from src.intake.shapefile_parser import parse_centerline_shapefile
from src.intake.source_sync import stage_inputs_from_source
from src.post.extract_sections import extract_required_sections
from src.post.floodline_mapper import export_energy_floodline
from src.post.long_profile import build_longitudinal_profile
from src.post.metrics import compute_metrics
from src.qa.geometry_qa import run_geometry_qa
from src.qa.hydraulic_qa import run_hydraulic_qa
from src.qa.regime_recommender import write_regime_recommendation
from src.ras.flow_writer import write_steady_flow_payload
from src.ras.file_model_writer import stage_text_model_files
from src.ras.hdf_reader import (
    discover_hdf_paths,
    extract_hydraulic_signals,
    extract_numeric_datasets,
    extract_profile_values,
)
from src.ras.manual_steps import write_manual_compute_steps
from src.ras.ras_log_parser import parse_ras_log
from src.ras.controller_adapter import HECControllerError, HECRASControllerAdapter
from src.ras.ras_shell import clone_shell_project, stage_import_file
from src.ras.result_seed import seed_result_artifacts
from src.ras.result_locator import locate_run_results
from src.ras.sdf_writer import write_rasimport_sdf
from src.post.cad_export import export_floodline_dxf
from src.reporting.report_builder import build_report
from src.reporting.submission_pack import build_submission_pack
from src.scenarios.scenario_compare import compare_runs
from src.scenarios.scenario_loader import load_scenario
from src.scenarios.scenario_registry import build_scenario_spec
from src.xs.reach_lengths import assign_reach_lengths, write_reach_lengths
from src.xs.roughness import apply_baseline_roughness
from src.xs.xs_builder import build_cross_sections
from src.xs.xs_complete_gap import complete_chainage_zero_section

app = typer.Typer(help="HEC-RAS-AUTO CLI")
logger = logging.getLogger(__name__)


@app.command()
def init() -> None:
    """Initialize required repo directories and fixture placeholders."""
    configure_logging()
    ensure_repo_paths()
    fixture_dir = Path("data/fixtures")
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "README.txt").write_text(
        "Place synthetic fixture files here for parser and integration tests.\n",
        encoding="utf-8",
    )
    typer.echo("Initialized repository scaffold and fixture directory.")


@app.command()
def ingest(config: Path = typer.Option(Path("config/project.yml")), sheets: Path = typer.Option(Path("config/sheets.yml"))) -> None:
    """Validate inputs and build processed intake artifacts."""
    configure_logging()
    cfg = load_project_config(config)
    sheets_cfg = load_sheets_config(sheets)
    manifest = build_manifest(cfg)
    validate_target_crs(cfg.files.projection_prj, cfg.project.target_crs_epsg)
    points = parse_kmz_map(
        {
            "station_0": cfg.kmz_points.station_0,
            "chainage0_right_bank_floodplain": cfg.kmz_points.chainage0_right_bank_floodplain,
            "chainage0_right_bank_top": cfg.kmz_points.chainage0_right_bank_top,
        },
        cfg.project.target_crs_epsg,
    )
    write_reference_points(points)
    parse_excel_inputs(cfg.files.info_xlsx, sheets_cfg)
    _write_centerline_geojson_from_excel(
        csv_path=Path("data/processed/centerline_from_excel.csv"),
        out_path=Path("data/processed/centerline_from_excel.geojson"),
        terrain_tif=cfg.files.terrain_tif,
        debug_out=Path("data/processed/centerline_transform_debug.json"),
    )
    dxf_path = _infer_dxf_from_dwg(cfg.files.contour_dwg)
    if dxf_path is not None and dxf_path.exists():
        try:
            parse_centerline_dxf(
                dxf_path=dxf_path,
                out_dir=Path("data/processed"),
                excel_centerline_csv=Path("data/processed/centerline_from_excel.csv"),
            )
        except Exception as exc:
            logger.warning("DXF centerline extraction failed (%s); continuing with Excel/Shapefile centerlines.", exc)
    parse_centerline_shapefile(cfg.files.centerline_shp, cfg.project.target_crs_epsg)
    typer.echo(f"Ingest complete. Manifest: data/processed/project_manifest.json ({len(manifest.files)} files)")


@app.command("complete-xs")
def complete_xs(
    chainage: float = typer.Option(0.0),
    run_id: str = typer.Option("baseline"),
    config: Path = typer.Option(Path("config/project.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
) -> None:
    """Complete chainage 0 cross section using terrain profile between KMZ points."""
    if chainage != 0:
        raise typer.BadParameter("v1 currently supports chainage=0 only.")
    configure_logging()
    cfg = load_project_config(config)
    th = load_threshold_config(thresholds)
    out_csv = complete_chainage_zero_section(
        terrain_tif=cfg.files.terrain_tif,
        thresholds=th,
        run_output_dir=Path("outputs") / run_id,
    )
    typer.echo(f"Completed chainage 0 section: {out_csv}")


@app.command("build-geometry")
def build_geometry(
    run_id: str = typer.Option("baseline"),
    config: Path = typer.Option(Path("config/project.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
) -> None:
    """Build cross-section package, assign roughness/reach lengths, and run geometry QA."""
    configure_logging()
    cfg = load_project_config(config)
    th = load_threshold_config(thresholds)
    xs_source = _prepare_xs_geometry_input()

    sections_json = build_cross_sections(
        centerline_geojson=_resolve_centerline_geojson(),
        xs_csv=xs_source,
        river_name=cfg.project.river_name,
        reach_name=cfg.project.reach_name,
        n_channel=cfg.hydraulics.mannings_channel,
        n_floodplain=cfg.hydraulics.mannings_floodplain,
    )

    # Enrich section objects with roughness and reach lengths.
    sections = _read_sections_json(sections_json)
    sections = apply_baseline_roughness(
        sections,
        n_channel=cfg.hydraulics.mannings_channel,
        n_floodplain=cfg.hydraulics.mannings_floodplain,
    )
    sections = assign_reach_lengths(sections)
    _write_sections_json(sections, sections_json)
    write_reach_lengths(sections)

    qa_issues = run_geometry_qa(
        sections_json,
        _resolve_centerline_geojson(),
        min_sections=th.qa.min_cross_sections,
    )
    qa_dir = Path("outputs") / run_id / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa_path = qa_dir / "geometry_qa.md"
    qa_path.write_text(_issues_to_markdown("Geometry QA", qa_issues), encoding="utf-8")
    if any(issue.severity == "error" for issue in qa_issues):
        raise RuntimeError(f"Geometry QA failed. Inspect report: {qa_path}")
    typer.echo(f"Geometry build complete. QA report: {qa_path}")


@app.command("prepare-run")
def prepare_run(
    run_id: str = typer.Option("baseline"),
    config: Path = typer.Option(Path("config/project.yml")),
) -> None:
    """Clone shell project, stage SDF import, and write flow payload + manual steps."""
    configure_logging()
    cfg = load_project_config(config)
    sections_json = Path("data/processed/cross_sections_final.json")
    if not sections_json.exists():
        raise FileNotFoundError("Missing geometry package: data/processed/cross_sections_final.json")

    run_project_dir = clone_shell_project(cfg.hec_ras.shell_project_dir, run_id)
    sdf_out = Path("runs") / run_id / "RASImport.sdf"
    write_rasimport_sdf(
        sections_json=sections_json,
        out_path=sdf_out,
        river_name=cfg.project.river_name,
        reach_name=cfg.project.reach_name,
    )
    staged = stage_import_file(run_project_dir, sdf_out, cfg.hec_ras.geometry_import_name)
    flow_json = Path("runs") / run_id / "flow" / "steady_flow.json"
    if not flow_json.exists():
        flow_json, _ = write_steady_flow_payload(cfg.hydraulics, run_id=run_id)
    staged_text = stage_text_model_files(
        run_project_dir=run_project_dir,
        sections_json=sections_json,
        centerline_geojson=_resolve_centerline_geojson(),
        flow_json=flow_json,
        river_name=cfg.project.river_name,
        reach_name=cfg.project.reach_name,
    )
    manual_path = write_manual_compute_steps(run_project_dir)
    typer.echo(f"Run prepared: {run_id}")
    typer.echo(f"SDF staged: {staged}")
    typer.echo(f"Flow payload: {flow_json}")
    typer.echo(f"Text model staged: {staged_text['geometry_file']}, {staged_text['flow_file']}")
    typer.echo(f"Manual steps: {manual_path}")


@app.command("import-results")
def import_results(run_id: str = typer.Option("baseline")) -> None:
    """Locate run artifacts and summarize HDF datasets."""
    configure_logging()
    result = locate_run_results(run_id)
    out_dir = Path("outputs") / run_id / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / "run_artifacts.json"
    artifact_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    hdf_path = Path(result["hdf_path"])
    hdf_keys_path = out_dir / "hdf_keys.json"
    hdf_keys_path.write_text(json.dumps(discover_hdf_paths(hdf_path), indent=2), encoding="utf-8")
    summary_csv = extract_numeric_datasets(hdf_path, out_dir / "hdf_numeric_summary.csv")
    signals_csv = extract_hydraulic_signals(hdf_path, out_dir / "hdf_hydraulic_signals.csv")
    profile_csv = extract_profile_values(
        hdf_path=hdf_path,
        station_map_csv=Path("data/processed/cross_sections_final.csv"),
        out_csv=out_dir / "hdf_profiles.csv",
    )
    typer.echo(f"Result artifacts imported: {artifact_path}")
    typer.echo(f"HDF summary: {summary_csv}")
    typer.echo(f"Hydraulic signal summary: {signals_csv}")
    typer.echo(f"Hydraulic profiles: {profile_csv}")


@app.command()
def analyze(
    run_id: str = typer.Option("baseline"),
    config: Path = typer.Option(Path("config/project.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
) -> None:
    """Generate sections, profile, metrics, floodline, and hydraulic QA outputs."""
    configure_logging()
    cfg = load_project_config(config)
    th = load_threshold_config(thresholds)
    xs_csv = Path("data/processed/cross_sections_final.csv")
    if not xs_csv.exists():
        raise FileNotFoundError("Missing cross_sections_final.csv. Run build-geometry first.")

    signal_csv = Path("outputs") / run_id / "artifacts" / "hdf_hydraulic_signals.csv"
    profile_csv = Path("outputs") / run_id / "artifacts" / "hdf_profiles.csv"
    section_csv = extract_required_sections(
        xs_csv,
        run_id=run_id,
        profile_values_csv=profile_csv,
        signal_summary_csv=signal_csv,
    )
    profile_png = build_longitudinal_profile(section_csv, run_id=run_id)
    metrics_csv = compute_metrics(section_csv, run_id=run_id)
    floodline = export_energy_floodline(
        section_csv,
        run_id=run_id,
        target_epsg=cfg.project.target_crs_epsg,
    )
    dxf = export_floodline_dxf(floodline, run_id=run_id)

    artifact_json = Path("outputs") / run_id / "artifacts" / "run_artifacts.json"
    log_issues = []
    if artifact_json.exists():
        artifact = json.loads(artifact_json.read_text(encoding="utf-8"))
        log_path = artifact.get("log_path", "")
        if log_path:
            log_issues = parse_ras_log(Path(log_path))
    qa_issues = run_hydraulic_qa(metrics_csv, log_issues=log_issues, thresholds=th)
    qa_dir = Path("outputs") / run_id / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    hyd_path = qa_dir / "hydraulic_qa.md"
    hyd_path.write_text(_issues_to_markdown("Hydraulic QA", qa_issues), encoding="utf-8")
    regime_path = write_regime_recommendation(metrics_csv, qa_dir / "flow_regime_recommendation.md")
    typer.echo(f"Analysis complete. Profile: {profile_png}")
    typer.echo(f"Metrics: {metrics_csv}")
    typer.echo(f"Floodline: {floodline}")
    typer.echo(f"CAD DXF: {dxf}")
    typer.echo(f"Hydraulic QA: {hyd_path}")
    typer.echo(f"Regime memo: {regime_path}")


@app.command("apply-scenario")
def apply_scenario(
    scenario: Path = typer.Option(Path("config/scenarios/scenario_2_climate.yml")),
    run_id: str = typer.Option("scenario_2"),
    config: Path = typer.Option(Path("config/project.yml")),
) -> None:
    """Apply scenario flow multipliers and generate scenario flow payload."""
    configure_logging()
    cfg = load_project_config(config)
    spec = load_scenario(scenario)
    flow_json, flow_csv = write_steady_flow_payload(cfg.hydraulics, run_id=run_id, scenario=spec)
    typer.echo(f"Scenario payload written: {flow_json}")
    typer.echo(f"Scenario table: {flow_csv}")


@app.command()
def compare(base: str = typer.Option("baseline"), other: str = typer.Option("scenario_2")) -> None:
    """Compare baseline and scenario metrics and profiles."""
    configure_logging()
    table_path, profile_path = compare_runs(base, other)
    typer.echo(f"Comparison table: {table_path}")
    typer.echo(f"Overlay profile: {profile_path}")


@app.command("build-report")
def build_report_cmd(run_id: str = typer.Option("baseline")) -> None:
    """Render markdown report draft for a run."""
    configure_logging()
    path = build_report(run_id)
    typer.echo(f"Report draft: {path}")


@app.command()
def doctor(
    config: Path = typer.Option(Path("config/project.yml")),
    out: Path = typer.Option(Path("outputs/doctor_report.md")),
) -> None:
    """Run environment and dependency preflight checks."""
    configure_logging()
    cfg = load_project_config(config)
    checks = run_doctor_checks(cfg)
    report = summarize_doctor(checks)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    typer.echo(f"Doctor report: {out}")
    typer.echo(report)


@app.command("run-hecras")
def run_hecras(
    run_id: str = typer.Option("baseline"),
    config: Path = typer.Option(Path("config/project.yml")),
    strict: bool = typer.Option(True, help="Fail immediately on COM setup/compute issues."),
    auto_close_instances: bool = typer.Option(
        True,
        help="Auto-close running Ras.exe processes before COM automation.",
    ),
) -> None:
    """Run HEC-RAS compute headlessly (CLI-only for v2 reliability)."""
    configure_logging()
    cfg = load_project_config(config)
    run_project_dir = Path("runs") / run_id / "ras_project"
    sdf_path = run_project_dir / "import" / cfg.hec_ras.geometry_import_name
    flow_json = Path("runs") / run_id / "flow" / "steady_flow.json"
    adapter = HECRASControllerAdapter()
    try:
        result = adapter.run_compute(
            run_project_dir=run_project_dir,
            sdf_path=sdf_path,
            flow_json=flow_json,
            river_name=cfg.project.river_name,
            reach_name=cfg.project.reach_name,
            strict=strict,
            auto_close_instances=auto_close_instances,
            ras_exe_path=cfg.hec_ras.ras_exe_path,
            prefer_cli=True,
            allow_com_fallback=False,
        )
    except HECControllerError as exc:
        raise RuntimeError(f"run-hecras failed: {exc}") from exc

    # Optional fallback seeding is now opt-in only; default behavior is to
    # surface native compute failures directly.
    allow_seed = str(os.getenv("RAS_AUTO_ALLOW_SEEDED_RESULTS", "")).strip() in {"1", "true", "TRUE"}
    if allow_seed and (
        not strict
        and (not bool(result.get("success", False)))
        and not result.get("hdf_files")
        and not result.get("output_files")
    ):
        seeded = seed_result_artifacts(run_id)
        if seeded:
            msgs = result.get("messages", [])
            if isinstance(msgs, list):
                msgs.append(
                    "Compute produced no native artifacts; seeded outputs from prior successful run "
                    "because RAS_AUTO_ALLOW_SEEDED_RESULTS is enabled."
                )
                result["messages"] = msgs
            result["seeded_from"] = seeded
            result["success"] = True

    out_dir = Path("outputs") / run_id / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    com_json = out_dir / "com_run_summary.json"
    com_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    typer.echo(f"HEC-RAS COM run summary: {com_json}")


@app.command()
def autopilot(
    source: str = typer.Option("ref"),
    run_id: str = typer.Option("baseline"),
    scenario2: bool = typer.Option(True),
    sweep: str = typer.Option("", help="Comma-separated multipliers, e.g. 1.10,1.15,1.20"),
    strict: bool = typer.Option(True),
    config: Path = typer.Option(Path("config/project.yml")),
    sheets: Path = typer.Option(Path("config/sheets.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
    automation: Path = typer.Option(Path("config/automation.yml")),
    ai: Path = typer.Option(Path("config/ai.yml")),
) -> None:
    """Unattended end-to-end run with guardrails."""
    configure_logging()
    source_path = Path(source)
    policy = load_automation_config(automation).autopilot
    ai_cfg = load_ai_config(ai).ai
    advisor = OpenAIAdvisor(ai_cfg)
    orch = AutopilotOrchestrator(run_id=run_id)

    def step_stage_source():
        cfg = load_project_config(config)
        report = stage_inputs_from_source(cfg, source_path, overwrite=True, purge_missing=True)
        path = Path("outputs") / run_id / "autopilot" / "source_sync.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        orch.set_artifact("source_sync", path)
        if report["missing"]:
            if policy.require_source_files:
                raise RuntimeError(
                    "Source sync missing required files: "
                    + ", ".join(report["missing"])
                    + ". Provide a complete source folder for this project."
                )
            logger.warning("Source sync missing files: %s", report["missing"])
        return report

    def step_doctor():
        cfg = load_project_config(config)
        checks = run_doctor_checks(cfg)
        report = summarize_doctor(checks)
        report_path = Path("outputs") / run_id / "autopilot" / "doctor_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        if not checks.get("python_ok", False):
            raise RuntimeError("Python 3.11+ required.")
        orch.set_artifact("doctor_report", report_path)
        return checks

    def step_ingest():
        ingest(config=config, sheets=sheets)
        return "ok"

    def step_complete_xs():
        complete_xs(chainage=0.0, run_id=run_id, config=config, thresholds=thresholds)
        return "ok"

    def step_build_geometry():
        build_geometry(run_id=run_id, config=config, thresholds=thresholds)
        return "ok"

    def step_prepare():
        prepare_run(run_id=run_id, config=config)
        return "ok"

    def step_compute():
        run_hecras(
            run_id=run_id,
            config=config,
            strict=strict,
            auto_close_instances=True,
        )
        return "ok"

    def step_import():
        import_results(run_id=run_id)
        return "ok"

    def step_analyze():
        analyze(run_id=run_id, config=config, thresholds=thresholds)
        _enforce_real_hydraulics(run_id=run_id, strict=strict)
        return "ok"

    def step_report():
        build_report_cmd(run_id=run_id)
        return "ok"

    try:
        orch.step("stage_source", step_stage_source)
        orch.step("init", lambda: init())
        orch.step("doctor", step_doctor)
        orch.step("ingest", step_ingest)
        orch.step("complete_xs", step_complete_xs)
        orch.step("build_geometry", step_build_geometry)
        orch.step("prepare_run", step_prepare)
        orch.step("run_hecras", step_compute)
        orch.step("import_results", step_import)
        orch.step("analyze", step_analyze)
        orch.step("build_report", step_report)

        if scenario2 and policy.scenario2.enabled:
            scenario_path = Path("config/scenarios/scenario_2_climate.yml")
            sweep_vals = []
            if sweep.strip():
                sweep_vals = [float(x.strip()) for x in sweep.split(",") if x.strip()]
            elif policy.scenario2.sweep_enabled:
                sweep_vals = [float(x) for x in policy.scenario2.sweep_values]
            if sweep_vals:
                sweep_ids: list[str] = []
                for idx, mult in enumerate(sweep_vals, start=1):
                    sid = f"{run_id}_scenario_2_{idx}"
                    sweep_ids.append(sid)
                    apply_scenario_with_multiplier(
                        run_id=sid,
                        scenario_path=scenario_path,
                        config_path=config,
                        multiplier=mult,
                    )
                    prepare_run(run_id=sid, config=config)
                    run_hecras(
                        run_id=sid,
                        config=config,
                        strict=strict,
                        auto_close_instances=not strict,
                    )
                    import_results(run_id=sid)
                    analyze(run_id=sid, config=config, thresholds=thresholds)
                    _enforce_real_hydraulics(run_id=sid, strict=strict)
                compare(base=run_id, other=f"{run_id}_scenario_2_{len(sweep_vals)}")
                _write_sweep_envelope(base_run=run_id, scenario_runs=sweep_ids)
            else:
                sid = f"{run_id}_scenario_2"
                apply_scenario_with_multiplier(
                    run_id=sid,
                    scenario_path=scenario_path,
                    config_path=config,
                    multiplier=float(policy.scenario2.fixed_multiplier),
                )
                prepare_run(run_id=sid, config=config)
                run_hecras(
                    run_id=sid,
                    config=config,
                    strict=strict,
                    auto_close_instances=not strict,
                )
                import_results(run_id=sid)
                analyze(run_id=sid, config=config, thresholds=thresholds)
                _enforce_real_hydraulics(run_id=sid, strict=strict)
                compare(base=run_id, other=sid)
                build_report_cmd(run_id=sid)

        # Add optional AI triage summary note.
        triage = advisor.anomaly_triage("Autopilot completed. Summarize residual risks.")
        triage_path = Path("outputs") / run_id / "autopilot" / "ai_triage.txt"
        triage_path.parent.mkdir(parents=True, exist_ok=True)
        triage_path.write_text(triage, encoding="utf-8")
        orch.log_action(
            f"ai_call type={advisor.last_prompt_type} response_id={advisor.last_response_id or 'n/a'}"
        )
        orch.set_artifact("ai_triage", triage_path)
        orch.complete()
        typer.echo(f"Autopilot completed for run: {run_id}")
    except Exception as exc:
        triage = advisor.anomaly_triage(f"Autopilot failure: {exc}")
        triage_path = Path("outputs") / run_id / "autopilot" / "ai_triage.txt"
        triage_path.parent.mkdir(parents=True, exist_ok=True)
        triage_path.write_text(triage, encoding="utf-8")
        orch.log_action(
            f"ai_call type={advisor.last_prompt_type} response_id={advisor.last_response_id or 'n/a'}"
        )
        orch.set_artifact("ai_triage", triage_path)
        raise


@app.command("agent-plan")
def agent_plan(
    prompt: str = typer.Option(..., help="Free-text assignment prompt."),
    source: str = typer.Option("ref"),
    out: Path = typer.Option(Path("outputs/baseline/agent/compiled_plan.json")),
    run_id: str = typer.Option("baseline"),
    assigned_scenario: str = typer.Option("scenario_2"),
    ai: Path = typer.Option(Path("config/ai.yml")),
    agent_config: Path = typer.Option(Path("config/agent.yml")),
) -> None:
    """Compile free-text prompt into a strict execution plan."""
    configure_logging()
    ai_cfg = load_ai_config(ai).ai
    ag_cfg = load_agent_config(agent_config).agent
    compiler = PromptCompiler(ai_cfg, max_retries=ag_cfg.max_parse_retries)
    spec = compiler.compile_job_spec(
        prompt_text=prompt,
        run_id=run_id,
        source=source,
        assigned_scenario_override=assigned_scenario,
        strict=ag_cfg.strict_mode_default,
    )
    plan = compiler.compile_execution_plan(spec, run_id=run_id)
    spec_path, plan_path = compiler.persist_plan_artifacts(run_id, spec, plan)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Prompt parse: {spec_path}")
    typer.echo(f"Compiled plan: {plan_path}")
    typer.echo(f"Explicit plan output: {out}")


@app.command("agent-run")
def agent_run(
    prompt: str = typer.Option(..., help="Free-text assignment prompt."),
    source: str = typer.Option("ref"),
    run_id: str = typer.Option("baseline"),
    assigned_scenario: str = typer.Option("scenario_2"),
    strict: bool = typer.Option(True),
    config: Path = typer.Option(Path("config/project.yml")),
    sheets: Path = typer.Option(Path("config/sheets.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
    automation: Path = typer.Option(Path("config/automation.yml")),
    ai: Path = typer.Option(Path("config/ai.yml")),
    agent_config: Path = typer.Option(Path("config/agent.yml")),
    retrieval: Path = typer.Option(Path("config/retrieval.yml")),
) -> None:
    """Run prompt-to-project autonomous workflow and emit submission pack."""
    configure_logging()
    ai_cfg = load_ai_config(ai).ai
    ag_cfg = load_agent_config(agent_config).agent
    ret_cfg = load_retrieval_config(retrieval).retrieval
    compiler = PromptCompiler(ai_cfg, max_retries=ag_cfg.max_parse_retries)

    spec = compiler.compile_job_spec(
        prompt_text=prompt,
        run_id=run_id,
        source=source,
        assigned_scenario_override=assigned_scenario,
        strict=strict,
    )
    plan = compiler.compile_execution_plan(spec, run_id=run_id)
    compiler.persist_plan_artifacts(run_id, spec, plan)

    engine = TaskEngine(
        run_id=run_id,
        retry_budget_per_stage=ag_cfg.retry_budget_per_stage,
        enable_self_heal=ag_cfg.enable_self_heal,
    )
    action_registry = _build_agent_action_registry(
        prompt_spec=spec,
        source=source,
        run_id=run_id,
        strict=strict,
        config=config,
        sheets=sheets,
        thresholds=thresholds,
        automation=automation,
        ai_cfg=ai_cfg,
        retrieval_cfg=ret_cfg,
    )

    try:
        state = engine.execute(
            plan=plan,
            action_registry=action_registry,
            retry_playbook=plan.retry_playbook,
            resume=False,
        )
        explain_path = _write_agent_explain(run_id)
        typer.echo(f"Agent run completed. State: outputs/{run_id}/agent/task_state.json")
        typer.echo(f"Explain report: {explain_path}")
        typer.echo(f"Submission manifest: outputs/{run_id}/submission/manifest.json")
        _ = state
    except Exception as exc:
        fail_path = _write_agent_fail_report(run_id, exc)
        raise RuntimeError(f"agent-run failed. See {fail_path}") from exc


@app.command("agent-resume")
def agent_resume(
    run_id: str = typer.Option(..., help="Run id to resume."),
    source: str = typer.Option("ref"),
    strict: bool = typer.Option(True),
    config: Path = typer.Option(Path("config/project.yml")),
    sheets: Path = typer.Option(Path("config/sheets.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
    automation: Path = typer.Option(Path("config/automation.yml")),
    ai: Path = typer.Option(Path("config/ai.yml")),
    agent_config: Path = typer.Option(Path("config/agent.yml")),
    retrieval: Path = typer.Option(Path("config/retrieval.yml")),
) -> None:
    """Resume a previously compiled agent plan from task state."""
    configure_logging()
    plan_path = Path("outputs") / run_id / "agent" / "compiled_plan.json"
    spec_path = Path("outputs") / run_id / "agent" / "prompt_parse.json"
    if not plan_path.exists() or not spec_path.exists():
        raise FileNotFoundError(
            f"Missing compiled plan or prompt parse under outputs/{run_id}/agent."
        )
    from src.models import ExecutionPlan, PromptJobSpec

    plan = ExecutionPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    spec = PromptJobSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))

    ai_cfg = load_ai_config(ai).ai
    ag_cfg = load_agent_config(agent_config).agent
    ret_cfg = load_retrieval_config(retrieval).retrieval
    engine = TaskEngine(
        run_id=run_id,
        retry_budget_per_stage=ag_cfg.retry_budget_per_stage,
        enable_self_heal=ag_cfg.enable_self_heal,
    )
    action_registry = _build_agent_action_registry(
        prompt_spec=spec,
        source=source,
        run_id=run_id,
        strict=strict,
        config=config,
        sheets=sheets,
        thresholds=thresholds,
        automation=automation,
        ai_cfg=ai_cfg,
        retrieval_cfg=ret_cfg,
    )
    try:
        engine.execute(
            plan=plan,
            action_registry=action_registry,
            retry_playbook=plan.retry_playbook,
            resume=True,
        )
        explain_path = _write_agent_explain(run_id)
        typer.echo(f"Agent resume completed: {explain_path}")
    except Exception as exc:
        fail_path = _write_agent_fail_report(run_id, exc)
        raise RuntimeError(f"agent-resume failed. See {fail_path}") from exc


@app.command("agent-explain")
def agent_explain(run_id: str = typer.Option(..., help="Run id to explain.")) -> None:
    """Render human-readable decision trace from task and decision logs."""
    configure_logging()
    out = _write_agent_explain(run_id)
    typer.echo(f"Agent explanation: {out}")


@app.command()
def pipeline(
    run_id: str = typer.Argument("baseline"),
    config: Path = typer.Option(Path("config/project.yml")),
    sheets: Path = typer.Option(Path("config/sheets.yml")),
    thresholds: Path = typer.Option(Path("config/thresholds.yml")),
) -> None:
    """Run all non-manual steps up to HEC-RAS compute gate for a given run."""
    if run_id != "baseline":
        typer.echo(
            "pipeline currently orchestrates baseline pre-compute steps only. "
            "Use apply-scenario/prepare-run for scenario runs.",
        )
    init()
    ingest(config=config, sheets=sheets)
    complete_xs(chainage=0.0, run_id=run_id, config=config, thresholds=thresholds)
    build_geometry(run_id=run_id, config=config, thresholds=thresholds)
    prepare_run(run_id=run_id, config=config)
    typer.echo("Pipeline paused at manual compute gate. Complete HEC-RAS compute, then run import-results/analyze.")


def _read_sections_json(path: Path):
    from src.models import CrossSection

    raw = json.loads(path.read_text(encoding="utf-8"))
    return [CrossSection.model_validate(item) for item in raw]


def _write_sections_json(sections, path: Path) -> None:
    path.write_text(json.dumps([s.model_dump() for s in sections], indent=2), encoding="utf-8")
    flat = []
    for s in sections:
        for p in s.points:
            flat.append(
                {
                    "chainage_m": s.chainage_m,
                    "river_station": s.river_station,
                    "offset_m": p.station,
                    "elevation_m": p.elevation,
                    "left_bank_station": s.left_bank_station,
                    "right_bank_station": s.right_bank_station,
                }
            )
    import pandas as pd

    pd.DataFrame(flat).to_csv(Path("data/processed/cross_sections_final.csv"), index=False)


def _issues_to_markdown(title: str, issues) -> str:
    lines = [f"# {title}", ""]
    for i in issues:
        lines.append(f"- [{i.severity.upper()}] `{i.code}`: {i.message}")
    return "\n".join(lines) + "\n"


def _write_centerline_geojson_from_excel(
    csv_path: Path,
    out_path: Path,
    terrain_tif: Path | None = None,
    debug_out: Path | None = None,
) -> Path:
    import pandas as pd
    import rasterio

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing Excel-derived centerline CSV: {csv_path}")

    df = pd.read_csv(csv_path)
    if "x" not in df.columns or "y" not in df.columns:
        raise ValueError(f"Centerline CSV missing x/y columns: {csv_path}")
    df["x"] = pd.to_numeric(df["x"], errors="coerce")
    df["y"] = pd.to_numeric(df["y"], errors="coerce")
    df = df.dropna(subset=["x", "y"]).reset_index(drop=True)
    if len(df) < 2:
        raise ValueError(f"Centerline CSV has fewer than 2 valid points: {csv_path}")
    if "chainage_m" in df.columns:
        df["chainage_m"] = pd.to_numeric(df["chainage_m"], errors="coerce")
        if df["chainage_m"].notna().any():
            df = df.sort_values("chainage_m").reset_index(drop=True)

    debug_payload: dict[str, object] = {
        "source_csv": str(csv_path),
        "terrain_tif": str(terrain_tif) if terrain_tif else "",
        "transform_applied": False,
    }
    if terrain_tif and terrain_tif.exists():
        with rasterio.open(terrain_tif) as ds:
            bounds = ds.bounds
        tx_min, tx_max = float(bounds.left), float(bounds.right)
        ty_min, ty_max = float(bounds.bottom), float(bounds.top)

        raw_inside = (
            (
                (df["x"] >= tx_min)
                & (df["x"] <= tx_max)
                & (df["y"] >= ty_min)
                & (df["y"] <= ty_max)
            ).sum()
            / max(len(df), 1)
        )

        ex_min, ex_max = float(df["x"].min()), float(df["x"].max())
        ey_min, ey_max = float(df["y"].min()), float(df["y"].max())
        dx = ((tx_min + tx_max) / 2.0) - ((ex_min + ex_max) / 2.0)
        dy = ((ty_min + ty_max) / 2.0) - ((ey_min + ey_max) / 2.0)

        shifted = df.copy()
        shifted["x"] = shifted["x"] + dx
        shifted["y"] = shifted["y"] + dy
        shifted_inside = (
            (
                (shifted["x"] >= tx_min)
                & (shifted["x"] <= tx_max)
                & (shifted["y"] >= ty_min)
                & (shifted["y"] <= ty_max)
            ).sum()
            / max(len(shifted), 1)
        )

        debug_payload.update(
            {
                "terrain_bounds": {"xmin": tx_min, "xmax": tx_max, "ymin": ty_min, "ymax": ty_max},
                "excel_bounds_raw": {"xmin": ex_min, "xmax": ex_max, "ymin": ey_min, "ymax": ey_max},
                "inside_ratio_raw": float(raw_inside),
                "inside_ratio_shifted": float(shifted_inside),
                "centroid_shift_dx": float(dx),
                "centroid_shift_dy": float(dy),
            }
        )

        # If Excel centerline appears in a different local frame, translate it
        # into the terrain frame by centroid shift.
        if raw_inside < 0.5 and shifted_inside >= 0.8 and shifted_inside > raw_inside + 0.2:
            df = shifted
            debug_payload["transform_applied"] = True
            debug_payload["transform_kind"] = "centroid_translation_to_terrain_bounds"
        else:
            debug_payload["transform_kind"] = "none"
    else:
        debug_payload["transform_kind"] = "none_no_terrain"

    coords = [[float(row.x), float(row.y)] for row in df.itertuples(index=False)]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": 1,
                    "source": "excel_centerline",
                    "transform_applied": bool(debug_payload.get("transform_applied", False)),
                    "transform_kind": str(debug_payload.get("transform_kind", "none")),
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if debug_out is not None:
        debug_out.parent.mkdir(parents=True, exist_ok=True)
        debug_out.write_text(json.dumps(debug_payload, indent=2), encoding="utf-8")
    return out_path


def _resolve_centerline_geojson() -> Path:
    dxf_geojson = Path("data/processed/centerline_from_dxf.geojson")
    excel_geojson = Path("data/processed/centerline_from_excel.geojson")
    shp_geojson = Path("data/processed/centerline_from_shp.geojson")
    if dxf_geojson.exists():
        return dxf_geojson
    if excel_geojson.exists():
        return excel_geojson
    if shp_geojson.exists():
        return shp_geojson
    raise FileNotFoundError(
        "No processed centerline GeoJSON found. Expected "
        "data/processed/centerline_from_dxf.geojson, "
        "data/processed/centerline_from_excel.geojson, "
        "or data/processed/centerline_from_shp.geojson."
    )


def _infer_dxf_from_dwg(contour_dwg: Path | None) -> Path | None:
    if contour_dwg is None:
        return None
    try:
        dwg = Path(contour_dwg)
    except Exception:
        return None
    if not dwg.name:
        return None
    dxf = dwg.with_suffix(".dxf")
    return dxf


def _prepare_xs_geometry_input() -> Path:
    import pandas as pd

    raw_path = Path("data/processed/cross_sections_raw.csv")
    completed_path = Path("data/processed/xs_chainage_0_completed.csv")
    merged_path = Path("data/processed/cross_sections_merged.csv")

    if not raw_path.exists():
        raise FileNotFoundError(f"Missing required file: {raw_path}")
    raw = pd.read_csv(raw_path)

    if completed_path.exists():
        completed = pd.read_csv(completed_path)
        merged = pd.concat([raw.loc[raw["chainage_m"] != 0], completed], ignore_index=True)
        merged = merged.sort_values(["chainage_m", "offset_m"]).reset_index(drop=True)
        merged.to_csv(merged_path, index=False)
        return merged_path

    return raw_path


def apply_scenario_with_multiplier(
    run_id: str,
    scenario_path: Path,
    config_path: Path,
    multiplier: float,
) -> None:
    from src.common.config import load_yaml
    import yaml

    cfg = load_project_config(config_path)
    data = load_yaml(scenario_path)
    data["scenario_id"] = run_id
    data["title"] = f"Climate Intensification x{multiplier:.2f}"
    data["flow_multiplier_upstream"] = multiplier
    data["flow_multiplier_tributary"] = multiplier
    tmp = Path("runs") / run_id / "scenario_runtime.yml"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(yaml.safe_dump(data), encoding="utf-8")
    spec = load_scenario(tmp)
    flow_json, flow_csv = write_steady_flow_payload(cfg.hydraulics, run_id=run_id, scenario=spec)
    typer.echo(f"Scenario payload written: {flow_json}")
    typer.echo(f"Scenario table: {flow_csv}")


def _enforce_real_hydraulics(run_id: str, strict: bool) -> None:
    import pandas as pd

    sections_path = Path("outputs") / run_id / "sections" / "required_sections.csv"
    if not sections_path.exists():
        raise RuntimeError(f"Missing required sections output: {sections_path}")

    sections = pd.read_csv(sections_path)
    if sections.empty:
        raise RuntimeError(f"Sections output is empty: {sections_path}")

    if "hydraulic_source" not in sections.columns:
        if strict:
            raise RuntimeError("Hydraulic source provenance missing from required sections.")
        return

    sources = set(sections["hydraulic_source"].dropna().astype(str).unique())
    non_computed = {"fallback", "signal_summary"}
    if strict and sources.intersection(non_computed):
        raise RuntimeError(
            "Strict hydraulic mode requires computed profile data from plan-result HDF; "
            f"found sources: {sorted(sources)}"
        )


def _write_sweep_envelope(base_run: str, scenario_runs: list[str]) -> Path:
    import pandas as pd

    base_path = Path("outputs") / base_run / "tables" / "metrics.csv"
    if not base_path.exists():
        raise FileNotFoundError(f"Missing baseline metrics: {base_path}")
    base_df = pd.read_csv(base_path)
    if base_df.empty:
        raise ValueError("Baseline metrics are empty; cannot build sweep envelope.")
    base = base_df.iloc[0]

    rows = []
    for rid in scenario_runs:
        p = Path("outputs") / rid / "tables" / "metrics.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if df.empty:
            continue
        r = df.iloc[0]
        rows.append(
            {
                "run_id": rid,
                "max_wse_m": float(r["max_wse_m"]),
                "max_velocity_mps": float(r["max_velocity_mps"]),
                "delta_wse_m": float(r["max_wse_m"] - base["max_wse_m"]),
                "delta_velocity_mps": float(r["max_velocity_mps"] - base["max_velocity_mps"]),
            }
        )

    if not rows:
        raise ValueError("No scenario metrics found for sweep envelope.")

    df = pd.DataFrame(rows).sort_values("run_id").reset_index(drop=True)
    envelope = pd.DataFrame(
        [
            {
                "metric": "max_wse_m",
                "baseline": float(base["max_wse_m"]),
                "scenario_min": float(df["max_wse_m"].min()),
                "scenario_max": float(df["max_wse_m"].max()),
                "delta_min": float(df["delta_wse_m"].min()),
                "delta_max": float(df["delta_wse_m"].max()),
            },
            {
                "metric": "max_velocity_mps",
                "baseline": float(base["max_velocity_mps"]),
                "scenario_min": float(df["max_velocity_mps"].min()),
                "scenario_max": float(df["max_velocity_mps"].max()),
                "delta_min": float(df["delta_velocity_mps"].min()),
                "delta_max": float(df["delta_velocity_mps"].max()),
            },
        ]
    )

    out_dir = Path("outputs") / base_run / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / "scenario2_sweep_runs.csv"
    env_path = out_dir / "scenario2_sweep_envelope.csv"
    df.to_csv(detail_path, index=False)
    envelope.to_csv(env_path, index=False)
    return env_path


def _build_agent_action_registry(
    prompt_spec,
    source: str,
    run_id: str,
    strict: bool,
    config: Path,
    sheets: Path,
    thresholds: Path,
    automation: Path,
    ai_cfg,
    retrieval_cfg,
):
    def _scenario_run_id(scenario_id: str) -> str:
        # Namespace scenario runs under the base run id to avoid collisions with
        # previous runs (e.g. a stale global "scenario_2" directory lock).
        return f"{run_id}_{scenario_id}"

    def run_baseline_autopilot(_inputs: dict) -> dict:
        autopilot(
            source=source,
            run_id=run_id,
            scenario2=False,
            sweep="",
            strict=strict,
            config=config,
            sheets=sheets,
            thresholds=thresholds,
            automation=automation,
            ai=Path("config/ai.yml"),
        )
        return {"baseline_run": run_id}

    def prepare_assigned_scenario_payload(inputs: dict) -> dict:
        scenario_id = str(inputs["scenario_id"])
        sid = _scenario_run_id(scenario_id)
        climate_mult = 1.15
        if scenario_id == "scenario_2":
            climate_mult = float(
                prompt_spec.constraints.get(
                    "scenario_2_multiplier",
                    load_automation_config(automation).autopilot.scenario2.fixed_multiplier,
                )
            )
        spec = build_scenario_spec(scenario_id, climate_multiplier=climate_mult)
        cfg = load_project_config(config)
        flow_json, flow_csv = write_steady_flow_payload(cfg.hydraulics, run_id=sid, scenario=spec)
        return {
            "scenario_run": sid,
            "scenario_flow_json": str(flow_json),
            "scenario_flow_csv": str(flow_csv),
        }

    def execute_assigned_scenario(inputs: dict) -> dict:
        scenario_id = str(inputs["scenario_id"])
        sid = _scenario_run_id(scenario_id)
        prepare_run(run_id=sid, config=config)
        run_hecras(run_id=sid, config=config, strict=strict, auto_close_instances=True)
        import_results(run_id=sid)
        analyze(run_id=sid, config=config, thresholds=thresholds)
        _enforce_real_hydraulics(run_id=sid, strict=strict)
        build_report_cmd(run_id=sid)
        return {"scenario_run": sid}

    def compare_baseline_scenario(inputs: dict) -> dict:
        scenario_id = str(inputs["scenario_id"])
        sid = _scenario_run_id(scenario_id)
        table, profile = compare_runs(run_id, sid)
        return {"comparison_table": str(table), "comparison_profile": str(profile)}

    def collect_citations(inputs: dict) -> dict:
        scenario_id = str(inputs["scenario_id"])
        sid = _scenario_run_id(scenario_id)
        objective = str(inputs.get("objective", "Hydraulic interpretation for scenario analysis."))
        retriever = WebCitationRetriever(ai_cfg, retrieval_cfg)
        claims = [
            objective,
            f"Hydraulic mechanism interpretation for {scenario_id} in 1D steady HEC-RAS.",
            f"Design flood change assumptions for {scenario_id}.",
        ]
        citations = retriever.retrieve(claims)
        citations = score_citations(citations, retrieval_cfg)
        citations = filter_citations(citations, retrieval_cfg.citation_confidence_threshold)
        agent_dir = Path("outputs") / run_id / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        path = agent_dir / "citations.json"
        path.write_text(
            json.dumps([c.model_dump(mode="json") for c in citations], indent=2),
            encoding="utf-8",
        )
        # Rebuild reports to inject citation markers.
        build_report_cmd(run_id=run_id)
        build_report_cmd(run_id=sid)
        return {"citations_path": str(path), "count": len(citations)}

    def build_submission(inputs: dict) -> dict:
        scenario_id = str(inputs["scenario_id"])
        sid = _scenario_run_id(scenario_id)
        build_report_cmd(run_id=run_id)
        build_report_cmd(run_id=sid)
        manifest = build_submission_pack(base_run_id=run_id, scenario_run_id=sid)
        return {"submission_manifest": str(manifest)}

    return {
        "run_baseline_autopilot": run_baseline_autopilot,
        "prepare_assigned_scenario_payload": prepare_assigned_scenario_payload,
        "execute_assigned_scenario": execute_assigned_scenario,
        "compare_baseline_scenario": compare_baseline_scenario,
        "collect_citations": collect_citations,
        "build_submission_pack": build_submission,
    }


def _write_agent_fail_report(run_id: str, exc: Exception) -> Path:
    out = Path("outputs") / run_id / "agent" / "fail_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "status": "failed",
        "error": str(exc),
        "remediation": [
            "Review outputs/<run_id>/agent/task_state.json for failed node.",
            "Review outputs/<run_id>/autopilot/fail_report.json if baseline autopilot failed.",
            "Run ras-auto agent-resume --run-id <run_id> after remediation.",
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _write_agent_explain(run_id: str) -> Path:
    agent_dir = Path("outputs") / run_id / "agent"
    explain_path = agent_dir / "explain.md"
    state_path = agent_dir / "task_state.json"
    decisions_path = agent_dir / "decisions.jsonl"
    plan_path = agent_dir / "compiled_plan.json"

    lines = [f"# Agent Explain: {run_id}", ""]
    if plan_path.exists():
        lines.append(f"- Plan: `{plan_path}`")
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        lines.append(f"- Status: `{state.get('status', 'unknown')}`")
        lines.append("")
        lines.append("## Task State")
        for node_id, node in state.get("nodes", {}).items():
            lines.append(
                f"- `{node_id}`: {node.get('status')} (attempt={node.get('attempt', 0)})"
            )
    if decisions_path.exists():
        lines.append("")
        lines.append("## Decision Trace")
        for line in decisions_path.read_text(encoding="utf-8").splitlines()[-20:]:
            try:
                obj = json.loads(line)
                lines.append(
                    f"- `{obj.get('stage')}` `{obj.get('decision_type')}`: {obj.get('rationale')}"
                )
            except Exception:
                continue
    explain_path.parent.mkdir(parents=True, exist_ok=True)
    explain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return explain_path


if __name__ == "__main__":
    app()
