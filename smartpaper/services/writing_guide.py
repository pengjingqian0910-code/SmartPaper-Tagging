"""
寫作引用導引服務
根據論文大綱各段落，推薦應引用哪些論文的哪些概念
"""

import json
from dataclasses import dataclass, field
from typing import Optional, Callable
from google import genai

from ..api.arxiv import ArxivAPI
from ..api import semantic_scholar as ss_api
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..models import Paper
from .reranker import Reranker

# 學術寫作專家系統提示，讓所有分析更聚焦於學術寫作品質
_WRITING_EXPERT_PROMPT = (
    "你是一位資深學術寫作顧問，擁有豐富的期刊論文、會議論文審稿與指導經驗。\n"
    "你的任務是協助研究者以嚴謹、清晰、具說服力的學術語言呈現研究成果。\n"
    "在分析引用建議時，你特別注重：\n"
    "1. 引用的邏輯鏈（如何從文獻建立論述的學術依據）\n"
    "2. 段落層次感（開頭引入背景、中間支撐論點、結尾總結或過渡）\n"
    "3. 學術措辭的精確性（避免過度籠統的引用理由）\n"
    "4. 論文整體架構的連貫性與完整性\n"
)

# forward-ref workaround: OutlineEnrichment is defined after WritingGuideService uses it
# so we use string annotation in generate_enrichment return type


@dataclass
class CitationGuide:
    paper: Paper
    should_cite: bool
    cite_reason: str       # 為什麼要在這個段落引用
    key_concept: str       # 應引用的核心概念或發現
    cite_position: str     # 建議引用位置：開頭 / 中間 / 結尾
    relevance_score: float = 0.0


@dataclass
class SectionGuide:
    section: str                          # 段落標題/描述
    citations: list[CitationGuide] = field(default_factory=list)
    writing_hint: str = ""                # 整體寫作建議


@dataclass
class ConceptGap:
    concept: str             # 缺少的概念名稱
    reason: str              # 為什麼這個概念重要
    suggested_section: str   # 建議補充到哪個段落
    paper: Optional[Paper]   # 文獻庫中找到的對應論文（可能為 None）
    writing_example: str = ""  # 具體寫作範例句
    external_suggestions: list[dict] = field(default_factory=list)  # arXiv 外部論文建議


@dataclass
class OutlineEnrichment:
    follow_up_questions: list[str] = field(default_factory=list)
    concept_gaps: list[ConceptGap] = field(default_factory=list)


