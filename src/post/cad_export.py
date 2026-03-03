from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Iterator

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


def export_floodline_dxf(
    floodline_geojson: Path,
    run_id: str,
    output_root: Path = Path("outputs"),
    reference_centerline_geojson: Path | None = None,
) -> Path:
    out_dir = output_root / run_id / "cad"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dxf = out_dir / "floodlines.dxf"

    flood_gdf = gpd.read_file(floodline_geojson)
    if flood_gdf.empty:
        raise ValueError(f"No geometry found in floodline file: {floodline_geojson}")

    flood_gdf = _set_layer(flood_gdf, "FLOODLINE")
    frames: list[gpd.GeoDataFrame] = [flood_gdf]

    centerline_info = _load_reference_centerline(reference_centerline_geojson)
    if centerline_info is not None:
        centerline_gdf, source_path = centerline_info
        centerline_gdf = _align_to_target_crs(centerline_gdf, flood_gdf.crs)
        frames.append(_set_layer(centerline_gdf, "CENTERLINE_REF"))
        logger.info("Including reference centerline in CAD export: %s", source_path)

    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=flood_gdf.crs)

    try:
        import ezdxf
    except Exception:
        logger.warning(
            "ezdxf is not available; using minimal DXF fallback writer for %s. "
            "Install ezdxf for richer CAD export.",
            out_dxf,
        )
        return _write_minimal_dxf(gdf, out_dxf)

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    _ensure_layer(doc, "FLOODLINE", color=1)
    _ensure_layer(doc, "CENTERLINE_REF", color=3)

    for geom, layer in _iter_layered_geometries(gdf):
        if geom.geom_type == "Polygon":
            coords = _clean_2d_coords(list(geom.exterior.coords))
            if len(coords) >= 3:
                msp.add_lwpolyline(coords, dxfattribs={"layer": layer, "closed": True})
        elif geom.geom_type == "LineString":
            coords = _clean_2d_coords(list(geom.coords))
            if len(coords) >= 2:
                msp.add_lwpolyline(coords, dxfattribs={"layer": layer})

    try:
        doc.saveas(out_dxf)
        return out_dxf
    except PermissionError:
        fallback = _next_available_dxf_path(out_dxf)
        logger.warning(
            "Could not overwrite %s (likely file lock); writing CAD output to fallback path %s",
            out_dxf,
            fallback,
        )
        doc.saveas(fallback)
        return fallback


def _write_minimal_dxf(gdf: gpd.GeoDataFrame, out_dxf: Path) -> Path:
    """
    DXF fallback if ezdxf is not available.
    Writes a conservative AC1009/R12-style DXF with POLYLINE entities,
    which is broadly supported by CAD viewers.
    """
    layer_names = sorted({layer for _, layer in _iter_layered_geometries(gdf)} or {"FLOODLINE"})
    lines: list[str] = [
        "0",
        "SECTION",
        "2",
        "HEADER",
        "9",
        "$ACADVER",
        "1",
        "AC1009",
        "0",
        "ENDSEC",
        "0",
        "SECTION",
        "2",
        "TABLES",
        "0",
        "TABLE",
        "2",
        "LAYER",
        "70",
        str(len(layer_names)),
    ]
    for layer in layer_names:
        lines.extend(
            [
                "0",
                "LAYER",
                "2",
                layer,
                "70",
                "0",
                "62",
                str(_layer_color(layer)),
                "6",
                "CONTINUOUS",
            ]
        )
    lines.extend(["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"])

    for geom, layer in _iter_layered_geometries(gdf):
        if geom.geom_type == "Polygon":
            parts = [(list(geom.exterior.coords), True)]
        elif geom.geom_type == "LineString":
            parts = [(list(geom.coords), False)]
        else:
            continue

        for coords, closed in parts:
            clean_coords = _clean_2d_coords(coords)
            if len(clean_coords) < 2:
                continue
            if closed and clean_coords[0] == clean_coords[-1]:
                clean_coords = clean_coords[:-1]
            if len(clean_coords) < 2:
                continue
            lines.extend(["0", "POLYLINE", "8", layer, "66", "1", "70", "1" if closed else "0"])
            for x, y in clean_coords:
                lines.extend(
                    [
                        "0",
                        "VERTEX",
                        "8",
                        layer,
                        "10",
                        f"{x:.6f}",
                        "20",
                        f"{y:.6f}",
                        "30",
                        "0.0",
                    ]
                )
            lines.extend(["0", "SEQEND"])
    lines.extend(["0", "ENDSEC", "0", "EOF"])

    payload = "\n".join(lines) + "\n"
    try:
        out_dxf.write_text(payload, encoding="ascii", errors="ignore")
        return out_dxf
    except PermissionError:
        fallback = _next_available_dxf_path(out_dxf)
        logger.warning(
            "Could not overwrite %s (likely file lock); writing CAD output to fallback path %s",
            out_dxf,
            fallback,
        )
        fallback.write_text(payload, encoding="ascii", errors="ignore")
        return fallback


