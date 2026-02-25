# HEC-RAS-AUTO

Deterministic, fixture-first automation pipeline for a supervised HEC-RAS 6.6 workflow.

## What This v1 Implements
- Intake validation for KMZ/XLSX/SHP/PRJ/GeoTIFF.
- Chainage 0 cross-section completion from terrain sampling.
- Geometry packaging and `RASImport.sdf` generation.
- Baseline + Scenario 2 (climate intensification) run preparation.
- Post-run discovery, analytics, QA reports, and draft Markdown report.
- Manual compute gate inside HEC-RAS UI.

## Quick Start
```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -e .[dev]
ras-auto init
ras-auto ingest --config config/project.yml
ras-auto complete-xs --chainage 0 --run-id baseline
ras-auto build-geometry --run-id baseline
ras-auto prepare-run --run-id baseline
```

Then perform the manual HEC-RAS compute gate using instructions in:
`runs/baseline/ras_project/MANUAL_COMPUTE_STEPS.txt`

Resume:
```powershell
ras-auto import-results --run-id baseline
ras-auto analyze --run-id baseline
ras-auto apply-scenario --scenario config/scenarios/scenario_2_climate.yml --run-id scenario_2
ras-auto prepare-run --run-id scenario_2
```

Repeat manual compute gate for scenario 2, then:
```powershell
ras-auto import-results --run-id scenario_2
ras-auto analyze --run-id scenario_2
ras-auto compare --base baseline --other scenario_2
ras-auto build-report --run-id baseline
ras-auto build-report --run-id scenario_2
```

## Notes
- Real project files can be added later under `data/raw/`.
- Fixtures are used to develop the pipeline contract before full data arrives.
- CAD UI automation is out of scope in v1 by design.
