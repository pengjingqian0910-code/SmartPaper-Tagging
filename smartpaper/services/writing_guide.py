"""
寫作引用導引服務
根據論文大綱各段落，推薦應引用哪些論文的哪些概念
"""

import json
from dataclasses import dataclass, field
from typing import Optional, Callable, TYPE_CHECKING
from google import genai

from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..models import Paper
from .reranker import Reranker

if TYPE_CHECKING:
    from ..skills import SkillConfig

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
        skill: Optional["SkillConfig"] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self.skill = skill
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

        role_prefix = self.skill.system_prompt + "\n\n" if self.skill else ""

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
        prompt1 = f"""你是一位嚴格的學術寫作顧問，負責檢視論文大綱是否完整、有深度。

作者的論文大綱：
{outline_text}

目前已建議的引用文獻分布：
{citations_summary}

請分析並回答：
1. **追問（Follow-up Questions）**：針對這份大綱，讀者或審稿人可能會提出哪些重要問題？這些問題指出了大綱目前論述不夠深入或需要補強的地方。請提出 3-5 個具體追問。
2. **概念缺口（Missing Concepts）**：目前引用的文獻缺少哪些重要概念？這些概念如果補入，能讓大綱更全面、論述更有說服力。請提出 3-5 個缺少的概念。

以 JSON 格式回答：
{{
    "follow_up_questions": [
        "問題1（具體指出大綱哪個部分不足）",
        "問題2...",
        "..."
    ],
    "missing_concepts": [
        {{
            "concept": "概念名稱（5-15字）",
            "reason": "為什麼這個概念重要，缺少它會有什麼問題（30字以內）",
            "suggested_section": "建議補充到哪個段落（對應上面大綱的段落描述）"
        }}
    ]
}}

只回傳 JSON，不要有其他文字。"""

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

        # ── Call 2：生成具體寫作範例 ───────────────────────────────────
        prog("Step 3-3：AI 生成寫作範例...")
        pairs_text = ""
        for i, cp in enumerate(concept_paper_pairs, 1):
            if cp["paper"]:
                abstract_preview = (cp["paper"].abstract or "")[:250]
                pairs_text += (
                    f"{i}. 概念：{cp['concept']}\n"
                    f"   論文：{cp['paper'].title}\n"
                    f"   摘要片段：{abstract_preview}\n\n"
                )
            else:
                pairs_text += (
                    f"{i}. 概念：{cp['concept']}\n"
                    f"   （文獻庫中暫無對應論文，請考慮補充外部文獻）\n\n"
                )

        prompt2 = f"""你是學術寫作助理，請為以下每個「概念缺口」生成一段具體的學術寫作範例。

論文大綱：
{outline_text}

概念缺口與對應論文：
{pairs_text}

對於每個有對應論文的概念缺口，請生成：
1. 一段 30-60 字的示範寫作句子（以「基於」、「根據」、「依據」、「X研究指出」等學術用語開頭，自然融入引用概念）
2. 說明這段文字適合放在論文的哪個位置/如何銜接

對於沒有對應論文的概念缺口，說明建議補充什麼類型的外部文獻。

以 JSON 格式回答：
{{
    "examples": [
        {{
            "index": 1,
            "writing_example": "示範寫作句子（有論文的情況）",
            "placement_tip": "建議放在哪個段落的哪個位置，以及如何與前後文銜接（25字以內）"
        }}
    ]
}}

只回傳 JSON，不要有其他文字。"""

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
