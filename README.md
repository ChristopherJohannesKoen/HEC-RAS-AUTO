# HEC-RAS-AUTO

Deterministic automation for Meerlustkloof 1D steady HEC-RAS workflows:
- baseline model build/compute/report
- scenario re-run and comparison
- prompt-driven orchestration with optional OpenAI support

## Platform Requirements

- Windows 10/11
- Python 3.11+
- HEC-RAS 6.6 or 6.7 installed (`Ras.exe`)
- PowerShell

## Repository Layout (Runtime-Critical)

- `src/` application code
- `config/` run and parsing configuration
- `shell/ras_project/` HEC-RAS shell project template
- `ref/` source input package used by `--source ref`
- `data/raw/meerlustkloof/` runtime intake target (auto-populated from `ref` by agent/autopilot)
- `templates/` report templates

Everything not required for runtime has been moved under `archive/` for cleanup.

## Setup

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -e .[dev]
ras-auto init
```

## Run the Full Meerlustkloof Example

Use the bundled script (recommended):

```powershell
$env:OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
.\scripts\run_prompt_live_run_example.ps1
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
```

The script reads the full assignment prompt from:
- `prompts/meerlustkloof_assignment_prompt.txt`

And runs:
- `ras-auto agent-run` for baseline + Scenario 2 triad (`lenient`, `average`, `conservative`)
- `ras-auto build-report --write-word-doc` for baseline
- `ras-auto build-report --write-word-doc` for each Scenario 2 tier

## Equivalent Manual Commands

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

## Outputs

Baseline run outputs:
- `outputs/prompt_live_run/`
- `outputs/reports/prompt_live_run_report_draft.md`
- `outputs/reports/prompt_live_run_final_ai_report.md`
- `outputs/reports/prompt_live_run_final_ai_report.docx`

Scenario outputs:
- `outputs/prompt_live_run_scenario_2_lenient/`
- `outputs/prompt_live_run_scenario_2_average/`
- `outputs/prompt_live_run_scenario_2_conservative/`
- `outputs/reports/prompt_live_run_scenario_2_lenient_report_draft.md`
- `outputs/reports/prompt_live_run_scenario_2_average_report_draft.md`
- `outputs/reports/prompt_live_run_scenario_2_conservative_report_draft.md`
- `outputs/reports/prompt_live_run_scenario_2_triad_report_draft.md`
- `outputs/prompt_live_run/comparison/scenario2_tier_comparison.csv`
- `outputs/prompt_live_run/comparison/scenario2_tier_overlay_profile.png`

Submission bundle:
- `outputs/prompt_live_run/submission/manifest.json`

## Troubleshooting

- If `agent-run` fails due file locks in `runs/<run_id>/ras_project`, close HEC-RAS and retry:
  - `ras-auto agent-resume --run-id <run_id> --strict`
- If no AI report is produced, confirm `OPENAI_API_KEY` is set in the current shell.
- If `Ras.exe` path is not discovered, set `HEC_RAS_EXE` or edit `config/project.yml`.

## Security

- Never commit real API keys.
- Use environment variables only:
  - `$env:OPENAI_API_KEY = "..."` for current shell session
