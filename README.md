# HEC-RAS-AUTO

Deterministic + agent-assisted automation for the Meerlustkloof 1D steady HEC-RAS workflow:
- baseline model build/compute/report
- Scenario 2 climate-intensification triad (`lenient`, `average`, `conservative`)
- optional OpenAI-assisted narrative report generation

## Requirements

- Windows 10/11
- Python 3.11+
- HEC-RAS 6.6 or 6.7 installed (`Ras.exe`)
- PowerShell

## Repository Layout

Runtime source:
- `src/` application code
- `config/` run/automation/report configuration
- `shell/ras_project/` HEC-RAS shell project template
- `scripts/` runnable helper scripts
- `prompts/` prompt files used by example scripts
- `ref/` input package used by `--source ref`
- `data/raw/meerlustkloof/` runtime intake destination (auto-populated from `ref`)

Versioned example output snapshot:
- `examples/prompt_live_run/` curated baseline + Scenario 2 triad artifacts for quick preview

Generated runtime folders (ignored by git):
- `outputs/`, `runs/`, `logs/`, `data/processed/*`

## Setup

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -e .[dev]
ras-auto init
```

## Run The Full Example

Recommended (scripted):

```powershell
$env:OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
.\scripts\run_prompt_live_run_example.ps1
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
```

The script uses:
- `prompts/meerlustkloof_assignment_prompt.txt`
- `run_id=prompt_live_run`
- assigned scenario `scenario_2`

## Manual Equivalent

```powershell
$env:OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
$prompt = Get-Content .\prompts\meerlustkloof_assignment_prompt.txt -Raw

ras-auto agent-run `
  --prompt "$prompt" `
  --source ref `
  --run-id prompt_live_run `
  --assigned-scenario scenario_2 `
  --strict `
  --config config/project.yml `
  --sheets config/sheets.yml `
  --thresholds config/thresholds.yml `
  --automation config/automation.yml `
  --ai config/ai.yml `
  --agent-config config/agent.yml `
  --retrieval config/retrieval.yml

ras-auto build-report --run-id prompt_live_run --ai config/ai.yml --write-word-doc
ras-auto build-report --run-id prompt_live_run_scenario_2_lenient --ai config/ai.yml --write-word-doc
ras-auto build-report --run-id prompt_live_run_scenario_2_average --ai config/ai.yml --write-word-doc
ras-auto build-report --run-id prompt_live_run_scenario_2_conservative --ai config/ai.yml --write-word-doc

Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
```

## Output Conventions

Live generated outputs:
- `outputs/<run_id>/...`
- `outputs/reports/...`

Scenario 2 triad outputs:
- `outputs/prompt_live_run_scenario_2_lenient/`
- `outputs/prompt_live_run_scenario_2_average/`
- `outputs/prompt_live_run_scenario_2_conservative/`
- `outputs/prompt_live_run/comparison/scenario2_tier_comparison.csv`
- `outputs/prompt_live_run/comparison/scenario2_tier_overlay_profile.png`

Submission manifest:
- `outputs/prompt_live_run/submission/manifest.json`

Committed sample output preview:
- `examples/prompt_live_run/`

## Troubleshooting

- If `agent-run` fails because files are locked in `runs/<run_id>/ras_project`, close HEC-RAS and retry:
  - `ras-auto agent-resume --run-id <run_id> --strict`
- If AI reports are skipped, confirm `OPENAI_API_KEY` is set in the current shell.
- If `Ras.exe` is not detected, set `HEC_RAS_EXE` or update `config/project.yml`.

## Security

- Never commit real API keys.
- Use environment variables only:
  - `$env:OPENAI_API_KEY = "..."`
