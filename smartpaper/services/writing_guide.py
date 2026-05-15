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
