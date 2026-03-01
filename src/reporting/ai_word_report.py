from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.models import AIAgentConfig


def build_ai_word_report(
    run_id: str,
    prompt_text: str,
    ai_config: AIAgentConfig,
    output_root: Path = Path("outputs"),
) -> dict[str, str]:
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"{run_id}_final_ai_report.md"
    docx_path = reports_dir / f"{run_id}_final_ai_report.docx"
    debug_path = reports_dir / f"{run_id}_final_ai_report_debug.json"

    context = _collect_context(run_id=run_id, prompt_text=prompt_text, output_root=output_root)
    ai_result = _generate_sections_with_ai(context=context, ai_config=ai_config)
    title = ai_result.get("title") or f"{run_id} Hydraulic Report"
    sections = ai_result.get("sections") or _fallback_sections_from_context(context)
    if not isinstance(sections, list) or not sections:
        sections = _fallback_sections_from_context(context)

    md_text = _sections_to_markdown(title, sections)
    md_path.write_text(md_text, encoding="utf-8")
    _write_docx(title=title, sections=sections, out_path=docx_path)

    debug_payload = {
        "run_id": run_id,
        "title": title,
        "section_count": len(sections),
        "ai_enabled": bool(ai_result.get("ai_enabled", False)),
        "response_id": ai_result.get("response_id"),
    }
    debug_path.write_text(json.dumps(debug_payload, indent=2), encoding="utf-8")

    return {
        "markdown": str(md_path),
        "docx": str(docx_path),
        "debug": str(debug_path),
    }


def _collect_context(run_id: str, prompt_text: str, output_root: Path) -> dict[str, str]:
    report_md = output_root / "reports" / f"{run_id}_report_draft.md"
    metrics_csv = output_root / run_id / "tables" / "metrics.csv"
    sections_csv = output_root / run_id / "sections" / "required_sections.csv"
    hydraulic_qa = output_root / run_id / "qa" / "hydraulic_qa.md"
    regime_md = output_root / run_id / "qa" / "flow_regime_recommendation.md"

    return {
        "prompt_text": prompt_text[:40000],
        "report_draft_md": _read_limited(report_md, 40000),
        "metrics_csv": _read_limited(metrics_csv, 20000),
        "required_sections_csv": _read_limited(sections_csv, 20000),
        "hydraulic_qa_md": _read_limited(hydraulic_qa, 12000),
        "regime_recommendation_md": _read_limited(regime_md, 12000),
    }


def _generate_sections_with_ai(context: dict[str, str], ai_config: AIAgentConfig) -> dict:
    enabled = bool(os.getenv(ai_config.api_key_env))
    if not enabled:
        return {"ai_enabled": False, "sections": _fallback_sections_from_context(context)}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv(ai_config.api_key_env))
    except Exception:
        return {"ai_enabled": False, "sections": _fallback_sections_from_context(context)}

    system_prompt = (
        ai_config.prompts.report.full_report
        or "Write a detailed hydraulic report and return strict JSON with title and sections."
    )
    request = {
        "task": "write_full_hydraulic_report",
        "output_schema": {
            "title": "string",
            "sections": [
                {
                    "heading": "string",
                    "body": "string with detailed engineering narrative",
                }
            ],
        },
        "rules": [
            "Return JSON only.",
            "No markdown fences.",
            "Use quantified values when present in context.",
            "Mark uncertain claims with [VERIFY].",
            "Cover baseline and scenario comparison when available.",
        ],
        "context": context,
    }
    try:
        resp = client.responses.create(
            model=ai_config.model,
            temperature=min(ai_config.temperature, 0.2),
            max_output_tokens=max(ai_config.max_tokens, 2500),
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(request)},
            ],
        )
        raw = getattr(resp, "output_text", "") or ""
        response_id = getattr(resp, "id", None)
        obj = _extract_json(raw)
        if not isinstance(obj, dict):
            return {
                "ai_enabled": True,
                "response_id": response_id,
                "sections": _fallback_sections_from_context(context),
            }
        obj["ai_enabled"] = True
        obj["response_id"] = response_id
        return obj
    except Exception:
        return {"ai_enabled": False, "sections": _fallback_sections_from_context(context)}


def _sections_to_markdown(title: str, sections: list[dict]) -> str:
    lines = [f"# {title}", ""]
    for sec in sections:
        heading = str(sec.get("heading", "")).strip() or "Section"
        body = str(sec.get("body", "")).strip()
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body if body else "_No content generated._")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _fallback_sections_from_context(context: dict[str, str]) -> list[dict]:
    draft = context.get("report_draft_md", "").strip()
    if draft:
        return [
            {"heading": "Assignment Context", "body": context.get("prompt_text", "")[:3000]},
            {"heading": "Draft Report Content", "body": draft[:18000]},
            {"heading": "Hydraulic QA Notes", "body": context.get("hydraulic_qa_md", "")[:8000]},
            {"heading": "Flow Regime Recommendation", "body": context.get("regime_recommendation_md", "")[:8000]},
        ]
    return [
        {"heading": "Assignment Context", "body": context.get("prompt_text", "")[:5000]},
        {"heading": "Model Metrics", "body": context.get("metrics_csv", "")[:12000]},
        {"heading": "Section Outputs", "body": context.get("required_sections_csv", "")[:12000]},
    ]


def _read_limited(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return txt[:limit]


def _extract_json(text: str) -> dict | None:
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


def _write_docx(title: str, sections: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    created = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    doc_xml = _build_document_xml(title=title, sections=sections)
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""
    core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{escape(title)}</dc:title>
  <dc:creator>HEC-RAS-AUTO</dc:creator>
  <cp:lastModifiedBy>HEC-RAS-AUTO</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>"""
    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>HEC-RAS-AUTO</Application>
</Properties>"""

    with ZipFile(out_path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("docProps/app.xml", app_xml)
        zf.writestr("word/document.xml", doc_xml)


def _build_document_xml(title: str, sections: list[dict]) -> str:
    body_parts: list[str] = []
    body_parts.append(_p(title, bold=True))
    body_parts.append(_p(""))
    for sec in sections:
        heading = str(sec.get("heading", "")).strip() or "Section"
        body = str(sec.get("body", "")).strip()
        body_parts.append(_p(heading, bold=True))
        if body:
            for para in _split_paragraphs(body):
                body_parts.append(_p(para))
        else:
            body_parts.append(_p("No content generated."))
        body_parts.append(_p(""))

    body_parts.append(
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
        'w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
    )
    body = "".join(body_parts)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14"><w:body>'
        + body
        + "</w:body></w:document>"
    )


def _p(text: str, bold: bool = False) -> str:
    if text == "":
        return "<w:p/>"
    safe = escape(text).replace("\n", " ")
    if bold:
        return f"<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"


def _split_paragraphs(text: str) -> list[str]:
    parts: list[str] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        cleaned = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if cleaned:
            parts.append(cleaned)
    return parts or [text.strip()]
