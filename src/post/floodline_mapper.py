from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiPoint, Point, Polygon

logger = logging.getLogger(__name__)


def export_energy_floodline(
    sections_csv: Path,
    run_id: str,
    target_epsg: int,
    profile_values_csv: Path | None = None,
    output_root: Path = Path("outputs"),
) -> Path:
    out_dir = output_root / run_id / "gis"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(sections_csv)
    if df.empty:
        raise ValueError("Sections CSV empty; cannot derive floodline.")

    sections_json = Path("data/processed/cross_sections_final.json")
    features = _build_energy_flood_features(
        sampled_sections=df,
        sections_json=sections_json,
        run_id=run_id,
        profile_values_csv=profile_values_csv,
    )
    if not features:
        # Final fallback: keep deterministic artifact creation even if geometry
        # inputs are incomplete.
        points = list(zip(df["offset_m"], df["energy_level_m"]))
        geom = MultiPoint([(float(x), float(y)) for x, y in points]).convex_hull
        features = [
            {
                "run_id": run_id,
                "type": "energy_flood_envelope_fallback",
                "geometry": geom,
            }
        ]
    gdf = gpd.GeoDataFrame(features, geometry="geometry", crs=f"EPSG:{target_epsg}")
    out_path = out_dir / "energy_floodline.geojson"
    try:
        gdf.to_file(out_path, driver="GeoJSON")
        return out_path
    except PermissionError:
        fallback = _next_available_geojson_path(out_path)
        logger.warning(
            "Could not overwrite %s (likely file lock); writing floodline to fallback path %s",
            out_path,
            fallback,
        )
        gdf.to_file(fallback, driver="GeoJSON")
        return fallback


