from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ProjectMeta(BaseModel):
    name: str
    river_name: str
    reach_name: str
    target_crs_epsg: int
    units: str = "SI"


class FilesConfig(BaseModel):
    contour_pdf: Optional[Path] = None
    contour_dwg: Optional[Path] = None
    info_xlsx: Path
    terrain_tif: Path
    projection_prj: Path
    centerline_shp: Path


class KmzPointsConfig(BaseModel):
    station_0: Optional[Path] = None
    chainage0_right_bank_floodplain: Path
    chainage0_right_bank_top: Path


class HydraulicsConfig(BaseModel):
    mannings_channel: float
    mannings_floodplain: float
    upstream_q_100: float
    tributary_q_100: float
    tributary_chainage_m: float
    upstream_normal_depth_slope: float
    downstream_normal_depth_slope: float


class HecRasConfig(BaseModel):
    shell_project_dir: Path
    ras_exe_path: Optional[Path] = None
    geometry_import_name: str = "RASImport.sdf"
    preserve_existing_model_inputs: bool = False


class BankBoundaryPoint(BaseModel):
    x: float
    y: float
    z: Optional[float] = None


class BankBoundarySection(BaseModel):
    chainage_m: float
    left_bank: BankBoundaryPoint
    right_bank: BankBoundaryPoint


class BankBoundaryConditionsConfig(BaseModel):
    sections: list[BankBoundarySection] = Field(default_factory=list)
    auto_transform_constraints: bool = False
    snap_constrained_points: bool = False
    enforce_on_chainage_line: bool = True


class ProjectConfig(BaseModel):
    project: ProjectMeta
    files: FilesConfig
    kmz_points: KmzPointsConfig
    hydraulics: HydraulicsConfig
    hec_ras: HecRasConfig
    bank_boundary_conditions: Optional[BankBoundaryConditionsConfig] = None


class TerrainThresholds(BaseModel):
    xs_profile_sample_spacing_m: float = 2.0
    xs_gap_expected_length_m: float = 90.0
    xs_gap_length_tolerance_m: float = 20.0
    max_profile_jump_per_step_m: float = 3.0
    max_nodata_fraction: float = 0.2


class QAThresholds(BaseModel):
    min_cross_sections: int = 8
    max_section_crossing_count: int = 1
    max_velocity_reasonableness_mps: float = 10.0
    max_eg_jump_between_sections_m: float = 5.0
    min_bankfull_width_m: float = 2.0
    max_bank_shift_between_sections_m: float = 50.0


class PlotThresholds(BaseModel):
    longitudinal_chainage_tick_m: int = 500


class ThresholdConfig(BaseModel):
    terrain: TerrainThresholds = Field(default_factory=TerrainThresholds)
    qa: QAThresholds = Field(default_factory=QAThresholds)
    plotting: PlotThresholds = Field(default_factory=PlotThresholds)


class SheetColumns(BaseModel):
    chainage: str
    station: str
    offset: str
    elevation: str
    x: str
    y: str


class ExcelSheetConfig(BaseModel):
    cross_sections_sheet: str
    centerline_sheet: str
    columns: SheetColumns


class SheetsConfig(BaseModel):
    excel: ExcelSheetConfig
