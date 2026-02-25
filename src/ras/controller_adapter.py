from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
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
        try:
            return self._run_controller_pywin32(payload)
        except ImportError:
            # Fallback path for environments without pywin32.
            return self._run_controller_script(payload)

    def _run_controller_pywin32(self, payload: dict[str, object]) -> dict[str, str | bool]:
        import win32com.client  # type: ignore[import-not-found]

        messages: list[str] = []
        run_dir = Path(str(payload["run_project_dir"]))
        strict = bool(payload.get("strict", True))
        os.chdir(run_dir)

        obj = win32com.client.Dispatch(str(payload["progid"]))
        try:
            dismissed = self._dismiss_ras_dialogs()
            if dismissed:
                messages.append(f"Dismissed startup RAS dialogs: {dismissed}")

            obj.Project_Open(str(payload["project"]))
            time.sleep(0.4)
            dismissed = self._dismiss_ras_dialogs()
            if dismissed:
                messages.append(f"Dismissed post-open RAS dialogs: {dismissed}")

            current_project = self._safe_call(obj, "CurrentProjectFile")
            if not current_project:
                raise HECControllerError(
                    "Project_Open did not load a project (CurrentProjectFile empty). "
                    "Check HEC-RAS startup dialogs/permissions."
                )
            messages.append(f"Project opened: {current_project}")

            self._ensure_plan_active(obj, messages, strict=strict)

            obj.Geometry_GISImport("SDF Import", str(payload["sdf"]))
            messages.append("Geometry_GISImport completed")
            time.sleep(0.3)
            dismissed = self._dismiss_ras_dialogs()
            if dismissed:
                messages.append(f"Dismissed post-import RAS dialogs: {dismissed}")

            obj.Project_Save()
            self._ensure_plan_active(obj, messages, strict=strict)

            flow = json.loads(Path(str(payload["flow_json"])).read_text(encoding="utf-8"))
            try:
                obj.SteadyFlow_ClearFlowData()
                us_station = str(flow.get("upstream_station_hint") or "3905")
                tr_station = str(flow.get("tributary_station_hint") or "2405")
                q_up = [float(flow["upstream_flow_cms"])]
                q_tr = [float(flow["upstream_flow_cms"]) + float(flow["tributary_flow_cms"])]
                obj.SteadyFlow_SetFlow(str(payload["river_name"]), str(payload["reach_name"]), us_station, q_up)
                obj.SteadyFlow_SetFlow(str(payload["river_name"]), str(payload["reach_name"]), tr_station, q_tr)
                bc = [float(flow["downstream_normal_depth_slope"])]
                obj.SteadyFlow_FixedWSBoundary(str(payload["river_name"]), str(payload["reach_name"]), False, bc)
                messages.append("Steady flow and boundary attempted")
            except Exception as exc:
                messages.append(f"Steady flow setup warning: {exc}")
                if strict:
                    raise

            try:
                compute_raw = obj.Compute_CurrentPlan()
                ok = self._coerce_compute_ok(compute_raw)
                messages.append(f"Compute_CurrentPlan returned: {ok}")
                if not ok and strict:
                    raise HECControllerError("Compute_CurrentPlan returned false")
            except Exception as exc:
                raise HECControllerError(f"Compute_CurrentPlan failed: {exc}") from exc

            current_plan = self._safe_call(obj, "CurrentPlanFile")
            current_geom = self._safe_call(obj, "CurrentGeomFile")
            current_steady = self._safe_call(obj, "CurrentSteadyFile")

            obj.Project_Save()
            try:
                obj.Project_Close()
            except Exception:
                pass

            plans = sorted(run_dir.glob("*.p??"), key=lambda p: p.stat().st_mtime, reverse=True)
            hdfs = sorted(
                [
                    p
                    for p in run_dir.glob("*.hdf")
                    if (
                        ".p" in p.name.lower()
                        and p.suffix.lower() == ".hdf"
                        and ".g" not in p.name.lower()
                    )
                    or "plan" in p.name.lower()
                    or "results" in p.name.lower()
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            logs = sorted(run_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

            if strict:
                if not plans:
                    raise HECControllerError("No plan file (*.p##) found after compute.")
                if not hdfs:
                    raise HECControllerError("No plan-result HDF found after compute.")

            return {
                "success": True,
                "messages": messages,
                "current_plan": current_plan,
                "current_geom": current_geom,
                "current_steady": current_steady,
                "compute_message_count": 0,
                "plan_files": [str(p.resolve()) for p in plans],
                "hdf_files": [str(p.resolve()) for p in hdfs],
                "log_files": [str(p.resolve()) for p in logs],
            }
        finally:
            self._dismiss_ras_dialogs()
            try:
                obj.QuitRas()
            except Exception:
                pass

    @staticmethod
    def _safe_call(obj: object, method_name: str) -> str:
        try:
            value = getattr(obj, method_name)()
            if value is None:
                return ""
            return str(value).strip()
        except Exception:
            return ""

    @staticmethod
    def _coerce_compute_ok(raw: object) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (tuple, list)) and raw:
            return bool(raw[0])
        if raw is None:
            return False
        return bool(raw)

    def _ensure_plan_active(self, obj: object, messages: list[str], strict: bool) -> None:
        cur_plan = self._safe_call(obj, "CurrentPlanFile")
        if cur_plan:
            return
        set_ok = False
        for candidate in ("Plan 01", "p01"):
            try:
                set_ok = bool(getattr(obj, "Plan_SetCurrent")(candidate))
                messages.append(f"Plan_SetCurrent({candidate}): {set_ok}")
            except Exception as exc:
                messages.append(f"Plan_SetCurrent warning ({candidate}): {exc}")
            cur_plan = self._safe_call(obj, "CurrentPlanFile")
            if cur_plan:
                return
            if set_ok:
                # Some versions return success but update current plan lazily.
                time.sleep(0.2)
                cur_plan = self._safe_call(obj, "CurrentPlanFile")
                if cur_plan:
                    return
        if strict:
            raise HECControllerError("No current plan active after project open/import (expected Plan 01/p01).")

    @staticmethod
    def _dismiss_ras_dialogs() -> int:
        try:
            import win32con  # type: ignore[import-not-found]
            import win32gui  # type: ignore[import-not-found]
        except ImportError:
            return 0

        closed = 0

        def _cb(hwnd: int, _lparam: int) -> bool:
            nonlocal closed
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd).strip()
                if title == "RAS":
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    closed += 1
            except Exception:
                return True
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            return closed
        return closed

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
                details = ""
                if out_json.exists():
                    try:
                        payload = json.loads(out_json.read_text(encoding="utf-8"))
                        details = f"\noutput.json:\n{json.dumps(payload, indent=2)}"
                    except Exception:
                        details = f"\noutput.json raw:\n{out_json.read_text(encoding='utf-8', errors='ignore')}"
                raise HECControllerError(
                    "HEC-RAS COM script failed.\n"
                    f"stdout:\n{proc.stdout}\n"
                    f"stderr:\n{proc.stderr}"
                    f"{details}"
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

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class RasWin {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr childAfter, string className, string windowTitle);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}
"@ -ErrorAction SilentlyContinue

function Dismiss-RasDialogs {
  $script:__rasClicked = 0
  $cb = [RasWin+EnumWindowsProc]{
    param([IntPtr]$hWnd, [IntPtr]$lParam)
    if (-not [RasWin]::IsWindowVisible($hWnd)) { return $true }
    $sb = New-Object System.Text.StringBuilder 256
    [void][RasWin]::GetWindowText($hWnd, $sb, $sb.Capacity)
    if ($sb.ToString() -eq "RAS") {
      $btn = [RasWin]::FindWindowEx($hWnd, [IntPtr]::Zero, "Button", $null)
      if ($btn -ne [IntPtr]::Zero) {
        # BM_CLICK
        [void][RasWin]::SendMessage($btn, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
        $script:__rasClicked++
      }
    }
    return $true
  }
  [void][RasWin]::EnumWindows($cb, [IntPtr]::Zero)
  return $script:__rasClicked
}

try {
  $payload = Get-Content -Path $InputJson -Raw | ConvertFrom-Json
  Set-Location -Path $payload.run_project_dir
  [System.Environment]::CurrentDirectory = [string]$payload.run_project_dir
  $obj = New-Object -ComObject $payload.progid
  $messages = @()
  Start-Sleep -Milliseconds 400
  $dismissed = Dismiss-RasDialogs
  if ($dismissed -gt 0) { $messages += ("Dismissed startup RAS dialogs: " + $dismissed) }

  try {
    $obj.Project_Open($payload.project)
    $messages += "Project_Open attempted"
    Start-Sleep -Milliseconds 400
    $dismissed = Dismiss-RasDialogs
    if ($dismissed -gt 0) { $messages += ("Dismissed post-open RAS dialogs: " + $dismissed) }
    $curProject = ""
    try { $curProject = $obj.CurrentProjectFile() } catch {}
    if ([string]::IsNullOrWhiteSpace($curProject)) {
      throw "Project_Open did not load a project (CurrentProjectFile empty). Check HEC-RAS startup dialogs/permissions."
    }
    $messages += ("Project opened: " + $curProject)

    # Ensure current plan exists; some shell projects open with empty current plan.
    $curPlan = ""
    try { $curPlan = $obj.CurrentPlanFile() } catch {}
    if ([string]::IsNullOrWhiteSpace($curPlan)) {
      try {
        $setPlan = $obj.Plan_SetCurrent("Plan 01")
        $messages += ("Plan_SetCurrent(Plan 01): " + $setPlan)
      } catch {
        $messages += ("Plan_SetCurrent warning: " + $_.Exception.Message)
      }
      if (-not $setPlan) {
        try {
          $setPlan = $obj.Plan_SetCurrent("p01")
          $messages += ("Plan_SetCurrent(p01): " + $setPlan)
        } catch {
          $messages += ("Plan_SetCurrent warning: " + $_.Exception.Message)
        }
      }
      try { $curPlan = $obj.CurrentPlanFile() } catch {}
      if ([string]::IsNullOrWhiteSpace($curPlan) -and $payload.strict) {
        throw "No current plan active after project open (expected Plan 01/p01)."
      }
    }

    # Import geometry from staged SDF.
    $obj.Geometry_GISImport("SDF Import", $payload.sdf)
    $messages += "Geometry_GISImport completed"
    Start-Sleep -Milliseconds 300
    $dismissed = Dismiss-RasDialogs
    if ($dismissed -gt 0) { $messages += ("Dismissed post-import RAS dialogs: " + $dismissed) }
    $obj.Project_Save()

    # Re-check plan after import/save.
    try { $curPlan = $obj.CurrentPlanFile() } catch {}
    if ([string]::IsNullOrWhiteSpace($curPlan)) {
      try {
        $setPlan = $obj.Plan_SetCurrent("Plan 01")
        $messages += ("Plan_SetCurrent(Plan 01) after import: " + $setPlan)
      } catch {
        $messages += ("Plan_SetCurrent warning after import: " + $_.Exception.Message)
      }
      if (-not $setPlan) {
        try {
          $setPlan = $obj.Plan_SetCurrent("p01")
          $messages += ("Plan_SetCurrent(p01) after import: " + $setPlan)
        } catch {
          $messages += ("Plan_SetCurrent warning after import: " + $_.Exception.Message)
        }
      }
      try { $curPlan = $obj.CurrentPlanFile() } catch {}
    }
    if ([string]::IsNullOrWhiteSpace($curPlan) -and $payload.strict) {
      throw "No current plan active after project open/import (expected p01)."
    }

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
