from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

from src.models import ProjectConfig
from src.ras.controller_adapter import HECRASControllerAdapter, HECControllerError


def run_doctor_checks(config: ProjectConfig) -> dict[str, object]:
    checks: dict[str, object] = {}
    checks["python_version"] = sys.version
    checks["python_ok"] = sys.version_info >= (3, 11)

    dep_map = {
        "pandas": "pandas",
        "numpy": "numpy",
        "geopandas": "geopandas",
        "rasterio": "rasterio",
        "h5py": "h5py",
        "jinja2": "jinja2",
        "tabulate": "tabulate",
        "ezdxf": "ezdxf",
        "openai": "openai",
        "pywin32": "win32com.client",
        "comtypes": "comtypes",
    }
    checks["dependencies"] = {
        label: _module_available(module_name)
        for label, module_name in dep_map.items()
    }
    checks["openai_key_set"] = bool(os.getenv("OPENAI_API_KEY"))

    checks["required_files"] = {
        "info_xlsx": config.files.info_xlsx.exists(),
        "terrain_tif": config.files.terrain_tif.exists(),
        "projection_prj": config.files.projection_prj.exists(),
        "centerline_shp": config.files.centerline_shp.exists(),
        "kmz_floodplain": config.kmz_points.chainage0_right_bank_floodplain.exists(),
        "kmz_top": config.kmz_points.chainage0_right_bank_top.exists(),
    }

    checks["shell_project_exists"] = config.hec_ras.shell_project_dir.exists()
    checks["shell_has_prj"] = any(config.hec_ras.shell_project_dir.glob("*.prj"))
    try:
        checks["ras_exe"] = str(HECRASControllerAdapter._resolve_ras_exe(config.hec_ras.ras_exe_path))
    except HECControllerError:
        checks["ras_exe"] = ""

    checks["com"] = {
        "RAS67.HECRASController": _com_available("RAS67.HECRASController"),
        "RAS66.HECRASController": _com_available("RAS66.HECRASController"),
    }
    checks["ras_process_count"] = _ras_process_count()

    return checks


def summarize_doctor(checks: dict[str, object]) -> str:
    lines = ["# Doctor Report", ""]
    lines.append(f"- Python OK: {checks.get('python_ok')}")
    lines.append(f"- OpenAI key set: {checks.get('openai_key_set')}")
    lines.append(f"- Shell project exists: {checks.get('shell_project_exists')}")
    lines.append(f"- Shell has .prj: {checks.get('shell_has_prj')}")
    lines.append(f"- Ras.exe: {checks.get('ras_exe') or 'NOT FOUND'}")
    lines.append(f"- Running Ras.exe count: {checks.get('ras_process_count')}")
    lines.append("")
    lines.append("## Dependencies")
    deps = checks.get("dependencies", {})
    for name, ok in sorted(deps.items()):
        lines.append(f"- {name}: {ok}")
    lines.append("")
    lines.append("## COM")
    com = checks.get("com", {})
    for name, ok in com.items():
        lines.append(f"- {name}: {ok}")
    lines.append("")
    lines.append("## Required Files")
    req = checks.get("required_files", {})
    for name, ok in req.items():
        lines.append(f"- {name}: {ok}")
    return "\n".join(lines) + "\n"


def _com_available(progid: str) -> bool:
    script = (
        f"$obj=$null; try {{$obj=New-Object -ComObject '{progid}'; 'OK'}} "
        "catch {'FAIL'} finally { if($obj -ne $null){ try{$obj.QuitRas()|Out-Null}catch{} } }"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    return "OK" in (proc.stdout or "")


def _ras_process_count() -> int:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Process Ras -ErrorAction SilentlyContinue | Measure-Object | % Count"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return int((proc.stdout or "").strip() or "0")
    except ValueError:
        return 0


def _module_available(module_name: str) -> bool:
    try:
        return bool(importlib.util.find_spec(module_name))
    except ModuleNotFoundError:
        return False
