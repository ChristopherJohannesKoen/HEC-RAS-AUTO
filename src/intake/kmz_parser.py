from __future__ import annotations

import csv
import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point

from src.models import ReferencePoint

logger = logging.getLogger(__name__)


def parse_kmz_point(kmz_path: Path, point_name: str, target_epsg: int) -> ReferencePoint:
    kml_data = _extract_kml_from_kmz(kmz_path)
    lon, lat = _extract_first_coordinate(kml_data)
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{target_epsg}", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return ReferencePoint(
        name=point_name,
        source_file=kmz_path,
        lon=lon,
        lat=lat,
        x=x,
        y=y,
        crs_epsg=target_epsg,
    )


def parse_kmz_map(kmz_points: dict[str, Path], target_epsg: int) -> list[ReferencePoint]:
    parsed: list[ReferencePoint] = []
    for name, path in kmz_points.items():
        if path is None:
            continue
        if not path.exists():
            logger.warning("KMZ path missing for %s: %s", name, path)
            continue
        parsed.append(parse_kmz_point(path, name, target_epsg))
    return parsed


def write_reference_points(points: list[ReferencePoint], out_dir: Path = Path("data/processed")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = out_dir / "reference_points.geojson"
    csv_path = out_dir / "reference_points.csv"

    if not points:
        gpd.GeoDataFrame(columns=["name", "lon", "lat", "x", "y"], geometry=[], crs="EPSG:4326").to_file(
            geojson_path, driver="GeoJSON"
        )
        csv_path.write_text("", encoding="utf-8")
        return

    gdf = gpd.GeoDataFrame(
        [{"name": p.name, "source_file": str(p.source_file), "lon": p.lon, "lat": p.lat, "x": p.x, "y": p.y} for p in points],
        geometry=[Point(p.x, p.y) for p in points],
        crs=f"EPSG:{points[0].crs_epsg}",
    )
    try:
        if geojson_path.exists():
            geojson_path.unlink()
        gdf.to_file(geojson_path, driver="GeoJSON", engine="fiona")
    except PermissionError:
        logger.warning(
            "Could not overwrite %s due to file lock; keeping existing GeoJSON and continuing.",
            geojson_path,
        )

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "source_file", "lon", "lat", "x", "y", "crs_epsg"])
        writer.writeheader()
        for p in points:
            writer.writerow(
                {
                    "name": p.name,
                    "source_file": str(p.source_file),
                    "lon": p.lon,
                    "lat": p.lat,
                    "x": p.x,
                    "y": p.y,
                    "crs_epsg": p.crs_epsg,
                }
            )


def _extract_kml_from_kmz(path: Path) -> bytes:
    with zipfile.ZipFile(path, "r") as zf:
        for member in zf.namelist():
            if member.lower().endswith(".kml"):
                return zf.read(member)
    raise ValueError(f"No KML found inside KMZ: {path}")


def _extract_first_coordinate(kml_data: bytes) -> tuple[float, float]:
    root = ET.fromstring(kml_data)
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    coord_el = root.find(".//kml:Point/kml:coordinates", namespaces=namespace)
    if coord_el is None or coord_el.text is None:
        raise ValueError("Could not find Point coordinates in KMZ/KML")
    raw = coord_el.text.strip().split(",")
    lon = float(raw[0])
    lat = float(raw[1])
    return lon, lat
