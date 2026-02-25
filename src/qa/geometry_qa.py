from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString

from src.geo.geometry_ops import section_intersects_reach_once, sections_cross
from src.models import QAIssue


def run_geometry_qa(
    sections_json: Path,
    centerline_geojson: Path,
    min_sections: int = 2,
) -> list[QAIssue]:
    issues: list[QAIssue] = []
    sections = json.loads(sections_json.read_text(encoding="utf-8"))
    if not sections:
        return [QAIssue(severity="error", code="NO_SECTIONS", message="No cross-sections generated.")]

    if len(sections) < min_sections:
        issues.append(
            QAIssue(
                severity="error",
                code="SECTION_COUNT_LOW",
                message=(
                    f"Only {len(sections)} cross-sections generated; expected at least {min_sections}."
                ),
            )
        )

    chainages = [float(s["chainage_m"]) for s in sections]
    if chainages != sorted(chainages):
        issues.append(
            QAIssue(severity="error", code="CHAINAGE_ORDER", message="Cross-sections are not sorted by chainage.")
        )

    centerline = _load_first_linestring(centerline_geojson)
    cutlines = []
    for idx, sec in enumerate(sections):
        cut = LineString(sec["cutline"])
        cutlines.append(cut)
        if not section_intersects_reach_once(cut, centerline):
            issues.append(
                QAIssue(
                    severity="error",
                    code="CUTLINE_INTERSECTION",
                    message=f"Section at index {idx} does not intersect centerline exactly once.",
                )
            )
        if sec["left_bank_station"] >= sec["right_bank_station"]:
            issues.append(
                QAIssue(
                    severity="error",
                    code="BANK_ORDER",
                    message=f"Invalid bank order at chainage {sec['chainage_m']}",
                )
            )

    for i in range(len(cutlines)):
        for j in range(i + 1, len(cutlines)):
            if sections_cross(cutlines[i], cutlines[j]):
                issues.append(
                    QAIssue(
                        severity="error",
                        code="SECTION_CROSSING",
                        message=f"Cross-sections intersect each other at indices {i} and {j}.",
                    )
                )

    if not issues:
        issues.append(QAIssue(severity="info", code="GEOM_QA_OK", message="Geometry QA passed."))
    return issues


def _load_first_linestring(path: Path) -> LineString:
    import geopandas as gpd

    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Empty centerline file: {path}")
    geom = gdf.geometry.iloc[0]
    return LineString(geom)
