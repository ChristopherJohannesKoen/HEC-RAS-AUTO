from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.models import AIAgentConfig


class InputReviewer:
    def __init__(self, ai_config: AIAgentConfig) -> None:
        self.ai_config = ai_config
        self.enabled = bool(os.getenv(ai_config.api_key_env))
        self._client = None
        self.last_response_id: str | None = None
        if self.enabled:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=os.getenv(ai_config.api_key_env))
            except Exception:
                self.enabled = False

    def review_and_prepare_sheets(
        self,
        prompt_text: str,
        source_dir: Path,
        sheets_path: Path,
        run_id: str,
        output_root: Path = Path("outputs"),
    ) -> dict[str, Any]:
        agent_dir = output_root / run_id / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        runtime_sheets = agent_dir / "sheets_runtime.yml"
        review_json = agent_dir / "input_review.json"
        review_md = agent_dir / "input_review.md"

        current = _load_yaml_file(sheets_path)
        workbook = _pick_workbook(source_dir)
        workbook_profile = _profile_workbook(workbook) if workbook else {"workbook": "", "sheets": []}

        payload: dict[str, Any] = {
            "enabled": bool(self.enabled and self._client is not None),
            "workbook": str(workbook) if workbook else "",
            "current_sheets_config": current,
            "recommended_sheets": {},
            "changes_applied": False,
            "issues": [],
            "prompt_overrides": {},
            "raw_model_output": "",
            "response_id": None,
        }

        recommended = _extract_current_sheet_subset(current)
        if payload["enabled"]:
            response = self._ask_model(prompt_text=prompt_text, workbook_profile=workbook_profile, current=current)
            payload["raw_model_output"] = response.get("raw_model_output", "")
            payload["response_id"] = response.get("response_id")
            payload["issues"] = response.get("issues", [])
            payload["prompt_overrides"] = response.get("prompt_overrides", {})
            model_rec = response.get("recommended_sheets", {})
            validated = _validate_recommendation(model_rec, workbook_profile)
            if validated:
                recommended = validated
                payload["recommended_sheets"] = validated
            else:
                payload["recommended_sheets"] = recommended
        else:
            payload["issues"] = ["AI reviewer disabled or unavailable; using current sheets config."]
            payload["recommended_sheets"] = recommended

        merged = _merge_sheet_config(current, payload["recommended_sheets"])
        runtime_sheets.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
        payload["runtime_sheets_path"] = str(runtime_sheets)
        payload["changes_applied"] = bool(
            _extract_current_sheet_subset(current) != _extract_current_sheet_subset(merged)
        )

        review_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        review_md.write_text(_to_markdown(payload), encoding="utf-8")
        return payload

    def _ask_model(self, prompt_text: str, workbook_profile: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled or self._client is None:
            return {}

        system_prompt = (
            self.ai_config.prompts.input_review
            or "Review workbook sheets/headers and return strict JSON with safe parser fixes."
        )
        request = {
            "task": "review_prompt_and_input_parser_config",
            "constraints": {
                "allowed_changes": [
                    "excel.cross_sections_sheet",
                    "excel.centerline_sheet",
                    "excel.columns.chainage",
                    "excel.columns.station",
                    "excel.columns.offset",
                    "excel.columns.elevation",
                    "excel.columns.x",
                    "excel.columns.y",
                ],
                "do_not_modify_raw_files": True,
            },
            "prompt_text": prompt_text,
            "current_sheets_config": _extract_current_sheet_subset(current),
            "workbook_profile": workbook_profile,
            "required_json_schema": {
                "issues": ["string"],
                "recommended_sheets": {
                    "cross_sections_sheet": "string",
                    "centerline_sheet": "string",
                    "columns": {
                        "chainage": "string",
                        "station": "string",
                        "offset": "string",
                        "elevation": "string",
                        "x": "string",
                        "y": "string",
                    },
                },
                "prompt_overrides": {
                    "assigned_scenario": "scenario_1|scenario_2|scenario_3|scenario_4",
                    "constraints": {},
                },
            },
            "output_rules": ["Return JSON only.", "No markdown fences."],
        }

        try:
            resp = self._client.responses.create(
                model=self.ai_config.model,
                temperature=min(self.ai_config.temperature, 0.2),
                max_output_tokens=max(self.ai_config.max_tokens, 1200),
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(request)},
                ],
            )
            self.last_response_id = getattr(resp, "id", None)
            raw = getattr(resp, "output_text", "") or ""
            obj = _extract_json(raw)
            if not isinstance(obj, dict):
                return {"raw_model_output": raw, "response_id": self.last_response_id}
            obj["raw_model_output"] = raw
            obj["response_id"] = self.last_response_id
            return obj
        except Exception as exc:
            return {
                "issues": [f"AI input review failed: {exc}"],
                "raw_model_output": "",
                "response_id": self.last_response_id,
            }