def _build_energy_flood_features(
    sampled_sections: pd.DataFrame,
    sections_json: Path,
    run_id: str,
    profile_values_csv: Path | None = None,
) -> list[dict[str, object]]:
    if not sections_json.exists():
        logger.warning("Missing %s; cannot build map-space floodline.", sections_json)
        return []

    try:
        sections_payload = json.loads(sections_json.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", sections_json, exc)
        return []

    if not isinstance(sections_payload, list) or not sections_payload:
        return []

    sampled = _prepare_energy_samples(sampled_sections, profile_values_csv)
    if sampled.empty:
        return []

    left_pts: list[tuple[float, float]] = []
    right_pts: list[tuple[float, float]] = []
    rows: list[dict[str, object]] = []

    for _, row in sampled.iterrows():
        chainage = float(row["chainage_m"])
        energy = float(row["energy_level_m"])
        sec = _nearest_section_payload(sections_payload, chainage)
        if sec is None:
            continue

        cutline = sec.get("cutline")
        points = sec.get("points")
        if not isinstance(cutline, list) or len(cutline) != 2:
            continue
        if not isinstance(points, list) or len(points) < 2:
            continue

        profile = _profile_dataframe(points)
        if profile.empty:
            continue
        left_bank = _safe_float(sec.get("left_bank_station"))
        right_bank = _safe_float(sec.get("right_bank_station"))
        if left_bank is None or right_bank is None:
            continue

        left_off = _find_flood_edge_offset(profile, bank_offset=left_bank, energy=energy, side="left")
        right_off = _find_flood_edge_offset(profile, bank_offset=right_bank, energy=energy, side="right")
        if left_off is None or right_off is None:
            continue

        left_xy = _offset_to_cutline_xy(profile, cutline, left_off)
        right_xy = _offset_to_cutline_xy(profile, cutline, right_off)
        if left_xy is None or right_xy is None:
            continue

        left_pts.append(left_xy)
        right_pts.append(right_xy)
        rows.append(
            {
                "run_id": run_id,
                "type": "energy_flood_section_edges",
                "chainage_m": chainage,
                "energy_level_m": energy,
                "left_edge_offset_m": float(left_off),
                "right_edge_offset_m": float(right_off),
                "geometry": LineString([left_xy, right_xy]),
            }
        )

    features: list[dict[str, object]] = []
    if len(left_pts) >= 2:
        features.append(
            {
                "run_id": run_id,
                "type": "energy_flood_edge_left",
                "geometry": LineString(left_pts),
            }
        )
    if len(right_pts) >= 2:
        features.append(
            {
                "run_id": run_id,
                "type": "energy_flood_edge_right",
                "geometry": LineString(right_pts),
            }
        )

    if len(left_pts) >= 2 and len(right_pts) >= 2:
        ring = left_pts + list(reversed(right_pts))
        try:
            envelope = Polygon(ring)
            if not envelope.is_valid:
                envelope = envelope.buffer(0)
            if envelope.is_empty:
                envelope = MultiPoint(ring).convex_hull
        except Exception:
            envelope = MultiPoint(ring).convex_hull
        features.append(
            {
                "run_id": run_id,
                "type": "energy_flood_envelope",
                "geometry": envelope,
            }
        )

    features.extend(rows)
    return features


def _prepare_energy_samples(
    sampled_sections: pd.DataFrame,
    profile_values_csv: Path | None,
) -> pd.DataFrame:
    # Prefer full HDF profile values when available; this creates a flood envelope
    # along the full model reach instead of only the report-required chainages.
    if profile_values_csv and profile_values_csv.exists():
        try:
            prof = pd.read_csv(profile_values_csv)
        except Exception:
            prof = pd.DataFrame()
        if not prof.empty and {"chainage_m", "energy_level_m"}.issubset(prof.columns):
            prof = prof.copy()
            prof["chainage_m"] = pd.to_numeric(prof["chainage_m"], errors="coerce")
            prof["energy_level_m"] = pd.to_numeric(prof["energy_level_m"], errors="coerce")
            prof = prof.dropna(subset=["chainage_m", "energy_level_m"])
            if not prof.empty:
                return (
                    prof.groupby("chainage_m", as_index=False)["energy_level_m"]
                    .median()
                    .sort_values("chainage_m")
                )
    return (
        sampled_sections.groupby("chainage_m", as_index=False)["energy_level_m"]
        .median()
        .sort_values("chainage_m")
    )


def _nearest_section_payload(sections_payload: list[dict], target_chainage: float) -> dict | None:
    best: dict | None = None
    best_err = float("inf")
    for sec in sections_payload:
        ch = _safe_float(sec.get("chainage_m"))
        if ch is None:
            continue
        err = abs(ch - target_chainage)
        if err < best_err:
            best_err = err
            best = sec
    return best


def _profile_dataframe(points: list[dict]) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for p in points:
        station = _safe_float(p.get("station"))
        elev = _safe_float(p.get("elevation"))
        if station is None or elev is None:
            continue
        rows.append({"offset_m": station, "elevation_m": elev})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("offset_m").reset_index(drop=True)


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _interp_elevation(profile: pd.DataFrame, offset: float) -> float:
    x = profile["offset_m"].to_numpy(dtype=float)
    y = profile["elevation_m"].to_numpy(dtype=float)
    if offset <= x[0]:
        return float(y[0])
    if offset >= x[-1]:
        return float(y[-1])
    idx = int((x <= offset).sum() - 1)
    x0, x1 = float(x[idx]), float(x[idx + 1])
    y0, y1 = float(y[idx]), float(y[idx + 1])
    if abs(x1 - x0) < 1e-9:
        return y0
    t = (offset - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _interp_crossing_offset(
    x0: float,
    z0: float,
    x1: float,
    z1: float,
    z_target: float,
) -> float:
    if abs(z1 - z0) < 1e-9:
        return x0
    t = (z_target - z0) / (z1 - z0)
    t = max(0.0, min(1.0, t))
    return x0 + t * (x1 - x0)


def _find_flood_edge_offset(
    profile: pd.DataFrame,
    bank_offset: float,
    energy: float,
    side: str,
) -> float | None:
    if profile.empty:
        return None

    offsets = profile["offset_m"].to_numpy(dtype=float)
    elevs = profile["elevation_m"].to_numpy(dtype=float)
    if len(offsets) < 2:
        return None

    current_off = float(bank_offset)
    current_elev = float(_interp_elevation(profile, current_off))
    had_wet = current_elev <= energy

    if side == "left":
        outward = profile.loc[profile["offset_m"] < bank_offset].sort_values("offset_m", ascending=False)
        terminal_offset = float(offsets.min())
    else:
        outward = profile.loc[profile["offset_m"] > bank_offset].sort_values("offset_m", ascending=True)
        terminal_offset = float(offsets.max())

    if outward.empty:
        return current_off

    for _, row in outward.iterrows():
        nxt_off = float(row["offset_m"])
        nxt_elev = float(row["elevation_m"])
        if (current_elev <= energy <= nxt_elev) or (current_elev >= energy >= nxt_elev):
            return _interp_crossing_offset(current_off, current_elev, nxt_off, nxt_elev, energy)
        if nxt_elev <= energy:
            had_wet = True
        current_off, current_elev = nxt_off, nxt_elev

    if had_wet:
        return terminal_offset
    return bank_offset


def _offset_to_cutline_xy(
    profile: pd.DataFrame,
    cutline: list[list[float]],
    offset: float,
) -> tuple[float, float] | None:
    try:
        (x0, y0), (x1, y1) = cutline
    except Exception:
        return None

    off_min = float(profile["offset_m"].min())
    off_max = float(profile["offset_m"].max())
    if abs(off_max - off_min) < 1e-9:
        return ((float(x0) + float(x1)) / 2.0, (float(y0) + float(y1)) / 2.0)
    t = (float(offset) - off_min) / (off_max - off_min)
    t = max(0.0, min(1.0, t))
    x = float(x0) + t * (float(x1) - float(x0))
    y = float(y0) + t * (float(y1) - float(y0))
    return (x, y)


def _next_available_geojson_path(base_path: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    candidate = base_path.with_name(f"{base_path.stem}_{ts}{base_path.suffix}")
    idx = 1
    while candidate.exists():
        candidate = base_path.with_name(f"{base_path.stem}_{ts}_{idx}{base_path.suffix}")
        idx += 1
    return candidate
