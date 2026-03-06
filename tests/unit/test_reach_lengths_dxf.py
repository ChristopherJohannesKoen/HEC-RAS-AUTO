from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from src.models.geometry import CrossSection, SectionPoint
from src.xs.reach_lengths import assign_reach_lengths


def _make_section(chainage: float, y: float) -> CrossSection:
    return CrossSection(
        chainage_m=chainage,
        river_station=3905.0 - chainage,
        river_name="R",
        reach_name="Main",
        cutline=[(-10.0, y), (10.0, y)],
        points=[
            SectionPoint(station=-10.0, elevation=10.0, source="excel"),
            SectionPoint(station=10.0, elevation=11.0, source="excel"),
        ],
        left_bank_station=-8.0,
        right_bank_station=8.0,
        mannings_left=0.06,
        mannings_channel=0.04,
        mannings_right=0.06,
    )


def test_assign_reach_lengths_uses_dxf_contours(tmp_path: Path) -> None:
    centerline_path = tmp_path / "centerline.geojson"
    dxf_like_path = tmp_path / "contours.geojson"

    centerline = gpd.GeoDataFrame(
        [{"id": 1}],
        geometry=[LineString([(0.0, 0.0), (0.0, 1000.0)])],
        crs=None,
    )
    centerline.to_file(centerline_path, driver="GeoJSON")

    contours = gpd.GeoDataFrame(
        [{"Layer": "SURF2CONTOURS"}, {"Layer": "SURF2CONTOURS"}],
        geometry=[
            LineString([(-20.0, 0.0), (-50.0, 500.0), (-20.0, 1000.0)]),
            LineString([(20.0, 0.0), (50.0, 500.0), (20.0, 1000.0)]),
        ],
        crs=None,
    )
    contours.to_file(dxf_like_path, driver="GeoJSON")

    sections = [_make_section(0.0, 0.0), _make_section(500.0, 500.0), _make_section(1000.0, 1000.0)]
    out = assign_reach_lengths(
        sections,
        dxf_path=dxf_like_path,
        centerline_geojson=centerline_path,
    )

    assert out[0].reach_length_left is not None
    assert out[0].reach_length_right is not None
    assert out[1].reach_length_left is not None
    assert out[1].reach_length_right is not None
    # Contour-guided routing should differ from the simple fixed 500 m
    # chainage delta on at least one bank side.
    assert abs(float(out[0].reach_length_left) - 500.0) > 0.1 or abs(float(out[0].reach_length_right) - 500.0) > 0.1
    assert abs(float(out[1].reach_length_left) - 500.0) > 0.1 or abs(float(out[1].reach_length_right) - 500.0) > 0.1
    assert out[2].reach_length_channel == 0.0


def test_assign_reach_lengths_writes_diagnostic_dxf(tmp_path: Path) -> None:
    centerline_path = tmp_path / "centerline.geojson"
    dxf_like_path = tmp_path / "contours.geojson"
    diagnostic_dxf = tmp_path / "bank_paths_debug.dxf"
    debug_json = tmp_path / "reach_lengths_debug.json"

    centerline = gpd.GeoDataFrame(
        [{"id": 1}],
        geometry=[LineString([(0.0, 0.0), (0.0, 1000.0)])],
        crs=None,
    )
    centerline.to_file(centerline_path, driver="GeoJSON")

    contours = gpd.GeoDataFrame(
        [{"Layer": "SURF2CONTOURS"}, {"Layer": "SURF2CONTOURS"}],
        geometry=[
            LineString([(-20.0, 0.0), (-50.0, 500.0), (-20.0, 1000.0)]),
            LineString([(20.0, 0.0), (50.0, 500.0), (20.0, 1000.0)]),
        ],
        crs=None,
    )
    contours.to_file(dxf_like_path, driver="GeoJSON")

    sections = [_make_section(0.0, 0.0), _make_section(500.0, 500.0), _make_section(1000.0, 1000.0)]
    _ = assign_reach_lengths(
        sections,
        dxf_path=dxf_like_path,
        centerline_geojson=centerline_path,
        debug_path=debug_json,
        diagnostic_dxf_path=diagnostic_dxf,
    )

    assert diagnostic_dxf.exists()
    payload = json.loads(debug_json.read_text(encoding="utf-8"))
    assert "diagnostic_dxf" in payload
    assert payload["diagnostic_dxf"]["path"] == str(diagnostic_dxf)
