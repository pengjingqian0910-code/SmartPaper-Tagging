"""
文稿潤色服務
幫助已有草稿的作者：學術語氣改寫、逐句批注、自動插入引用、偵測現有引用並推薦更佳替代
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional, Callable
from google import genai

from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper
from .reranker import Reranker


@dataclass
class SentenceNote:
    original: str
    polished: str
    comment: str          # why this change improves academic quality


@dataclass
class CitationSuggestion:
    paper: Paper
    location_hint: str    # which topic/claim this paper supports
    relevance_reason: str


@dataclass
class AlternativePaper:
    cited_ref: str        # detected citation string from original, e.g. "Smith, 2020"
    paper: Paper          # library paper on same topic
    reason: str


@dataclass
class PolishResult:
    polished_text: str
    sentence_notes: list[SentenceNote] = field(default_factory=list)
    citation_suggestions: list[CitationSuggestion] = field(default_factory=list)
    alternative_papers: list[AlternativePaper] = field(default_factory=list)
    detected_topics: list[str] = field(default_factory=list)
    detected_citations: list[str] = field(default_factory=list)


class TextPolishService:
    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
        api_key: Optional[str] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self.reranker = Reranker()
        self.api_key = api_key or GEMINI_API_KEY
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    def polish(
        self,
        text: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> PolishResult:
        def prog(msg: str):
            if progress_callback:
                progress_callback(msg)

        if not self.client:
            return PolishResult(polished_text="(Gemini API Key not configured)")

        # ── Call 1: LLM rewrite + annotations + topic/citation extraction ──
        prog("Step 1: AI rewriting for academic tone…")
        prompt = f"""You are an expert academic writing editor. The user has provided a draft paragraph or section. Your tasks:

1. **Rewrite** it with polished academic English — formal register, precise vocabulary, logical sentence flow, appropriate hedging. Preserve ALL original ideas; do not add new claims or remove existing ones.
2. **Sentence notes** — for each sentence that was substantially changed, explain the key improvement in plain English.
3. **Key topics** — extract 2–4 main academic concepts or topics from the text (used to search a citation library).
4. **Detected citations** — identify any existing in-text citation strings (e.g. "Smith, 2020", "(Jones et al., 2019)", "Wang and Lee 2021").

Draft text:
\"\"\"
{text}
\"\"\"

Respond strictly in JSON. All text values must be in English:
{{
    "polished_text": "The fully rewritten academic paragraph",
    "sentence_notes": [
        {{
            "original": "exact original sentence (copy verbatim)",
            "polished": "rewritten version of this sentence",
            "comment": "what was improved and why (under 20 words)"
        }}
    ],
    "key_topics": ["topic 1", "topic 2", "topic 3"],
    "detected_citations": ["Smith, 2020", "Jones et al., 2019"]
}}

Rules:
- sentence_notes: only include sentences with substantial changes; skip trivial ones
- polished_text must not introduce facts or claims absent from the original
- Return only the JSON, no other text"""

        try:
            resp = self.client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            raw = resp.text.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            data = json.loads(raw.strip())
        except Exception as ex:
            return PolishResult(polished_text=f"(Analysis failed: {ex})")

        polished_text      = data.get("polished_text", "")
        key_topics         = data.get("key_topics", [])
        detected_citations = data.get("detected_citations", [])
        raw_notes          = data.get("sentence_notes", [])

        sentence_notes = [
            SentenceNote(
                original=n.get("original", ""),
                polished=n.get("polished", ""),
                comment=n.get("comment", ""),
            )
            for n in raw_notes
            if n.get("original") and n.get("polished")
        ]

        # ── Step 2: Library search for citation suggestions ─────────────
        prog("Step 2: Searching library for citation suggestions…")
        citation_suggestions: list[CitationSuggestion] = []
        seen_ids: set[int] = set()

        for topic in key_topics[:4]:
            try:
                vr_list = self.vector_db.search(query=topic, n_results=4)
                for vr in vr_list:
                    if vr["paper_id"] in seen_ids:
                        continue
                    p = self.sqlite_db.get_by_id(vr["paper_id"])
                    if p and p.abstract:
                        seen_ids.add(p.id)
                        citation_suggestions.append(CitationSuggestion(
                            paper=p,
                            location_hint=topic,
                            relevance_reason=", ".join(p.tags[:2]) if p.tags else topic,
                        ))
            except Exception:
                pass

        # Rerank against the full input text
        if len(citation_suggestions) > 5:
            try:
                candidates = [
                    {
                        "cs": cs,
                        "document": f"{cs.paper.title}. {(cs.paper.abstract or '')[:300]}",
                    }
                    for cs in citation_suggestions
                ]
                reranked = self.reranker.rerank(
                    query=text[:300],
                    candidates=candidates,
                    text_key="document",
                    top_k=5,
                )
                citation_suggestions = [r["cs"] for r in reranked]
            except Exception:
                citation_suggestions = citation_suggestions[:5]
        else:
            citation_suggestions = citation_suggestions[:5]

        # ── Step 3: Find library alternatives for detected citations ─────
        prog("Step 3: Finding library alternatives for detected citations…")
        alternative_papers: list[AlternativePaper] = []

        for cited_ref in detected_citations[:4]:
            # Search library for papers on the same topic as the cited reference
            try:
                vr_list = self.vector_db.search(query=cited_ref, n_results=3)
                for vr in vr_list:
                    if vr["paper_id"] in seen_ids:
                        continue
                    p = self.sqlite_db.get_by_id(vr["paper_id"])
                    if p and p.abstract:
                        seen_ids.add(p.id)
                        alternative_papers.append(AlternativePaper(
                            cited_ref=cited_ref,
                            paper=p,
                            reason=(
                                f"Your library has '{p.title[:50]}' "
                                f"({p.year or '?'}) covering the same topic"
                            ),
                        ))
                        break
            except Exception:
                pass

        prog("Complete.")
        return PolishResult(
            polished_text=polished_text,
            sentence_notes=sentence_notes,
            citation_suggestions=citation_suggestions,
            alternative_papers=alternative_papers,
            detected_topics=key_topics,
            detected_citations=detected_citations,
        )
