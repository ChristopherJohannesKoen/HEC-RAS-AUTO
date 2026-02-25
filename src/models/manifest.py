from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ProjectManifest(BaseModel):
    project_name: str
    raw_dir: Path
    target_crs_epsg: int
    files: dict[str, Path]
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    hash_map: dict[str, str]
    notes: list[str] = Field(default_factory=list)
