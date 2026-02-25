from __future__ import annotations

import json
from pathlib import Path

from src.models import CitationRecord


def load_citations(run_id: str, output_root: Path = Path("outputs")) -> list[CitationRecord]:
    path = output_root / run_id / "agent" / "citations.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[CitationRecord] = []
    for item in raw:
        try:
            out.append(CitationRecord.model_validate(item))
        except Exception:
            continue
    return out


def citations_markdown(citations: list[CitationRecord]) -> str:
    if not citations:
        return "_No validated external citations were attached._"
    lines = []
    for i, c in enumerate(citations, start=1):
        lines.append(f"{i}. [{c.title}]({c.source_url}) - {c.publisher} (confidence={c.confidence:.2f})")
    return "\n".join(lines)


def inject_citation_markers(text: str, citations: list[CitationRecord]) -> str:
    if "[CITE]" not in text:
        return text
    if not citations:
        return text.replace("[CITE]", "[VERIFY][CITE]")
    out = text
    idx = 1
    while "[CITE]" in out:
        out = out.replace("[CITE]", f"[CITE:{idx}]", 1)
        idx = min(idx + 1, len(citations))
    return out
