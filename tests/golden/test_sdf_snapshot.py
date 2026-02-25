import json
from pathlib import Path

from src.ras.sdf_writer import write_rasimport_sdf


def test_sdf_snapshot(tmp_path: Path) -> None:
    fixture = Path("data/fixtures/cross_sections_fixture.json")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    src = tmp_path / "sections.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "RASImport.sdf"
    write_rasimport_sdf(src, out, river_name="Meerlustkloof", reach_name="Main")
    txt = out.read_text(encoding="utf-8")
    assert "BEGIN HEADER:" in txt
    assert "STREAM ID: Meerlustkloof" in txt
    assert "RIVER STATION: 3905.0" in txt
