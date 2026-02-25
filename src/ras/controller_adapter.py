from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class HECControllerError(RuntimeError):
    """Raised when COM automation execution fails."""


@dataclass
class HECRASControllerAdapter:
    timeout_sec: int = 600

    def detect_progid(self) -> str:
        for progid in ("RAS67.HECRASController", "RAS66.HECRASController"):
            if self._com_available(progid):
                return progid
        raise HECControllerError("No compatible HEC-RAS COM ProgID found (RAS67/RAS66).")

    def check_no_running_instances(self, auto_close: bool = False) -> None:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Process Ras -ErrorAction SilentlyContinue | Measure-Object | % Count"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            count = int(result.stdout.strip() or "0")
        except ValueError:
            count = 0
        if count <= 0:
            return
        if auto_close:
            self._close_running_instances()
            return
        raise HECControllerError(
            f"Detected {count} running Ras.exe instances. Close them before unattended run."
        )

    def run_compute(
        self,
        run_project_dir: Path,
        sdf_path: Path,
        flow_json: Path,
        river_name: str,
        reach_name: str,
        strict: bool = True,
        auto_close_instances: bool = False,
    ) -> dict[str, str | bool]:
        progid = self.detect_progid()
        self.check_no_running_instances(auto_close=auto_close_instances)
        project_files = list(run_project_dir.glob("*.prj"))
        if not project_files:
            raise HECControllerError(f"No .prj found in run project directory: {run_project_dir}")
        prj = project_files[0]

        payload = {
            "project": str(prj.resolve()),
            "sdf": str(sdf_path.resolve()),
            "flow_json": str(flow_json.resolve()),
            "river_name": river_name,
            "reach_name": reach_name,
            "progid": progid,
            "strict": strict,
            "run_project_dir": str(run_project_dir.resolve()),
        }
        return self._run_controller_script(payload)

    @staticmethod
    def _close_running_instances() -> None:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Process Ras -ErrorAction SilentlyContinue | Stop-Process -Force"],
            capture_output=True,
            text=True,
            check=False,
        )

    def _com_available(self, progid: str) -> bool:
        script = f"""
$obj = $null
try {{
  $obj = New-Object -ComObject '{progid}'
  Write-Output 'OK'
}} catch {{
  Write-Output 'FAIL'
}} finally {{
  if ($obj -ne $null) {{
    try {{ $obj.QuitRas() | Out-Null }} catch {{}}
  }}
}}
"""
        out = self._run_ps_inline(script)
        return "OK" in out

    def _run_controller_script(self, payload: dict[str, object]) -> dict[str, str | bool]:
        script = self._controller_script()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            ps1 = td_path / "run_hecras.ps1"
            in_json = td_path / "input.json"
            out_json = td_path / "output.json"
            ps1.write_text(script, encoding="utf-8")
            in_json.write_text(json.dumps(payload), encoding="utf-8")

            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
                "-InputJson",
                str(in_json),
                "-OutputJson",
                str(out_json),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
            if proc.returncode != 0:
                raise HECControllerError(
                    "HEC-RAS COM script failed.\n"
                    f"stdout:\n{proc.stdout}\n"
                    f"stderr:\n{proc.stderr}"
                )
            if not out_json.exists():
                raise HECControllerError("HEC-RAS COM script did not produce output.json")
            data = json.loads(out_json.read_text(encoding="utf-8"))
            if not data.get("success", False):
                raise HECControllerError(f"HEC-RAS COM automation failed: {data.get('error', 'unknown')}")
            return data

    @staticmethod
    def _run_ps_inline(script: str) -> str:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        return (proc.stdout or "") + (proc.stderr or "")

    @staticmethod
    def _controller_script() -> str:
        # Note: run is guardrailed; if plan is invalid or compute cannot proceed, script returns success=false.
        return r"""
param(
  [Parameter(Mandatory=$true)][string]$InputJson,
  [Parameter(Mandatory=$true)][string]$OutputJson
)

$ErrorActionPreference = "Stop"

function Write-Result($obj) {
  $obj | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputJson -Encoding utf8
}

try {
  $payload = Get-Content -Path $InputJson -Raw | ConvertFrom-Json
  $obj = New-Object -ComObject $payload.progid
  $messages = @()

  try {
    $obj.Project_Open($payload.project)
    $messages += "Project opened"

    # Import geometry from staged SDF.
    $obj.Geometry_GISImport($payload.sdf, "SDF")
    $messages += "Geometry_GISImport completed"
    $obj.Project_Save()

    # Try steady-flow setup (best effort; some projects may require pre-existing plan/profile definitions).
    $flow = Get-Content -Path $payload.flow_json -Raw | ConvertFrom-Json
    try {
      $obj.SteadyFlow_ClearFlowData()
      $qUp = New-Object 'System.Single[]' 1
      $qUp[0] = [single]$flow.upstream_flow_cms
      $qTr = New-Object 'System.Single[]' 1
      $qTr[0] = [single]($flow.upstream_flow_cms + $flow.tributary_flow_cms)
      $usStation = if ($flow.upstream_station_hint) { [string]$flow.upstream_station_hint } else { '3905' }
      $trStation = if ($flow.tributary_station_hint) { [string]$flow.tributary_station_hint } else { '2405' }

      # Station mapping assumes assignment convention (upstream station ~3905, confluence station ~2405).
      $obj.SteadyFlow_SetFlow($payload.river_name, $payload.reach_name, $usStation, $qUp)
      $obj.SteadyFlow_SetFlow($payload.river_name, $payload.reach_name, $trStation, $qTr)

      $bc = New-Object 'System.Single[]' 1
      $bc[0] = [single]$flow.downstream_normal_depth_slope
      [void]$obj.SteadyFlow_FixedWSBoundary($payload.river_name, $payload.reach_name, $false, $bc)
      $messages += "Steady flow and boundary attempted"
    } catch {
      $messages += ("Steady flow setup warning: " + $_.Exception.Message)
      if ($payload.strict) { throw }
    }

    # Compute current plan.
    [int]$nmsg = 0
    $outMsgs = New-Object 'System.String[]' 500
    try {
      $ok = $obj.Compute_CurrentPlan([ref]$nmsg, $outMsgs, $true)
      $messages += ("Compute_CurrentPlan returned: " + $ok)
      if (-not $ok -and $payload.strict) {
        throw "Compute_CurrentPlan returned false"
      }
    } catch {
      throw ("Compute_CurrentPlan failed: " + $_.Exception.Message)
    }

    $currentPlan = $obj.CurrentPlanFile()
    $currentGeom = $obj.CurrentGeomFile()
    $currentSteady = $obj.CurrentSteadyFile()

    $obj.Project_Save()
    $obj.Project_Close()

    $runDir = $payload.run_project_dir
    $plans = Get-ChildItem -Path $runDir -Filter '*.p??' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    $hdfs = Get-ChildItem -Path $runDir -Filter '*.hdf' -ErrorAction SilentlyContinue | `
      Where-Object { $_.Name -match '\.p\d\d(\..+)?\.hdf$' -or $_.Name -match '\.p\d\d\.hdf$' -or $_.Name -match 'plan|results' } | `
      Sort-Object LastWriteTime -Descending
    $logs = Get-ChildItem -Path $runDir -Filter '*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending

    if ($payload.strict) {
      if ($plans.Count -eq 0) { throw "No plan file (*.p##) found after compute." }
      if ($hdfs.Count -eq 0) { throw "No plan-result HDF found after compute." }
    }

    $result = [ordered]@{
      success = $true
      messages = $messages
      current_plan = $currentPlan
      current_geom = $currentGeom
      current_steady = $currentSteady
      compute_message_count = $nmsg
      plan_files = @($plans | ForEach-Object { $_.FullName })
      hdf_files = @($hdfs | ForEach-Object { $_.FullName })
      log_files = @($logs | ForEach-Object { $_.FullName })
    }
    Write-Result $result
  }
  finally {
    if ($null -ne $obj) {
      try { $obj.QuitRas() | Out-Null } catch {}
    }
  }
}
catch {
  $fail = [ordered]@{
    success = $false
    error = $_.Exception.Message
  }
  Write-Result $fail
  exit 1
}
"""
