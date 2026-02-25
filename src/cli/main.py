from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from src.common.config import (
    load_project_config,
    load_scenario_spec,
    load_sheets_config,
    load_threshold_config,
)
from src.common.logging import configure_logging
from src.common.paths import ensure_repo_paths
from src.intake.excel_parser import parse_excel_inputs
from src.intake.kmz_parser import parse_kmz_map, write_reference_points
from src.intake.manifest_builder import build_manifest
from src.intake.prj_parser import validate_target_crs
from src.intake.shapefile_parser import parse_centerline_shapefile
from src.post.extract_sections import extract_required_sections
from src.post.floodline_mapper import export_energy_floodline
from src.post.long_profile import build_longitudinal_profile
from src.post.metrics import compute_metrics
from src.qa.geometry_qa import run_geometry_qa
from src.qa.hydraulic_qa import run_hydraulic_qa
from src.qa.regime_recommender import write_regime_recommendation
from src.ras.flow_writer import write_steady_flow_payload
from src.ras.hdf_reader import discover_hdf_paths, extract_numeric_datasets
from src.ras.manual_steps import write_manual_compute_steps
from src.ras.ras_log_parser import parse_ras_log
from src.ras.ras_shell import clone_shell_project, stage_import_file
from src.ras.result_locator import locate_run_results
from src.ras.sdf_writer import write_rasimport_sdf
from src.reporting.report_builder import build_report
from src.scenarios.scenario_compare import compare_runs
from src.scenarios.scenario_loader import load_scenario
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
) -> None:
    """Build cross-section package, assign roughness/reach lengths, and run geometry QA."""
    configure_logging()
    cfg = load_project_config(config)
    xs_source = Path("data/processed/xs_chainage_0_completed.csv")
    if not xs_source.exists():
        xs_source = Path("data/processed/cross_sections_raw.csv")

    sections_json = build_cross_sections(
        centerline_geojson=Path("data/processed/centerline_from_shp.geojson"),
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

    qa_issues = run_geometry_qa(sections_json, Path("data/processed/centerline_from_shp.geojson"))
    qa_dir = Path("outputs") / run_id / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa_path = qa_dir / "geometry_qa.md"
    qa_path.write_text(_issues_to_markdown("Geometry QA", qa_issues), encoding="utf-8")
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
    flow_json, _ = write_steady_flow_payload(cfg.hydraulics, run_id=run_id)
    manual_path = write_manual_compute_steps(run_project_dir)
    typer.echo(f"Run prepared: {run_id}")
    typer.echo(f"SDF staged: {staged}")
    typer.echo(f"Flow payload: {flow_json}")
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
    typer.echo(f"Result artifacts imported: {artifact_path}")
    typer.echo(f"HDF summary: {summary_csv}")


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

    section_csv = extract_required_sections(xs_csv, run_id=run_id)
    profile_png = build_longitudinal_profile(section_csv, run_id=run_id)
    metrics_csv = compute_metrics(section_csv, run_id=run_id)
    floodline = export_energy_floodline(
        section_csv,
        run_id=run_id,
        target_epsg=cfg.project.target_crs_epsg,
    )

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
    build_geometry(run_id=run_id, config=config)
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


if __name__ == "__main__":
    app()
