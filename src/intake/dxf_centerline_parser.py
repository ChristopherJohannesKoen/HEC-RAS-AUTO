from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge


NOISE_LAYERS = {
    "surf2contours",
    "z_titleblock",
    "google image",
    "0",
    "points",
    "cross sections",
    "10 year floodline",
    "100 year floodline",
}

PREFERRED_LAYER_NAMES = {
    "cl",
    "centerline",
    "centreline",
    "river centerline",
    "river centreline",
    "river_centerline",
    "river_centreline",
}


def parse_centerline_dxf(
    dxf_path: Path,
    out_dir: Path = Path("data/processed"),
    excel_centerline_csv: Path | None = None,
) -> Path:
    """
    Extract the best centerline polyline from a CAD DXF and write:
      - data/processed/centerline_from_dxf.geojson
      - data/processed/centerline_from_dxf_debug.json

    Selection favors a layer named CL/Centerline (case-insensitive) and
    geometries near the Excel chainage span when available.
    """
    if not dxf_path.exists():
        raise FileNotFoundError(f"DXF file not found: {dxf_path}")

    gdf = gpd.read_file(dxf_path)
    if gdf.empty:
        raise ValueError(f"DXF contains no features: {dxf_path}")

    layer_col = _find_col(gdf, "layer")
    chainage_hint = _excel_chainage_hint(excel_centerline_csv) if excel_centerline_csv else None

    candidates: list[dict[str, object]] = []
    for idx, geom in enumerate(gdf.geometry):
        line = _as_line_2d(geom)
        if line is None:
            continue
        length = float(line.length)
        if length <= 0:
            continue
        layer = ""
        if layer_col is not None:
            raw = gdf.iloc[idx][layer_col]
            layer = str(raw).strip() if raw is not None else ""
        score = _score_candidate(layer=layer, length=length, chainage_hint=chainage_hint)
        candidates.append(
            {
                "idx": int(idx),
                "layer": layer,
                "length": length,
                "score": float(score),
                "geometry": line,
            }
        )

    if not candidates:
        raise ValueError(f"No line/polyline candidates found in DXF: {dxf_path}")

    candidates.sort(key=lambda c: (float(c["score"]), float(c["length"])), reverse=True)
    chosen = candidates[0]
    line = chosen["geometry"]
    assert isinstance(line, LineString)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_geojson = out_dir / "centerline_from_dxf.geojson"
    out_debug = out_dir / "centerline_from_dxf_debug.json"

    out_gdf = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "source": "dxf_centerline",
                "layer": str(chosen["layer"]),
                "length_m": float(chosen["length"]),
            }
        ],
        geometry=[line],
        crs=None,
    )
    out_gdf.to_file(out_geojson, driver="GeoJSON")

    debug: dict[str, object] = {
        "source_dxf": str(dxf_path),
        "selected_candidate": {
            "idx": int(chosen["idx"]),
            "layer": str(chosen["layer"]),
            "length": float(chosen["length"]),
            "score": float(chosen["score"]),
        },
        "candidate_count": len(candidates),
        "top_candidates": [
            {
                "idx": int(c["idx"]),
                "layer": str(c["layer"]),
                "length": float(c["length"]),
                "score": float(c["score"]),
            }
            for c in candidates[:20]
        ],
    }

    if excel_centerline_csv and excel_centerline_csv.exists():
        fit = _fit_excel_to_reference(excel_centerline_csv=excel_centerline_csv, ref_line=line)
        if fit:
            debug["excel_to_dxf_fit"] = fit

    out_debug.write_text(json.dumps(debug, indent=2), encoding="utf-8")
    return out_geojson


def _find_col(df: gpd.GeoDataFrame, target: str) -> str | None:
    target = target.lower()
    for c in df.columns:
        if str(c).lower() == target:
            return str(c)
    return None


def _excel_chainage_hint(excel_centerline_csv: Path | None) -> float | None:
    if not excel_centerline_csv or not excel_centerline_csv.exists():
        return None
    try:
        df = pd.read_csv(excel_centerline_csv)
    except Exception:
        return None
    if "chainage_m" not in df.columns:
        return None
    ch = pd.to_numeric(df["chainage_m"], errors="coerce").dropna()
    if ch.empty:
        return None
    return float(ch.max() - ch.min())


def _as_line_2d(geom: object) -> LineString | None:
    if geom is None:
        return None
    line: LineString | None = None
    if isinstance(geom, LineString):
        line = geom
    elif isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            line = merged
        elif isinstance(merged, MultiLineString) and len(merged.geoms) > 0:
            line = max(merged.geoms, key=lambda g: g.length)
    if line is None:
        return None

    coords_2d = [(float(c[0]), float(c[1])) for c in line.coords if len(c) >= 2]
    if len(coords_2d) < 2:
        return None
    return LineString(coords_2d)


