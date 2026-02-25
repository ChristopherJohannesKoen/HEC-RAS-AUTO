from __future__ import annotations

import os
import re
from datetime import datetime

from src.models import AIAgentConfig, CitationRecord, RetrievalConfig


class WebCitationRetriever:
    def __init__(self, ai_config: AIAgentConfig, retrieval_cfg: RetrievalConfig) -> None:
        self.ai_config = ai_config
        self.retrieval_cfg = retrieval_cfg
        self._client = self._build_client()
        self.last_response_id: str | None = None

    def retrieve(self, claims: list[str]) -> list[CitationRecord]:
        records: list[CitationRecord] = []
        for claim in claims:
            records.extend(self._retrieve_for_claim(claim))
        dedup: dict[str, CitationRecord] = {}
        for rec in records:
            dedup_key = f"{rec.source_url}|{rec.claim_text}"
            if dedup_key not in dedup or rec.confidence > dedup[dedup_key].confidence:
                dedup[dedup_key] = rec
        return list(dedup.values())

    def _retrieve_for_claim(self, claim: str) -> list[CitationRecord]:
        if self._client is None:
            return []
        prompt = (
            f"Find {self.retrieval_cfg.max_sources_per_claim} authoritative web sources for this claim:\n"
            f"{claim}\n"
            "Return compact bullet points with URL, title, and one-sentence relevance."
        )
        try:
            resp = self._client.responses.create(
                model=self.ai_config.model,
                temperature=0.0,
                max_output_tokens=self.ai_config.max_tokens,
                tools=[{"type": "web_search_preview"}],
                input=[{"role": "user", "content": prompt}],
            )
            self.last_response_id = getattr(resp, "id", None)
            text = getattr(resp, "output_text", "") or ""
            urls = self._extract_urls(text)
            kept = [u for u in urls if self._allowed_domain(u)]
            kept = kept[: self.retrieval_cfg.max_sources_per_claim]
            out = []
            for u in kept:
                out.append(
                    CitationRecord(
                        source_url=u,
                        title=self._infer_title_from_url(u),
                        publisher=self._infer_publisher(u),
                        retrieved_at=datetime.utcnow(),
                        claim_text=claim,
                        confidence=0.75,
                        allowed_quote_excerpt=self._safe_excerpt(text),
                    )
                )
            return out
        except Exception:
            return []

    def _build_client(self):
        try:
            api_key = os.getenv(self.ai_config.api_key_env)
            if not api_key:
                return None
            from openai import OpenAI

            return OpenAI(api_key=api_key)
        except Exception:
            return None

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        return re.findall(r"https?://[^\s\]\)]+", text)

    def _allowed_domain(self, url: str) -> bool:
        domain = self._infer_publisher(url)
        if any(b in domain for b in self.retrieval_cfg.blocked_domains):
            return False
        if not self.retrieval_cfg.allowed_domains:
            return True
        return any(a in domain for a in self.retrieval_cfg.allowed_domains)

    @staticmethod
    def _infer_publisher(url: str) -> str:
        return url.split("/")[2].lower() if "://" in url else url.lower()

    @staticmethod
    def _infer_title_from_url(url: str) -> str:
        tail = url.rstrip("/").split("/")[-1]
        tail = tail.replace("-", " ").replace("_", " ")
        return tail[:80] or "source"

    @staticmethod
    def _safe_excerpt(text: str, limit: int = 120) -> str:
        return " ".join(text.strip().split())[:limit]
