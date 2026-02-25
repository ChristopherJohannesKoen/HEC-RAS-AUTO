from __future__ import annotations

from src.models import CitationRecord, RetrievalConfig


def score_citations(citations: list[CitationRecord], retrieval_cfg: RetrievalConfig) -> list[CitationRecord]:
    scored: list[CitationRecord] = []
    for c in citations:
        bonus = 0.0
        domain = c.publisher.lower()
        if any(d in domain for d in ("gov", "edu", "ac.", "wmo.int", "ipcc.ch")):
            bonus += 0.1
        if any(d in domain for d in retrieval_cfg.allowed_domains):
            bonus += 0.05
        c.confidence = min(1.0, max(0.0, c.confidence + bonus))
        scored.append(c)
    return scored


def filter_citations(citations: list[CitationRecord], threshold: float) -> list[CitationRecord]:
    return [c for c in citations if c.confidence >= threshold]
