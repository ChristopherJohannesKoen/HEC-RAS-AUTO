from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml


def build_scenario2_triad_report(
    base_run_id: str,
    tier_runs: dict[str, str],
    profile_config: Path = Path("config/scenarios/scenario_2_climate_profiles.yml"),
    outputs_root: Path = Path("outputs"),
    runs_root: Path = Path("runs"),
) -> Path:
    reports_dir = outputs_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{base_run_id}_scenario_2_triad_report_draft.md"

    prof = _load_profile_config(profile_config)
    comparison_csv = outputs_root / base_run_id / "comparison" / "scenario2_tier_comparison.csv"
    envelope_csv = outputs_root / base_run_id / "comparison" / "scenario2_tier_envelope.csv"
    overlay_png = outputs_root / base_run_id / "comparison" / "scenario2_tier_overlay_profile.png"

    comp_md = _read_csv_markdown(comparison_csv)
    env_md = _read_csv_markdown(envelope_csv)
    flow_md = _tier_flow_table_markdown(tier_runs=tier_runs, runs_root=runs_root)
    refs_md = _refs_markdown(prof.get("references", []))
    assumptions_md = _bullet_list(prof.get("assumptions", []))
    limits_md = _bullet_list(prof.get("limitations", []))

    lines: list[str] = [
        f"# {base_run_id.upper()} Scenario 2 Triad Report Draft",
        "",
        "## Scenario Definition",
        f"- Primary tier: `{prof.get('primary_tier', 'average')}`",
        f"- Tier order: `{', '.join(_safe_list(prof.get('tier_order', [])))}`",
        "",
        "## Physical Mechanism",
        str(prof.get("physical_mechanism", "")).strip()
        or "Climate intensification is represented by increasing design-event forcing.",
        "",
        "## Tier Flow Inputs",
        flow_md,
        "",
        "## Tier Comparison Matrix (Baseline vs Scenario 2 Tiers)",
        comp_md,
        "",
        "## Tier Envelope Summary",
        env_md,
        "",
        "## Hydraulic Mechanism Interpretation",
        (
            "Higher design discharges increase stage and energy gradients, but response is non-uniform by section "
            "because confinement, floodplain activation, and confluence interactions alter conveyance and losses. "
            "Conservative forcing should amplify confluence effects at chainage ~1500 m and expand flood extent most strongly."
        ),
        "",
        "## Assumptions",
        assumptions_md,
        "",
        "## Limitations",
        limits_md,
        "",
        "## Key Artifacts",
        f"- Triad comparison CSV: `{comparison_csv}`",
        f"- Triad envelope CSV: `{envelope_csv}`",
        f"- Triad overlay profile plot: `{overlay_png}`",
        "",
        "## References",
        refs_md,
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _load_profile_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_csv_markdown(path: Path) -> str:
    if not path.exists():
        return "_Missing comparison artifact._"
    try:
        df = pd.read_csv(path)
    except Exception:
        return "_Could not parse comparison artifact._"
    if df.empty:
        return "_Comparison artifact exists but has no rows._"
    try:
        return df.to_markdown(index=False)
    except Exception:
        cols = [str(c) for c in df.columns]
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, row in df.iterrows():
            vals = [str(row[c]) for c in df.columns]
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines)


def _tier_flow_table_markdown(tier_runs: dict[str, str], runs_root: Path) -> str:
    rows: list[dict[str, object]] = []
    for tier, rid in tier_runs.items():
        p = runs_root / rid / "flow" / "steady_flow.csv"
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if df.empty:
            continue
        r = df.iloc[0]
        rows.append(
            {
                "tier": tier,
                "run_id": rid,
                "upstream_flow_cms": float(r.get("upstream_flow_cms", float("nan"))),
                "tributary_flow_cms": float(r.get("tributary_flow_cms", float("nan"))),
                "upstream_normal_depth_slope": float(r.get("upstream_normal_depth_slope", float("nan"))),
                "downstream_normal_depth_slope": float(r.get("downstream_normal_depth_slope", float("nan"))),
            }
        )
    if not rows:
        return "_No tier flow tables found._"
    df = pd.DataFrame(rows)
    try:
        return df.to_markdown(index=False)
    except Exception:
        return df.to_csv(index=False)


def _refs_markdown(refs: object) -> str:
    if not isinstance(refs, list) or not refs:
        return "_No references configured._"
    lines: list[str] = []
    for i, item in enumerate(refs, start=1):
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            claim = str(item.get("claim", "")).strip()
            if title and url:
                lines.append(f"{i}. [{title}]({url})")
            elif url:
                lines.append(f"{i}. {url}")
            if claim:
                lines.append(f"   - {claim}")
        else:
            lines.append(f"{i}. {str(item)}")
    return "\n".join(lines)


def _bullet_list(items: object) -> str:
    vals = _safe_list(items)
    if not vals:
        return "_Not specified._"
    return "\n".join(f"- {x}" for x in vals)


def _safe_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        s = str(v).strip()
        if s:
            out.append(s)
    return out
