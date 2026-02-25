# HEC-RAS-AUTO

Deterministic, fixture-first automation pipeline for HEC-RAS baseline + Scenario 2 workflows.

## What This Implements
- Intake validation for KMZ/XLSX/SHP/PRJ/GeoTIFF.
- Chainage 0 cross-section completion from terrain sampling.
- Geometry packaging and `RASImport.sdf` generation.
- Baseline + Scenario 2 (climate intensification) run preparation.
- COM-driven unattended HEC-RAS compute (`RAS67`/`RAS66` auto-detect).
- Post-run discovery, analytics, QA reports, CAD DXF export, and draft Markdown report.
- Guardrailed `autopilot` mode with OpenAI-assisted anomaly triage (optional).

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

Then perform the manual HEC-RAS compute gate (optional path) using instructions in:
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

## Unattended v2 Mode
```powershell
setx OPENAI_API_KEY "<your_key>"   # optional, for AI triage text
ras-auto doctor --config config/project.yml
ras-auto autopilot --source ref --run-id baseline --scenario2
```

Additional automation command:
```powershell
ras-auto run-hecras --run-id baseline --strict
```

Optional Scenario 2 sensitivity sweep:
```powershell
ras-auto autopilot --source ref --run-id baseline --scenario2 --sweep 1.10,1.15,1.20
```

## Notes
- Real project files can be added later under `data/raw/`.
- Fixtures are used to develop the pipeline contract before full data arrives.
- CAD UI automation is not required; DXF + GIS exports are generated automatically.
