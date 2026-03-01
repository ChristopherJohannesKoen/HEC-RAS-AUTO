param(
    [string]$RunId = "prompt_live_run",
    [string]$AssignedScenario = "scenario_2",
    [string]$Source = "ref",
    [string]$PromptFile = "prompts/meerlustkloof_assignment_prompt.txt",
    [switch]$SkipWordReports
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PromptFile)) {
    throw "Prompt file not found: $PromptFile"
}

if (-not $env:OPENAI_API_KEY -or $env:OPENAI_API_KEY -eq "YOUR_OPENAI_API_KEY") {
    throw "Set OPENAI_API_KEY in this shell before running. Example: `$env:OPENAI_API_KEY='sk-...'"
}

$prompt = Get-Content -Path $PromptFile -Raw
$scenarioRunId = "${RunId}_${AssignedScenario}"

ras-auto agent-run `
  --prompt "$prompt" `
  --source $Source `
  --run-id $RunId `
  --assigned-scenario $AssignedScenario `
  --strict `
  --config config/project.yml `
  --sheets config/sheets.yml `
  --thresholds config/thresholds.yml `
  --automation config/automation.yml `
  --ai config/ai.yml `
  --agent-config config/agent.yml `
  --retrieval config/retrieval.yml

if (-not $SkipWordReports) {
    ras-auto build-report --run-id $RunId --ai config/ai.yml --write-word-doc
    ras-auto build-report --run-id $scenarioRunId --ai config/ai.yml --write-word-doc
}

Write-Host "Done. Baseline outputs: outputs/$RunId"
Write-Host "Done. Scenario outputs: outputs/$scenarioRunId"
