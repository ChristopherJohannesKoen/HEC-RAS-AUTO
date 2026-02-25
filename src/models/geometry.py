from __future__ import annotations

from pathlib import Path
from typing import Optional
from typing import Literal

from pydantic import BaseModel, Field


class ReferencePoint(BaseModel):
    name: str
    source_file: Path
    lon: float
    lat: float
    x: float
    y: float
    crs_epsg: int


class SectionPoint(BaseModel):
    station: float
    elevation: float
    source: Literal["excel", "terrain_fill", "interpolated", "manual_override"] = "excel"


class CrossSection(BaseModel):
    chainage_m: float
    river_station: float
    reach_name: str
    river_name: str
    cutline: list[tuple[float, float]]
    points: list[SectionPoint]
    left_bank_station: float
    right_bank_station: float
    mannings_left: float
    mannings_channel: float
    mannings_right: float
    reach_length_left: Optional[float] = None
    reach_length_channel: Optional[float] = None
    reach_length_right: Optional[float] = None
    provenance: list[str] = Field(default_factory=list)
    confidence: float = 1.0
