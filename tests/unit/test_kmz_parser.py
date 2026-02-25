import zipfile
from pathlib import Path

from src.intake.kmz_parser import parse_kmz_point


def test_parse_kmz_point(tmp_path: Path) -> None:
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>test</name>
      <Point><coordinates>18.5,-33.9,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>
"""
    kmz = tmp_path / "point.kmz"
    with zipfile.ZipFile(kmz, "w") as zf:
        zf.writestr("doc.kml", kml)

    p = parse_kmz_point(kmz, "test", target_epsg=4326)
    assert p.name == "test"
    assert round(p.lon, 1) == 18.5
    assert round(p.lat, 1) == -33.9
