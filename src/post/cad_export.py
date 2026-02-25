from __future__ import annotations

from pathlib import Path

import geopandas as gpd


def export_floodline_dxf(
    floodline_geojson: Path,
    run_id: str,
    output_root: Path = Path("outputs"),
) -> Path:
    out_dir = output_root / run_id / "cad"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dxf = out_dir / "floodlines.dxf"

    gdf = gpd.read_file(floodline_geojson)
    if gdf.empty:
        raise ValueError(f"No geometry found in floodline file: {floodline_geojson}")

    try:
        import ezdxf
    except Exception:
        _write_minimal_dxf(gdf, out_dxf)
        return out_dxf

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    if "FLOODLINE" not in doc.layers:
        doc.layers.new("FLOODLINE")

    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "Polygon":
            coords = list(geom.exterior.coords)
            msp.add_lwpolyline(coords, dxfattribs={"layer": "FLOODLINE", "closed": True})
        elif geom.geom_type == "LineString":
            coords = list(geom.coords)
            msp.add_lwpolyline(coords, dxfattribs={"layer": "FLOODLINE"})
        elif geom.geom_type == "MultiPolygon":
            for poly in geom.geoms:
                coords = list(poly.exterior.coords)
                msp.add_lwpolyline(coords, dxfattribs={"layer": "FLOODLINE", "closed": True})
        elif geom.geom_type == "MultiLineString":
            for line in geom.geoms:
                coords = list(line.coords)
                msp.add_lwpolyline(coords, dxfattribs={"layer": "FLOODLINE"})

    doc.saveas(out_dxf)
    return out_dxf


def _write_minimal_dxf(gdf: gpd.GeoDataFrame, out_dxf: Path) -> None:
    """
    Minimal DXF fallback if ezdxf is not available.
    Writes lightweight polyline entities with basic section formatting.
    """
    lines: list[str] = ["0", "SECTION", "2", "ENTITIES"]
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        geoms = [geom]
        if geom.geom_type.startswith("Multi"):
            geoms = list(geom.geoms)
        for g in geoms:
            if g.geom_type == "Polygon":
                coords = list(g.exterior.coords)
            elif g.geom_type == "LineString":
                coords = list(g.coords)
            else:
                continue
            lines.extend(["0", "LWPOLYLINE", "8", "FLOODLINE", "90", str(len(coords))])
            for x, y, *_ in coords:
                lines.extend(["10", str(float(x)), "20", str(float(y))])
    lines.extend(["0", "ENDSEC", "0", "EOF"])
    out_dxf.write_text("\n".join(lines) + "\n", encoding="utf-8")
