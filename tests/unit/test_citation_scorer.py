from __future__ import annotations

from src.agent.citation_scorer import filter_citations, score_citations
from src.models import CitationRecord, RetrievalConfig


def test_citation_scoring_and_filtering() -> None:
    cfg = RetrievalConfig(allowed_domains=["noaa.gov"], citation_confidence_threshold=0.7)
    citations = [
        CitationRecord(
            source_url="https://www.noaa.gov/example",
            title="NOAA",
            publisher="www.noaa.gov",
            claim_text="claim",
            confidence=0.65,
        ),
        CitationRecord(
            source_url="https://example.com/a",
            title="Example",
            publisher="example.com",
            claim_text="claim",
            confidence=0.4,
        ),
    ]
    scored = score_citations(citations, cfg)
    filtered = filter_citations(scored, cfg.citation_confidence_threshold)
    assert any("noaa.gov" in c.publisher for c in filtered)
    assert all(c.confidence >= 0.7 for c in filtered)
