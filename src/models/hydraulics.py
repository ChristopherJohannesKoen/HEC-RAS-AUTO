from __future__ import annotations

from pathlib import Path
from typing import Optional
from typing import Literal

from pydantic import BaseModel


class BoundaryCondition(BaseModel):
    location: Literal["upstream", "downstream", "internal"]
    bc_type: Literal["flow", "normal_depth", "lateral_inflow"]
    river_station: Optional[float] = None
    value: float
    slope: Optional[float] = None


class RunArtifacts(BaseModel):
    run_id: str
    run_dir: Path
    ras_project_dir: Path
    sdf_path: Path
    geometry_csv: Path
    flow_json: Path
    hdf_path: Optional[Path] = None
    output_log: Optional[Path] = None
