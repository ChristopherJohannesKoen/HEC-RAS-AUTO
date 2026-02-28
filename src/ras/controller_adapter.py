from __future__ import annotations

import json
import os
import re
import shutil
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
        # Prefer HEC-RAS 6.6 by default, then fall back to 6.7.
        for progid in ("RAS66.HECRASController", "RAS67.HECRASController"):
            if self._com_available(progid):
                return progid
        raise HECControllerError("No compatible HEC-RAS COM ProgID found (RAS66/RAS67).")

    def check_no_running_instances(self, auto_close: bool = False) -> None:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(@(Get-Process Ras -ErrorAction SilentlyContinue) + @(Get-Process RasProcess -ErrorAction SilentlyContinue)).Count",
            ],
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
        apply_flow_via_com: bool = False,
        ras_exe_path: Path | None = None,
        prefer_cli: bool = True,
        allow_com_fallback: bool = False,
    ) -> dict[str, object]:
        # sdf_path is kept for interface compatibility; file-first mode does not
        # require geometry import at compute time.
        _ = sdf_path

        run_project_dir = run_project_dir.resolve()
        self.check_no_running_instances(auto_close=auto_close_instances)
        prj = self._pick_project_file(run_project_dir).resolve()
        if not flow_json.exists():
            raise HECControllerError(f"Missing steady flow payload: {flow_json}")
        flow_payload = json.loads(flow_json.read_text(encoding="utf-8"))
        errors: list[str] = []

        if prefer_cli:
            try:
                ras_exe = self._resolve_ras_exe(ras_exe_path)
                return self._run_compute_cli(
                    ras_exe=ras_exe,
                    run_dir=run_project_dir,
                    project_file=prj,
                    strict=strict,
                )
            except HECControllerError as exc:
                errors.append(f"CLI compute failed: {exc}")
                if not allow_com_fallback:
                    raise HECControllerError(errors[-1]) from exc

        try:
            progid = self.detect_progid()
            result = self._run_controller_pywin32(
                progid=progid,
                run_dir=run_project_dir,
                project_file=prj,
                strict=strict,
                flow_payload=flow_payload,
                river_name=river_name,
                reach_name=reach_name,
                apply_flow_via_com=apply_flow_via_com,
            )
            if errors:
                existing = result.get("messages", [])
                if not isinstance(existing, list):
                    existing = [str(existing)]
                result["messages"] = errors + [str(m) for m in existing]
            return result
        except Exception as exc:
            if errors:
                raise HECControllerError("; ".join(errors + [f"COM fallback failed: {exc}"])) from exc
            raise

    def _run_compute_cli(
        self,
        ras_exe: Path,
        run_dir: Path,
        project_file: Path,
        strict: bool,
    ) -> dict[str, object]:
        # Primary unattended strategy: explicit current-plan compute using a
        # batch command pattern proven in HEC-Commander workflows:
        #   "Ras.exe" -c "project.prj" "plan.p##"
        primary = self._run_compute_cli_current_plan(
            ras_exe=ras_exe,
            run_dir=run_dir,
            project_file=project_file,
            strict=False,
        )
        if primary.get("success", False):
            return primary

        # Secondary fallback: HEC-RAS test mode.
        fallback = self._run_compute_cli_test_mode(
            ras_exe=ras_exe,
            run_dir=run_dir,
            project_file=project_file,
            strict=False,
        )
        msgs = []
        prim_msgs = primary.get("messages", [])
        if isinstance(prim_msgs, list):
            msgs.extend([str(m) for m in prim_msgs])
        msgs.append("Primary CLI mode (-c project+plan) produced no native result artifacts.")
        fb_msgs = fallback.get("messages", [])
        if isinstance(fb_msgs, list):
            msgs.extend([str(m) for m in fb_msgs])
        fallback["messages"] = msgs
        success = bool(fallback.get("success", False))
        if strict and not success:
            raise HECControllerError(
                "CLI compute finished without native result artifacts in both -c and -test modes. "
                "Check HEC-RAS popups/logs and HECRASPlotDriverError.txt."
            )
        return fallback

    def _run_compute_cli_current_plan(
        self,
        ras_exe: Path,
        run_dir: Path,
        project_file: Path,
        strict: bool,
    ) -> dict[str, object]:
        self._clear_readonly(run_dir)
        self._repair_plotdriver_state()
        env = self._build_cli_env(run_dir)
        project_abs = project_file.resolve()
        plan_abs = self._pick_plan_file(run_dir, project_abs).resolve()
        bat_path = run_dir / "_hec_run_compute.bat"
        bat_cmd = f"\"{ras_exe}\" -c \"{project_abs}\" \"{plan_abs}\""
        bat_path.write_text(f"@echo off\r\n{bat_cmd}\r\n", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                ["cmd.exe", "/c", str(bat_path)],
                cwd=str(run_dir),
                env=env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            raise HECControllerError(f"Failed to start Ras.exe current-plan batch compute: {exc}") from exc

        start = time.time()
        stall_timeout_sec = max(180, min(self.timeout_sec // 2, 600))
        last_activity = time.time()
        last_seen_mtime = 0.0
        while proc.poll() is None:
            self._dismiss_ras_dialogs(aggressive=True)
            try:
                mtimes = [p.stat().st_mtime for p in run_dir.iterdir()]
                if mtimes:
                    current_mtime = max(mtimes)
                    if current_mtime > last_seen_mtime:
                        last_seen_mtime = current_mtime
                        last_activity = time.time()
            except Exception:
                pass
            if (time.time() - last_activity) > stall_timeout_sec:
                self._close_running_instances()
                raise HECControllerError(
                    f"Ras.exe current-plan batch stalled with no file activity for {stall_timeout_sec}s; "
                    "likely waiting on internal error dialog or failed compute state."
                )
            if (time.time() - start) > self.timeout_sec:
                self._close_running_instances()
                raise HECControllerError(
                    f"Ras.exe current-plan batch compute timed out after {self.timeout_sec}s."
                )
            time.sleep(0.5)

        stdout = ""
        stderr = ""
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            pass
        artifacts = self._collect_output_files(run_dir)
        messages: list[str] = [
            f"CLI command (bat): {bat_cmd}",
            f"CLI return code: {proc.returncode}",
        ]
        if stdout.strip():
            messages.append(f"CLI stdout: {stdout.strip()[:4000]}")
        if stderr.strip():
            messages.append(f"CLI stderr: {stderr.strip()[:4000]}")

        success = bool(artifacts["hdf_files"] or artifacts["output_files"])
        if strict and not success:
            raise HECControllerError(
                "CLI current-plan batch compute finished without result artifacts (*.p##.hdf or *.O##). "
                "Check HEC-RAS popups/logs and HECRASPlotDriverError.txt."
            )

        try:
            bat_path.unlink(missing_ok=True)
        except Exception:
            pass

        return {
            "success": success,
            "messages": messages,
            "current_plan": "",
            "current_geom": "",
            "current_steady": "",
            "compute_message_count": 0,
            "compute_blocking_mode": True,
            "plan_files": artifacts["plan_files"],
            "hdf_files": artifacts["hdf_files"],
            "output_files": artifacts["output_files"],
            "log_files": artifacts["log_files"],
            "backend": "cli",
            "ras_exe": str(ras_exe),
        }

    def _run_compute_cli_test_mode(
        self,
        ras_exe: Path,
        run_dir: Path,
        project_file: Path,
        strict: bool,
    ) -> dict[str, object]:
        self._clear_readonly(run_dir)
        self._repair_plotdriver_state()
        env = self._build_cli_env(run_dir)
        project_abs = project_file.resolve()
        test_dir = run_dir.parent / f"{run_dir.name} [Test]"
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)

        cmd = [str(ras_exe), str(project_abs), "-test", "-hideCompute"]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(run_dir.parent),
                env=env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            raise HECControllerError(f"Failed to start Ras.exe test-batch compute: {exc}") from exc

        start = time.time()
        error_text = ""
        last_activity = time.time()
        last_seen_mtime = 0.0
        stall_timeout_sec = max(180, min(self.timeout_sec // 2, 600))
        while proc.poll() is None:
            self._dismiss_ras_dialogs(aggressive=True)
            if test_dir.exists():
                try:
                    mtimes = [p.stat().st_mtime for p in test_dir.iterdir()]
                    if mtimes:
                        current_mtime = max(mtimes)
                        if current_mtime > last_seen_mtime:
                            last_seen_mtime = current_mtime
                            last_activity = time.time()
                except Exception:
                    pass
                data_error_file = next(test_dir.glob("*.data_errors.txt"), None)
                if data_error_file and data_error_file.exists():
                    try:
                        err = data_error_file.read_text(encoding="utf-8", errors="ignore")
                        if "Unable to delete temporary results file" in err:
                            error_text = err.strip()
                            self._close_running_instances()
                            break
                    except Exception:
                        pass
            if (time.time() - last_activity) > stall_timeout_sec:
                self._close_running_instances()
                raise HECControllerError(
                    f"Ras.exe test-batch stalled with no file activity for {stall_timeout_sec}s; "
                    "likely waiting on internal error dialog or failed compute state."
                )
            if (time.time() - start) > self.timeout_sec:
                self._close_running_instances()
                raise HECControllerError(
                    f"Ras.exe test-batch compute timed out after {self.timeout_sec}s."
                )
            time.sleep(0.5)

        stdout = ""
        stderr = ""
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            pass
        source_dir = test_dir if test_dir.exists() else run_dir
        source_artifacts = self._collect_output_files(source_dir)

        for pattern in ("*.p??.hdf", "*.p??.tmp.hdf", "*.g??.hdf", "*.o??", "*.computeMsgs.txt", "*.testing.txt"):
            for file_path in source_dir.glob(pattern):
                try:
                    shutil.copy2(file_path, run_dir / file_path.name)
                except Exception:
                    pass
        artifacts = self._collect_output_files(run_dir)
        messages: list[str] = [
            "CLI command: " + " ".join(f"\"{a}\"" if " " in a else a for a in cmd),
            f"CLI return code: {proc.returncode}",
            f"CLI test folder: {test_dir}",
        ]
        if error_text:
            messages.append(f"CLI data error: {error_text[:2000]}")
        if stdout.strip():
            messages.append(f"CLI stdout: {stdout.strip()[:4000]}")
        if stderr.strip():
            messages.append(f"CLI stderr: {stderr.strip()[:4000]}")
        if source_dir == test_dir and not source_artifacts["hdf_files"] and not source_artifacts["output_files"]:
            messages.append("CLI test mode produced no outputs in [Test] folder.")

        success = bool(artifacts["hdf_files"] or artifacts["output_files"])
        if strict and not success:
            raise HECControllerError(
                "CLI test-batch compute finished without result artifacts (*.p##.hdf or *.O##). "
                "Check HEC-RAS popups/logs and HECRASPlotDriverError.txt."
            )

        return {
            "success": success,
            "messages": messages,
            "current_plan": "",
            "current_geom": "",
            "current_steady": "",
            "compute_message_count": 0,
            "compute_blocking_mode": True,
            "plan_files": artifacts["plan_files"],
            "hdf_files": artifacts["hdf_files"],
            "output_files": artifacts["output_files"],
            "log_files": artifacts["log_files"],
            "backend": "cli",
            "ras_exe": str(ras_exe),
        }

    def _run_controller_pywin32(
        self,
        progid: str,
        run_dir: Path,
        project_file: Path,
        strict: bool,
        flow_payload: dict[str, object],
        river_name: str,
        reach_name: str,
        apply_flow_via_com: bool,
    ) -> dict[str, object]:
        import win32com.client  # type: ignore[import-not-found]

        messages: list[str] = []
        project_abs = project_file.resolve()
        original_cwd = Path.cwd()
        os.chdir(run_dir)

        obj = win32com.client.gencache.EnsureDispatch(progid)
        try:
            obj.Project_Open(str(project_abs))
            time.sleep(0.4)

            current_project = self._safe_call(obj, "CurrentProjectFile")
            if not current_project:
                self._dismiss_ras_dialogs()
                time.sleep(0.2)
                current_project = self._safe_call(obj, "CurrentProjectFile")
            if current_project:
                messages.append(f"Project opened: {current_project}")
            else:
                messages.append(
                    "Project_Open completed but CurrentProjectFile is empty; "
                    "continuing with compute path and validating via result artifacts."
                )

            # Plan activation via COM can be brittle across versions; avoid hard fail here
            # and rely on compute/result artifact checks for final validation.
            self._ensure_plan_active(obj, messages, strict=False)
            if apply_flow_via_com:
                self._apply_steady_flow(
                    obj=obj,
                    flow_payload=flow_payload,
                    river_name=river_name,
                    reach_name=reach_name,
                    messages=messages,
                    strict=strict,
                )
            obj.Project_Save()

            try:
                compute_raw = obj.Compute_CurrentPlan(0, None, True)
            except Exception as exc:
                raise HECControllerError(f"Compute_CurrentPlan failed: {exc}") from exc

            ok, nmsg, comp_msgs, blocking_mode = self._parse_compute_result(compute_raw)
            messages.append(f"Compute_CurrentPlan returned: {ok}")
            if comp_msgs:
                messages.extend([f"COMPUTE: {m}" for m in comp_msgs])

            if not ok:
                lowered = [m.lower() for m in comp_msgs]
                if any("overflow" in m for m in lowered):
                    messages.append(
                        "Overflow detected; switching plan to Subcritical Flow and retrying once."
                    )
                    self._set_plan_regime_on_disk(run_dir, "Subcritical Flow")
                    try:
                        obj.Project_Close()
                    except Exception:
                        pass
                    obj.Project_Open(str(project_abs))
                    time.sleep(0.4)
                    try:
                        compute_raw = obj.Compute_CurrentPlan(0, None, True)
                    except Exception as exc:
                        raise HECControllerError(
                            f"Compute_CurrentPlan retry after overflow failed: {exc}"
                        ) from exc
                    ok, nmsg, comp_msgs, blocking_mode = self._parse_compute_result(compute_raw)
                    messages.append(f"Compute overflow-retry returned: {ok}")
                    if comp_msgs:
                        messages.extend([f"COMPUTE(RETRY-OVERFLOW): {m}" for m in comp_msgs])

                if not ok:
                    messages.append(
                        "Compute returned false; retrying once with COM flow/boundary reapplication."
                    )
                    self._apply_steady_flow(
                        obj=obj,
                        flow_payload=flow_payload,
                        river_name=river_name,
                        reach_name=reach_name,
                        messages=messages,
                        strict=False,
                    )
                    try:
                        compute_raw = obj.Compute_CurrentPlan(0, None, True)
                    except Exception as exc:
                        raise HECControllerError(f"Compute_CurrentPlan retry failed: {exc}") from exc
                    ok, nmsg, comp_msgs, blocking_mode = self._parse_compute_result(compute_raw)
                    messages.append(f"Compute flow-retry returned: {ok}")
                    if comp_msgs:
                        messages.extend([f"COMPUTE(RETRY-FLOW): {m}" for m in comp_msgs])

            if strict and not ok:
                raise HECControllerError(
                    "Compute did not complete successfully. "
                    "Review .computeMsgs.txt/.log for missing boundary/flow/geometry inputs."
                )

            current_plan = self._safe_call(obj, "CurrentPlanFile")
            current_geom = self._safe_call(obj, "CurrentGeomFile")
            current_steady = self._safe_call(obj, "CurrentSteadyFile")

            try:
                obj.Project_Save()
            except Exception:
                pass
            try:
                obj.Project_Close()
            except Exception:
                pass

            artifacts = self._collect_output_files(run_dir)
            plans = artifacts["plan_files"]
            hdfs = artifacts["hdf_files"]
            outputs = artifacts["output_files"]
            logs = artifacts["log_files"]

            if strict and not plans:
                raise HECControllerError("No plan file (*.p##) found after compute.")
            if strict and not hdfs and not outputs:
                raise HECControllerError(
                    "No result artifacts (*.p##.hdf or *.o##) found after compute."
                )

            return {
                "success": bool(ok),
                "messages": messages,
                "current_plan": current_plan,
                "current_geom": current_geom,
                "current_steady": current_steady,
                "compute_message_count": nmsg,
                "compute_blocking_mode": bool(blocking_mode),
                "plan_files": plans,
                "hdf_files": hdfs,
                "output_files": outputs,
                "log_files": logs,
                "backend": "com",
            }
        finally:
            try:
                obj.QuitRas()
            except Exception:
                pass
            try:
                os.chdir(original_cwd)
            except Exception:
                pass

    def _apply_steady_flow(
        self,
        obj: object,
        flow_payload: dict[str, object],
        river_name: str,
        reach_name: str,
        messages: list[str],
        strict: bool,
    ) -> None:
        up_q = float(flow_payload["upstream_flow_cms"])
        tr_q = float(flow_payload["tributary_flow_cms"])
        up_station = self._fmt_station(flow_payload.get("upstream_station_hint", 3905.0))
        tr_station = self._fmt_station(flow_payload.get("tributary_station_hint", 2405.0))
        # HEC-RAS COM expects 1-based profile arrays; prepend a dummy element.
        up_arr = [0.0, up_q]
        tr_arr = [0.0, up_q + tr_q]

        try:
            getattr(obj, "SteadyFlow_SetFlow")(river_name, reach_name, up_station, up_arr)
            getattr(obj, "SteadyFlow_SetFlow")(river_name, reach_name, tr_station, tr_arr)
            messages.append(
                "Steady flow set via COM "
                f"(US {up_station}={up_q:.3f} cms, TR {tr_station}={up_q + tr_q:.3f} cms). "
                "Boundary conditions remain file-defined."
            )
        except Exception as exc:
            messages.append(f"Steady flow COM setup warning: {exc}")
            if strict:
                raise HECControllerError(f"Steady flow setup failed: {exc}") from exc

    @staticmethod
    def _set_plan_regime_on_disk(run_dir: Path, regime: str) -> None:
        p01 = run_dir / "Meerlustkloof.p01"
        if not p01.exists():
            return
        text = p01.read_text(encoding="cp1252", errors="ignore")
        lines = [ln.rstrip("\r") for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        regimes = {"Subcritical Flow", "Supercritical Flow", "Mixed Flow"}
        replaced = False
        for i, line in enumerate(lines):
            if line.strip() in regimes:
                lines[i] = regime
                replaced = True
                break
        if not replaced:
            insert_at = 4 if len(lines) >= 4 else len(lines)
            lines.insert(insert_at, regime)
        p01.write_text("\n".join(lines).rstrip() + "\n", encoding="cp1252")

    def _run_controller_script(
        self,
        progid: str,
        run_dir: Path,
        project_file: Path,
        strict: bool,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            ps1 = td_path / "run_hecras.ps1"
            ps1.write_text(self._controller_script(), encoding="utf-8")
            in_json = td_path / "in.json"
            out_json = td_path / "out.json"
            in_json.write_text(
                json.dumps(
                    {
                        "progid": progid,
                        "run_dir": str(run_dir.resolve()),
                        "project_file": str(project_file.resolve()),
                        "strict": bool(strict),
                    }
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
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
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_sec,
            )
            if proc.returncode != 0:
                details = out_json.read_text(encoding="utf-8", errors="ignore") if out_json.exists() else ""
                raise HECControllerError(
                    "HEC-RAS PowerShell COM run failed.\n"
                    f"stdout:\n{proc.stdout}\n"
                    f"stderr:\n{proc.stderr}\n"
                    f"details:\n{details}"
                )
            if not out_json.exists():
                raise HECControllerError("HEC-RAS PowerShell COM run produced no output payload.")
            data = json.loads(out_json.read_text(encoding="utf-8"))
            if not data.get("success", False):
                raise HECControllerError(str(data.get("error", "Unknown PowerShell COM error")))
            return data

    @staticmethod
    def _safe_call(obj: object, method_name: str) -> str:
        try:
            value = getattr(obj, method_name)()
            if value is None:
                return ""
            return str(value).strip()
        except Exception:
            return ""

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
                time.sleep(0.2)
                cur_plan = self._safe_call(obj, "CurrentPlanFile")
                if cur_plan:
                    return

        if strict:
            raise HECControllerError(
                "No current plan active after project open (expected Plan 01/p01)."
            )

    @staticmethod
    def _parse_compute_result(raw: object) -> tuple[bool, int, list[str], bool]:
        if isinstance(raw, tuple):
            ok = bool(raw[0]) if len(raw) > 0 else False
            nmsg = int(raw[1]) if len(raw) > 1 and raw[1] is not None else 0
            msgs = [str(m) for m in raw[2]] if len(raw) > 2 and raw[2] is not None else []
            blocking = bool(raw[3]) if len(raw) > 3 else True
            return ok, nmsg, msgs, blocking
        if isinstance(raw, list):
            ok = bool(raw[0]) if raw else False
            return ok, 0, [], True
        if isinstance(raw, bool):
            return raw, 0, [], True
        if raw is None:
            return False, 0, [], True
        return bool(raw), 0, [], True

    @staticmethod
    def _resolve_ras_exe(ras_exe_path: Path | None) -> Path:
        candidates: list[Path] = []
        if ras_exe_path:
            raw = str(ras_exe_path).strip().strip('"').strip("'")
            if raw and raw not in {".", "./", ".\\"}:
                candidates.append(Path(raw))
        env_path = os.getenv("HEC_RAS_EXE")
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend(
            [
                Path(r"D:\Program Files\HEC\HEC-RAS\6.6\Ras.exe"),
                Path(r"C:\Program Files\HEC\HEC-RAS\6.6\Ras.exe"),
                Path(r"D:\Program Files\HEC\HEC-RAS\6.7\Ras.exe"),
                Path(r"C:\Program Files\HEC\HEC-RAS\6.7\Ras.exe"),
            ]
        )
        for candidate in candidates:
            if (
                candidate
                and candidate.exists()
                and candidate.is_file()
                and candidate.name.lower() == "ras.exe"
            ):
                return candidate.resolve()
        raise HECControllerError(
            "Ras.exe not found. Set hec_ras.ras_exe_path in config/project.yml "
            "or HEC_RAS_EXE environment variable."
        )

    @staticmethod
    def _build_cli_env(run_dir: Path) -> dict[str, str]:
        env = os.environ.copy()
        runtime_root = run_dir / "_hec_runtime"
        local_app = runtime_root / "LocalAppData"
        roaming = runtime_root / "AppData"
        temp_dir = runtime_root / "Temp"
        for path in (local_app, roaming, temp_dir, local_app / "PlotDriver"):
            path.mkdir(parents=True, exist_ok=True)
        env["LOCALAPPDATA"] = str(local_app.resolve())
        env["APPDATA"] = str(roaming.resolve())
        env["TEMP"] = str(temp_dir.resolve())
        env["TMP"] = str(temp_dir.resolve())
        return env

    @staticmethod
    def _clear_readonly(run_dir: Path) -> None:
        subprocess.run(
            ["attrib", "-R", str(run_dir / "*"), "/S", "/D"],
            capture_output=True,
            text=True,
            check=False,
        )

    def _collect_output_files(self, run_dir: Path) -> dict[str, list[str]]:
        plans = sorted(
            [p for p in run_dir.iterdir() if re.search(r"\.p\d\d$", p.name.lower())],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        hdfs = sorted(
            [p for p in run_dir.glob("*.hdf") if self._is_plan_hdf(p)],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        outputs = sorted(
            [p for p in run_dir.iterdir() if re.search(r"\.o\d\d$", p.name.lower())],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        logs = sorted(run_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        return {
            "plan_files": [str(p.resolve()) for p in plans],
            "hdf_files": [str(p.resolve()) for p in hdfs],
            "output_files": [str(p.resolve()) for p in outputs],
            "log_files": [str(p.resolve()) for p in logs],
        }

    @staticmethod
    def _repair_plotdriver_state() -> None:
        try:
            root = Path.home() / "AppData" / "Local" / "PlotDriver"
            root.mkdir(parents=True, exist_ok=True)
            for candidate in root.glob("RasPlotDriver.exe_Url_*"):
                try:
                    (candidate / "1.0.0.0").mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
            error_log = Path("HECRASPlotDriverError.txt")
            if error_log.exists():
                text = error_log.read_text(encoding="utf-8", errors="ignore")
                for match in re.findall(
                    r"([A-Za-z]:\\Users\\[^\\]+\\AppData\\Local\\PlotDriver\\RasPlotDriver\.exe_Url_[^\\]+\\1\.0\.0\.0)",
                    text,
                ):
                    try:
                        Path(match).mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
        except Exception:
            # PlotDriver repairs are best-effort only.
            pass

    @staticmethod
    def _is_plan_hdf(path: Path) -> bool:
        name = path.name.lower()
        if name == "terrain.hdf":
            return False
        if ".g" in name and name.endswith(".hdf"):
            return False
        return ".p" in name and name.endswith(".hdf")

    @staticmethod
    def _fmt_station(value: object) -> str:
        try:
            f = float(value)
        except Exception:
            return str(value).strip()
        if abs(f - round(f)) < 1e-6:
            return str(int(round(f)))
        return f"{f:.3f}"

    @staticmethod
    def _dismiss_ras_dialogs(aggressive: bool = False) -> int:
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
                cls = win32gui.GetClassName(hwnd).strip()
                # Only close modal dialog popups; never close the main RAS frame.
                should_close = title == "RAS"
                if aggressive and title in {"Error", "Restart Plot Process?"}:
                    should_close = True
                if should_close and cls == "#32770":
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
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process Ras,RasProcess -ErrorAction SilentlyContinue | Stop-Process -Force",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _pick_project_file(run_project_dir: Path) -> Path:
        prjs = sorted(run_project_dir.glob("*.prj"), key=lambda p: (p.name.lower(), p.stat().st_size))
        if not prjs:
            raise HECControllerError(f"No .prj found in run project directory: {run_project_dir}")

        non_empty = [p for p in prjs if p.stat().st_size > 0]
        if not non_empty:
            raise HECControllerError(
                f"Only empty .prj files found in run project directory: {run_project_dir}"
            )

        preferred = [p for p in non_empty if p.name.lower() == "meerlustkloof.prj"]
        return preferred[0] if preferred else non_empty[0]

    @staticmethod
    def _pick_plan_file(run_dir: Path, project_file: Path) -> Path:
        preferred_name = ""
        try:
            text = project_file.read_text(encoding="cp1252", errors="ignore")
            for line in text.splitlines():
                if line.startswith("Current Plan="):
                    preferred_name = line.split("=", 1)[1].strip()
                    break
            if not preferred_name:
                for line in text.splitlines():
                    if line.startswith("Plan File="):
                        preferred_name = line.split("=", 1)[1].strip()
                        break
        except Exception:
            preferred_name = ""

        candidates = sorted(
            [p for p in run_dir.iterdir() if re.search(r"\.p\d\d$", p.name.lower()) and p.stat().st_size > 0],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise HECControllerError(f"No non-empty plan file (*.p##) found in {run_dir}")

        if preferred_name:
            for c in candidates:
                if c.suffix.lower() == f".{preferred_name.lower()}":
                    return c
        named = [c for c in candidates if c.name.lower().endswith(".p01")]
        return named[0] if named else candidates[0]

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
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return "OK" in out

    @staticmethod
    def _controller_script() -> str:
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
  Set-Location -Path $payload.run_dir
  [System.Environment]::CurrentDirectory = [string]$payload.run_dir

  $obj = New-Object -ComObject $payload.progid
  try {
    $obj.Project_Open($payload.project_file)
    Start-Sleep -Milliseconds 400
    $curProj = ""
    try { $curProj = $obj.CurrentProjectFile() } catch {}
    if ([string]::IsNullOrWhiteSpace($curProj)) {
      throw "Project_Open did not load a project (CurrentProjectFile empty)."
    }

    $curPlan = ""
    try { $curPlan = $obj.CurrentPlanFile() } catch {}
    if ([string]::IsNullOrWhiteSpace($curPlan)) {
      try { [void]$obj.Plan_SetCurrent("Plan 01") } catch {}
      try { [void]$obj.Plan_SetCurrent("p01") } catch {}
      try { $curPlan = $obj.CurrentPlanFile() } catch {}
      if ([string]::IsNullOrWhiteSpace($curPlan) -and $payload.strict) {
        throw "No current plan active after project open."
      }
    }

    $computeRaw = $obj.Compute_CurrentPlan(0, $null, $true)
    $ok = $false
    $nmsg = 0
    $msgs = @()
    $blocking = $true
    if ($computeRaw -is [array]) {
      if ($computeRaw.Length -ge 1) { $ok = [bool]$computeRaw[0] }
      if ($computeRaw.Length -ge 2) { try { $nmsg = [int]$computeRaw[1] } catch {} }
      if ($computeRaw.Length -ge 3 -and $computeRaw[2]) {
        $msgs = @($computeRaw[2] | ForEach-Object { [string]$_ })
      }
      if ($computeRaw.Length -ge 4) { try { $blocking = [bool]$computeRaw[3] } catch {} }
    } elseif ($computeRaw -is [bool]) {
      $ok = $computeRaw
    } else {
      $ok = [bool]$computeRaw
    }

    $obj.Project_Save()
    try { $obj.Project_Close() } catch {}

    $plans = Get-ChildItem -Path $payload.run_dir -Filter '*.p??' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    $hdfs = Get-ChildItem -Path $payload.run_dir -Filter '*.hdf' -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.p\d\d\.hdf$' } | Sort-Object LastWriteTime -Descending
    $outs = Get-ChildItem -Path $payload.run_dir -Filter '*.o??' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    $logs = Get-ChildItem -Path $payload.run_dir -Filter '*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending

    if ($payload.strict -and (-not $ok)) {
      throw "Compute did not complete successfully."
    }
    if ($payload.strict -and $plans.Count -eq 0) {
      throw "No plan file (*.p##) found after compute."
    }
    if ($payload.strict -and $hdfs.Count -eq 0 -and $outs.Count -eq 0) {
      throw "No result artifacts (*.p##.hdf or *.o##) found after compute."
    }

    $curPlanFile = ""
    $curGeomFile = ""
    $curSteadyFile = ""
    try { $curPlanFile = $obj.CurrentPlanFile() } catch {}
    try { $curGeomFile = $obj.CurrentGeomFile() } catch {}
    try { $curSteadyFile = $obj.CurrentSteadyFile() } catch {}

    Write-Result @{
      success = $true
      messages = @($msgs)
      current_plan = $curPlanFile
      current_geom = $curGeomFile
      current_steady = $curSteadyFile
      compute_message_count = $nmsg
      compute_blocking_mode = $blocking
      plan_files = @($plans | ForEach-Object { $_.FullName })
      hdf_files = @($hdfs | ForEach-Object { $_.FullName })
      output_files = @($outs | ForEach-Object { $_.FullName })
      log_files = @($logs | ForEach-Object { $_.FullName })
    }
  }
  finally {
    if ($null -ne $obj) {
      try { $obj.QuitRas() | Out-Null } catch {}
    }
  }
}
catch {
  Write-Result @{
    success = $false
    error = $_.Exception.Message
    where = $_.InvocationInfo.PositionMessage
    stack = $_.ScriptStackTrace
  }
  exit 1
}
"""