def _load_yaml_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _pick_workbook(source_dir: Path) -> Path | None:
    if not source_dir.exists():
        return None
    cands = sorted(source_dir.rglob("*.xlsx"))
    if not cands:
        return None
    preferred = [p for p in cands if "info" in p.name.lower() or "meerlustkloof" in p.name.lower()]
    return preferred[0] if preferred else cands[0]


def _profile_workbook(xlsx: Path) -> dict[str, Any]:
    profile: dict[str, Any] = {"workbook": str(xlsx), "sheets": []}
    try:
        xl = pd.ExcelFile(xlsx)
    except Exception:
        return profile
    for sheet in xl.sheet_names[:8]:
        try:
            df = pd.read_excel(xlsx, sheet_name=sheet, header=None, nrows=12)
            preview = df.iloc[:, :12].fillna("").astype(str).values.tolist()
            cols = [str(c) for c in pd.read_excel(xlsx, sheet_name=sheet, nrows=0).columns.tolist()]
        except Exception:
            preview = []
            cols = []
        profile["sheets"].append({"name": sheet, "columns": cols[:20], "preview": preview})
    return profile


def _extract_current_sheet_subset(cfg: dict[str, Any]) -> dict[str, Any]:
    excel = cfg.get("excel", {})
    return {
        "cross_sections_sheet": excel.get("cross_sections_sheet", ""),
        "centerline_sheet": excel.get("centerline_sheet", ""),
        "columns": dict(excel.get("columns", {}) or {}),
    }


def _validate_recommendation(rec: dict[str, Any], workbook_profile: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(rec, dict):
        return None
    sheet_names = {str(s.get("name", "")) for s in (workbook_profile.get("sheets", []) or [])}
    out: dict[str, Any] = {}
    xs_sheet = str(rec.get("cross_sections_sheet", "")).strip()
    cl_sheet = str(rec.get("centerline_sheet", "")).strip()
    if xs_sheet and (not sheet_names or xs_sheet in sheet_names):
        out["cross_sections_sheet"] = xs_sheet
    if cl_sheet and (not sheet_names or cl_sheet in sheet_names):
        out["centerline_sheet"] = cl_sheet

    cols = rec.get("columns", {})
    if isinstance(cols, dict):
        allowed = {"chainage", "station", "offset", "elevation", "x", "y"}
        vcols: dict[str, str] = {}
        for k, v in cols.items():
            kk = str(k).strip().lower()
            vv = str(v).strip()
            if kk in allowed and vv:
                vcols[kk] = vv
        if vcols:
            out["columns"] = vcols
    return out if out else None


def _merge_sheet_config(current: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(current))
    merged.setdefault("excel", {})
    excel = merged["excel"]
    if "cross_sections_sheet" in rec:
        excel["cross_sections_sheet"] = rec["cross_sections_sheet"]
    if "centerline_sheet" in rec:
        excel["centerline_sheet"] = rec["centerline_sheet"]
    excel.setdefault("columns", {})
    if isinstance(rec.get("columns"), dict):
        for k, v in rec["columns"].items():
            excel["columns"][k] = v
    return merged


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Input Review", ""]
    lines.append(f"- Enabled: `{payload.get('enabled')}`")
    lines.append(f"- Workbook: `{payload.get('workbook', '')}`")
    lines.append(f"- Changes Applied: `{payload.get('changes_applied')}`")
    lines.append(f"- Runtime Sheets: `{payload.get('runtime_sheets_path', '')}`")
    if payload.get("response_id"):
        lines.append(f"- OpenAI Response ID: `{payload.get('response_id')}`")
    lines.append("")
    lines.append("## Issues")
    issues = payload.get("issues") or []
    if issues:
        for item in issues:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Recommended Sheets")
    lines.append("```json")
    lines.append(json.dumps(payload.get("recommended_sheets", {}), indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Prompt Overrides")
    lines.append("```json")
    lines.append(json.dumps(payload.get("prompt_overrides", {}), indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)