def _score_candidate(layer: str, length: float, chainage_hint: float | None) -> float:
    lname = layer.strip().lower()
    score = 0.0
    if lname in PREFERRED_LAYER_NAMES:
        score += 1000.0
    if "center" in lname or "centre" in lname:
        score += 700.0
    if lname in NOISE_LAYERS:
        score -= 600.0
    if length > 1000:
        score += 30.0
    if chainage_hint and chainage_hint > 0:
        rel = abs(length - chainage_hint) / chainage_hint
        score += max(0.0, 250.0 - 800.0 * rel)
    score += min(length, 10000.0) / 100.0
    return score


def _fit_excel_to_reference(excel_centerline_csv: Path, ref_line: LineString) -> dict[str, object] | None:
    try:
        df = pd.read_csv(excel_centerline_csv)
    except Exception:
        return None
    if "x" not in df.columns or "y" not in df.columns:
        return None

    df["x"] = pd.to_numeric(df["x"], errors="coerce")
    df["y"] = pd.to_numeric(df["y"], errors="coerce")
    df = df.dropna(subset=["x", "y"]).reset_index(drop=True)
    if len(df) < 3:
        return None

    if "chainage_m" in df.columns:
        df["chainage_m"] = pd.to_numeric(df["chainage_m"], errors="coerce")
        if df["chainage_m"].notna().any():
            df = df.sort_values("chainage_m").reset_index(drop=True)
            ch = df["chainage_m"].to_numpy(dtype=float)
            ch0 = ch - np.nanmin(ch)
            span = float(np.nanmax(ch0)) if np.isfinite(ch0).any() else 0.0
            if span > 0:
                fracs = np.clip(ch0 / span, 0.0, 1.0)
            else:
                fracs = np.linspace(0.0, 1.0, len(df))
        else:
            fracs = np.linspace(0.0, 1.0, len(df))
    else:
        fracs = np.linspace(0.0, 1.0, len(df))

    src = df[["x", "y"]].to_numpy(dtype=float)
    tgt_fwd = np.array(
        [[ref_line.interpolate(float(fr) * ref_line.length).x, ref_line.interpolate(float(fr) * ref_line.length).y] for fr in fracs],
        dtype=float,
    )
    tgt_rev = np.array(
        [
            [
                ref_line.interpolate((1.0 - float(fr)) * ref_line.length).x,
                ref_line.interpolate((1.0 - float(fr)) * ref_line.length).y,
            ]
            for fr in fracs
        ],
        dtype=float,
    )

    fit_fwd = _similarity_fit(src, tgt_fwd)
    fit_rev = _similarity_fit(src, tgt_rev)
    chosen = fit_fwd if fit_fwd["rmse"] <= fit_rev["rmse"] else fit_rev
    chosen["orientation"] = "forward" if fit_fwd["rmse"] <= fit_rev["rmse"] else "reversed"
    chosen["rmse_forward"] = float(fit_fwd["rmse"])
    chosen["rmse_reversed"] = float(fit_rev["rmse"])
    chosen["n_points"] = int(len(src))
    return chosen


def _similarity_fit(src: np.ndarray, dst: np.ndarray) -> dict[str, object]:
    # Umeyama similarity fit: dst ~= s * R * src + t
    n = src.shape[0]
    mu_src = src.mean(axis=0)
    mu_dst = dst.mean(axis=0)
    src_c = src - mu_src
    dst_c = dst - mu_dst

    var_src = np.sum(src_c**2) / n
    if var_src <= 0:
        return {
            "rmse": float("inf"),
            "scale": 1.0,
            "rotation_deg": 0.0,
            "tx": 0.0,
            "ty": 0.0,
        }

    cov = (dst_c.T @ src_c) / n
    u, svals, vt = np.linalg.svd(cov)
    d = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[-1, -1] = -1.0
    r = u @ d @ vt
    scale = float(np.trace(np.diag(svals) @ d) / var_src)
    t = mu_dst - scale * (r @ mu_src)

    pred = (scale * (r @ src.T)).T + t
    rmse = float(np.sqrt(np.mean(np.sum((pred - dst) ** 2, axis=1))))
    theta = float(np.degrees(np.arctan2(r[1, 0], r[0, 0])))
    return {
        "rmse": rmse,
        "scale": scale,
        "rotation_deg": theta,
        "tx": float(t[0]),
        "ty": float(t[1]),
    }