class WritingGuideService:
    """寫作引用導引服務"""

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

    def generate_outline_guide(
        self,
        sections: list[str],
        n_candidates: int = 8,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> list[SectionGuide]:
        """
        為整份寫作大綱的每個段落生成引用導引

        Args:
            sections: 段落標題/描述列表
            n_candidates: 每個段落取的候選論文數量
            progress_callback: 進度回調 (section, current, total)

        Returns:
            每個段落對應的 SectionGuide
        """
        results = []
        total = len(sections)

        for idx, section in enumerate(sections):
            if progress_callback:
                progress_callback(section, idx + 1, total)

            guide = self.generate_section_guide(section, n_candidates=n_candidates)
            results.append(guide)

        return results

    def find_section_candidates(
        self,
        section: str,
        n_candidates: int = 8,
    ) -> list[dict]:
        """
        僅搜尋並 re-rank 候選論文，不呼叫 LLM。
        讓使用者在 UI 確認哪些論文要送進分析。

        Returns:
            list of {paper, score, document, rerank_score?}
        """
        fetch_n = n_candidates * 3
        vector_results = self.vector_db.search(query=section, n_results=fetch_n)
        if not vector_results:
            return []

        candidates = []
        for vr in vector_results:
            paper = self.sqlite_db.get_by_id(vr["paper_id"])
            if paper:
                candidates.append({
                    "paper": paper,
                    "score": vr["score"],
                    "document": f"{paper.title}. {(paper.abstract or '')[:300]}",
                })

        if candidates:
            try:
                candidates = self.reranker.rerank(
                    query=section,
                    candidates=candidates,
                    text_key="document",
                    top_k=n_candidates,
                )
            except Exception:
                candidates = candidates[:n_candidates]

        return candidates

    def analyze_from_candidates(
        self,
        section: str,
        candidates: list[dict],
    ) -> SectionGuide:
        """
        接受已確認的候選論文列表，直接執行 LLM 分析。
        candidates 每項需有 "paper" 欄位。
        """
        if not candidates:
            return SectionGuide(section=section,
                                writing_hint="未選擇任何候選論文。")

        if not self.client:
            citations = [
                CitationGuide(
                    paper=c["paper"],
                    should_cite=True,
                    cite_reason="語意相關",
                    key_concept=", ".join(c["paper"].tags[:2]) if c["paper"].tags else "",
                    cite_position="中間",
                    relevance_score=c.get("rerank_score", c.get("score", 0.0)),
                )
                for c in candidates
            ]
            return SectionGuide(section=section, citations=citations)

        return self._analyze_with_llm(section, candidates)

    def generate_section_guide(
        self,
        section: str,
        n_candidates: int = 8,
    ) -> SectionGuide:
        """為單一段落生成引用導引（舊有 API，一步完成搜尋+分析）"""
        candidates = self.find_section_candidates(section, n_candidates)
        if not candidates:
            return SectionGuide(section=section,
                                writing_hint="資料庫中尚無相關論文，請先匯入論文資料。")
        return self.analyze_from_candidates(section, candidates)

    def _analyze_with_llm(
        self,
        section: str,
        candidates: list[dict],
    ) -> SectionGuide:
        """用 LLM 分析候選論文並生成引用建議（一次 API call 處理所有候選）"""

        role_prefix = _WRITING_EXPERT_PROMPT + "\n"

        # 建構論文列表文字
        papers_text = ""
        for i, c in enumerate(candidates, 1):
            paper = c["paper"]
            abstract_preview = paper.abstract[:400] if paper.abstract else "無摘要"
            tags_text = f"標籤：{', '.join(paper.tags)}\n   " if paper.tags else ""
            papers_text += (
                f"{i}. 標題：{paper.title}\n"
                f"   {tags_text}"
                f"   摘要：{abstract_preview}\n\n"
            )

        prompt = f"""{role_prefix}你是一位學術寫作助理，負責協助作者決定在論文各段落應引用哪些文獻。

作者正在撰寫這個段落：
【{section}】

以下是與此段落語意相關的候選論文（已按相關性排序）：

{papers_text}

請仔細分析每篇論文是否適合在「{section}」這個段落中被引用。

考量重點：
1. 這篇論文的哪個概念/方法/發現可以支撐這個段落的論述？
2. 引用這篇論文能為段落增添什麼學術依據？
3. 引用建議放在段落的哪個位置最自然？

請以 JSON 格式回答：
{{
    "writing_hint": "針對「{section}」這個段落的整體寫作建議（60字以內，說明應涵蓋哪些要點）",
    "citations": [
        {{
            "paper_index": 1,
            "should_cite": true,
            "cite_reason": "為什麼要引用：具體說明這篇論文能為段落提供什麼依據（40字以內）",
            "key_concept": "應引用的核心概念或具體發現（25字以內）",
            "cite_position": "段落開頭 / 中間論述 / 結尾總結（選一）"
        }}
    ]
}}

重要：
- 只列出 should_cite 為 true 的論文
- 若論文與這個段落無關，直接省略，不要列入 citations
- 每篇論文的分析必須具體，不能泛泛而談
- 只回傳 JSON，不要有其他文字"""

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            response_text = response.text.strip()

            # 清理 markdown 格式
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            data = json.loads(response_text.strip())
            writing_hint = data.get("writing_hint", "")

            # 解析引用建議
            citations = []
            paper_map = {i + 1: c for i, c in enumerate(candidates)}

            for item in data.get("citations", []):
                idx = item.get("paper_index")
                if idx not in paper_map:
                    continue

                candidate = paper_map[idx]
                citations.append(CitationGuide(
                    paper=candidate["paper"],
                    should_cite=True,
                    cite_reason=item.get("cite_reason", ""),
                    key_concept=item.get("key_concept", ""),
                    cite_position=item.get("cite_position", "中間論述"),
                    relevance_score=candidate.get("rerank_score", candidate.get("score", 0.0)),
                ))

            return SectionGuide(
                section=section,
                citations=citations,
                writing_hint=writing_hint,
            )

        except Exception as e:
            print(f"LLM 分析失敗: {e}")
            return SectionGuide(
                section=section,
                writing_hint=f"分析失敗：{str(e)[:80]}",
            )

    def generate_enrichment(
        self,
        sections: list[str],
        guides: list[SectionGuide],
        progress_callback: Optional[Callable] = None,
    ) -> "OutlineEnrichment":
        """
        Step 3：分析目前大綱的缺口，搜尋文獻庫補強，生成具體寫作範例。

        流程：
        1. LLM 分析大綱 + 已引用論文 → 找出 follow-up questions + missing concepts
        2. 對每個 missing concept 語意搜尋文獻庫
        3. LLM 為每個 concept + paper 生成寫作範例句
        """
        def prog(msg):
            if progress_callback:
                progress_callback(msg)

        if not self.client:
            return OutlineEnrichment(
                follow_up_questions=["未設定 Gemini API Key，無法進行 AI 分析"],
                concept_gaps=[],
            )

        # ── 整理目前引用摘要給 LLM ──────────────────────────────────
        outline_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sections))
        citations_summary = ""
        for guide in guides:
            if guide.citations:
                cited_titles = "、".join(
                    c.paper.title[:30] + ("…" if len(c.paper.title) > 30 else "")
                    for c in guide.citations
                )
                citations_summary += f"- {guide.section}：引用了 {cited_titles}\n"
            else:
                citations_summary += f"- {guide.section}：尚無引用論文\n"

        prog("Step 3-1：AI 分析大綱缺口與追問...")

        # ── Call 1：找出 follow-up questions + missing concepts ──────
        prompt1 = f"""{_WRITING_EXPERT_PROMPT}
Act as a strict academic writing consultant. Evaluate whether the following paper outline is complete and sufficiently rigorous.

Paper outline:
{outline_text}

Current citation distribution across sections:
{citations_summary}

Please analyze and respond with:
1. **Follow-up Questions**: What important questions might reviewers or readers raise about this outline? Identify 3–5 specific gaps in argumentation or depth.
2. **Missing Concepts**: What important concepts are absent from the current citations? Identify 3–5 concepts whose inclusion would make the outline more comprehensive and persuasive.

Respond in JSON format. All text values must be written in English:
{{
    "follow_up_questions": [
        "Question 1 (identify which section is insufficient)",
        "Question 2...",
        "..."
    ],
    "missing_concepts": [
        {{
            "concept": "Concept name (3–8 words)",
            "reason": "Why this concept matters and what is lost without it (under 25 words)",
            "suggested_section": "Which section of the outline this concept should be added to"
        }}
    ]
}}

Return only the JSON, no other text."""

        try:
            resp1 = self.client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt1,
            )
            text1 = resp1.text.strip()
            if "```json" in text1:
                text1 = text1.split("```json")[1].split("```")[0]
            elif "```" in text1:
                text1 = text1.split("```")[1].split("```")[0]
            data1 = json.loads(text1.strip())
        except Exception as ex:
            return OutlineEnrichment(
                follow_up_questions=[f"分析失敗：{ex}"],
                concept_gaps=[],
            )

        follow_up_questions = data1.get("follow_up_questions", [])
        raw_concepts = data1.get("missing_concepts", [])

        if not raw_concepts:
            return OutlineEnrichment(
                follow_up_questions=follow_up_questions,
                concept_gaps=[],
            )

        # ── 搜尋文獻庫：為每個 missing concept 找對應論文 ────────────
        prog(f"Step 3-2：搜尋文獻庫（{len(raw_concepts)} 個概念缺口）...")
        concept_paper_pairs: list[dict] = []
        for rc in raw_concepts:
            concept = rc.get("concept", "")
            query   = f"{concept} {rc.get('reason', '')}"
            vr_list = self.vector_db.search(query=query, n_results=3)
            paper   = None
            for vr in vr_list:
                p = self.sqlite_db.get_by_id(vr["paper_id"])
                if p and p.abstract:
                    paper = p
                    break
            concept_paper_pairs.append({
                "concept":           concept,
                "reason":            rc.get("reason", ""),
                "suggested_section": rc.get("suggested_section", ""),
                "paper":             paper,
            })

        # ── 外部論文建議：優先用 arXiv 直接關鍵字搜尋（最相關），再補 SS 推薦
        prog(f"Step 3-2b：外部論文搜尋（{len(concept_paper_pairs)} 個缺口）...")
        arxiv_api = ArxivAPI()
        for cp in concept_paper_pairs:
            suggestions: list[dict] = []
            query = f"{cp['concept']} {cp['reason']}"
            # 主力：arXiv 直接關鍵字搜尋（摘要最完整）
            try:
                arxiv_recs = arxiv_api.search_by_keywords(query, n_results=3)
                for r in arxiv_recs:
                    r["source"] = "arXiv"
                suggestions.extend(arxiv_recs)
            except Exception:
                pass
            # 補充：若本地論文有 DOI → Semantic Scholar 推薦
            local_paper = cp["paper"]
            if len(suggestions) < 3 and local_paper and local_paper.doi:
                try:
                    ss_recs = ss_api.fetch_recommendations(local_paper.doi,
                                                           n=3 - len(suggestions))
                    for r in ss_recs:
                        r["source"] = "Semantic Scholar"
                    suggestions.extend(ss_recs)
                except Exception:
                    pass
            cp["external_suggestions"] = suggestions

        # ── Call 2：生成具體寫作範例（基於外部論文摘要，產出完整段落）────
        prog("Step 3-3：AI 生成寫作範例...")
        pairs_text = ""
        for i, cp in enumerate(concept_paper_pairs, 1):
            ext_block = ""
            for j, ext in enumerate(cp.get("external_suggestions", [])[:3], 1):
                ext_abs = (ext.get("abstract") or "")[:300]
                ext_authors = ext.get("authors", [])
                if ext_authors:
                    last_name = ext_authors[0].split()[-1]
                    author_cite = f"{last_name} et al." if len(ext_authors) > 1 else last_name
                else:
                    author_cite = "Anonymous"
                ext_year = ext.get("year", "")
                ext_block += (
                    f"   外部文獻{j}：{ext.get('title', '')} "
                    f"（{author_cite}, {ext_year}）\n"
                    f"   建議引用格式：({author_cite}, {ext_year})\n"
                    f"   摘要：{ext_abs}\n"
                )
            pairs_text += (
                f"{i}. 概念：{cp['concept']}\n"
                f"   理由：{cp['reason']}\n"
                f"{ext_block if ext_block else '   （暫無外部文獻）'}\n"
            )

        prompt2 = f"""You are a senior academic writing consultant. For each concept gap below, write a complete academic paragraph in English demonstrating how to incorporate the relevant literature.

Paper outline:
{outline_text}

Concept gaps and available external references (with abstracts and suggested citation formats):
{pairs_text}

**IMPORTANT RULES**:
- All output text must be in English.
- In-text citations must use ONLY the "Suggested citation format" provided above, e.g. (Wang et al., 2023). Do NOT cite any other papers or fabricate author names or years.
- If fewer than two external references are provided for a gap, cite only those available.

For each concept gap, generate:
1. A complete academic paragraph of **80–150 words** (3–4 sentences):
   - Sentence 1: Introduce the concept and its significance in the academic context.
   - Sentences 2–3: Elaborate on the core methods, findings, or theory, naturally integrating parenthetical citations (only from the provided references).
   - Sentence 4: Connect this concept to the present study's research question and bridge to the next section.
2. A brief placement tip explaining where in the outline this paragraph belongs and how it connects.

Respond in JSON format:
{{
    "examples": [
        {{
            "index": 1,
            "writing_example": "Full academic paragraph (80–150 words, 3–4 sentences, citations only from provided references)",
            "placement_tip": "Where this paragraph fits in the outline and how it transitions (under 20 words)"
        }}
    ]
}}

Return only the JSON, no other text."""

        try:
            resp2 = self.client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt2,
            )
            text2 = resp2.text.strip()
            if "```json" in text2:
                text2 = text2.split("```json")[1].split("```")[0]
            elif "```" in text2:
                text2 = text2.split("```")[1].split("```")[0]
            data2 = json.loads(text2.strip())
            examples_map = {ex["index"]: ex for ex in data2.get("examples", [])}
        except Exception:
            examples_map = {}

        # ── 組裝 ConceptGap 列表 ───────────────────────────────────────
        concept_gaps = []
        for i, cp in enumerate(concept_paper_pairs, 1):
            ex = examples_map.get(i, {})
            writing_example = ex.get("writing_example", "")
            placement_tip   = ex.get("placement_tip", "")
            if placement_tip:
                writing_example = writing_example + f"\n💡 {placement_tip}"
            concept_gaps.append(ConceptGap(
                concept=cp["concept"],
                reason=cp["reason"],
                suggested_section=cp["suggested_section"],
                paper=cp["paper"],
                writing_example=writing_example,
                external_suggestions=cp.get("external_suggestions", []),
            ))

        prog("Step 3 完成")
        return OutlineEnrichment(
            follow_up_questions=follow_up_questions,
            concept_gaps=concept_gaps,
        )

    def export_guide_to_markdown(
        self,
        guides: list[SectionGuide],
        output_path: str,
    ) -> None:
        """將寫作導引匯出為 Markdown 文件"""
        lines = ["# 寫作引用導引\n"]

        for i, guide in enumerate(guides, 1):
            lines.append(f"## {i}. {guide.section}\n")

            if guide.writing_hint:
                lines.append(f"> **寫作建議**：{guide.writing_hint}\n")

            if not guide.citations:
                lines.append("*未找到相關論文*\n")
                continue

            lines.append(f"**建議引用 {len(guide.citations)} 篇論文：**\n")

            for c in guide.citations:
                lines.append(f"### 📄 {c.paper.title}")
                lines.append(f"- **引用時機**：{c.cite_reason}")
                lines.append(f"- **引用概念**：{c.key_concept}")
                lines.append(f"- **段落位置**：{c.cite_position}")
                if c.paper.doi:
                    lines.append(f"- **DOI**：{c.paper.doi}")
                lines.append("")

            lines.append("---\n")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