def _set_layer(gdf: gpd.GeoDataFrame, layer_name: str) -> gpd.GeoDataFrame:
    out = gdf.copy()
    out["_cad_layer"] = layer_name
    return out


def _align_to_target_crs(gdf: gpd.GeoDataFrame, target_crs: object) -> gpd.GeoDataFrame:
    if target_crs is None:
        return gdf
    if gdf.crs is None:
        return gdf.set_crs(target_crs, allow_override=True)
    if str(gdf.crs) == str(target_crs):
        return gdf

    if _looks_like_projected_xy(gdf):
        logger.warning(
            "Reference centerline CRS appears mislabeled (%s); overriding to match target CRS %s.",
            gdf.crs,
            target_crs,
        )
        return gdf.set_crs(target_crs, allow_override=True)

    try:
        return gdf.to_crs(target_crs)
    except Exception:
        logger.warning(
            "Could not transform centerline CRS %s to %s; overriding CRS to target.",
            gdf.crs,
            target_crs,
        )
        return gdf.set_crs(target_crs, allow_override=True)


def _load_reference_centerline(
    reference_centerline_geojson: Path | None,
) -> tuple[gpd.GeoDataFrame, Path] | None:
    candidates: list[Path] = []
    if reference_centerline_geojson is not None:
        candidates.append(reference_centerline_geojson)
    candidates.extend(
        [
            Path("data/processed/centerline_from_dxf.geojson"),
            Path("data/processed/centerline_from_excel.geojson"),
            Path("data/processed/centerline_from_shp.geojson"),
        ]
    )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            continue
        try:
            gdf = gpd.read_file(candidate)
        except Exception:
            continue
        if gdf.empty:
            continue
        line_like = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])]
        if line_like.empty:
            continue
        return line_like, candidate
    return None


def _iter_layered_geometries(gdf: gpd.GeoDataFrame) -> Iterator[tuple[object, str]]:
    layer_col = "_cad_layer" if "_cad_layer" in gdf.columns else None
    for idx, geom in enumerate(gdf.geometry):
        if geom is None or geom.is_empty:
            continue
        layer = "FLOODLINE"
        if layer_col is not None:
            raw_layer = gdf.iloc[idx][layer_col]
            if raw_layer is not None and str(raw_layer).strip():
                layer = str(raw_layer).strip()

        parts = [geom]
        if geom.geom_type.startswith("Multi"):
            parts = list(geom.geoms)

        for part in parts:
            if part is None or part.is_empty:
                continue
            if part.geom_type not in {"Polygon", "LineString"}:
                continue
            yield part, layer


def _ensure_layer(doc: object, name: str, color: int) -> None:
    try:
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": color})
    except Exception:
        pass


def _layer_color(layer: str) -> int:
    if layer.upper() == "CENTERLINE_REF":
        return 3
    return 1


def _looks_like_projected_xy(gdf: gpd.GeoDataFrame) -> bool:
    try:
        xmin, ymin, xmax, ymax = gdf.total_bounds.tolist()
    except Exception:
        return False
    return any(abs(v) > 500.0 for v in (xmin, ymin, xmax, ymax))


def _clean_2d_coords(coords: list[tuple[float, ...]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for raw in coords:
        if len(raw) < 2:
            continue
        x = float(raw[0])
        y = float(raw[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        out.append((x, y))
    return out


def _next_available_dxf_path(base_path: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    candidate = base_path.with_name(f"{base_path.stem}_{ts}{base_path.suffix}")
    idx = 1
    while candidate.exists():
        candidate = base_path.with_name(f"{base_path.stem}_{ts}_{idx}{base_path.suffix}")
        idx += 1
    return candidate
