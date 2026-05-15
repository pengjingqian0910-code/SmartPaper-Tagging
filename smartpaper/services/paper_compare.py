"""
跨論文推理服務

給定 2-5 篇論文（paper_ids）+ 比較問題（question），
從每篇論文分別取 Methodology / Results / Conclusion 的代表 chunk，
送給 Gemini 做結構化比較分析，回傳：
- 方法異同
- 結果/數據比較
- 研究缺口
"""

from dataclasses import dataclass, field
from typing import Optional

from ..api.gemini import GeminiTagger
from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..database.chunk_store import ChunkStore
from ..database.sqlite_db import SQLiteDB
from ..models import Paper


# 每篇論文抽取哪些 section_type 供比較
COMPARE_SECTION_PRIORITY = ["abstract", "methodology", "results", "conclusion", "discussion"]
MAX_CHARS_PER_PAPER = 1800  # 每篇送進 LLM 的字元上限


@dataclass
class PaperCompareResult:
    papers: list[Paper]
    similarities: str = ""
    differences: str = ""
    research_gaps: str = ""
    recommendation: str = ""
    raw_answer: str = ""
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.raw_answer)


class PaperCompareService:
    """
    跨論文比較分析服務。

    使用方式：
        svc = PaperCompareService()
        result = svc.compare([1, 3, 5], question="這三篇論文的方法有什麼根本差異？")
    """

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        chunk_store: Optional[ChunkStore] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.chunk_store = chunk_store or ChunkStore()

    def compare(
        self,
        paper_ids: list[int],
        question: str = "",
        progress_callback=None,
    ) -> PaperCompareResult:
        def prog(msg):
            if progress_callback:
                progress_callback(msg)

        if len(paper_ids) < 2:
            return PaperCompareResult(papers=[], error="至少需要 2 篇論文才能比較")
        if len(paper_ids) > 6:
            paper_ids = paper_ids[:6]

        if not GEMINI_API_KEY:
            return PaperCompareResult(papers=[], error="未設定 GEMINI_API_KEY")

        # 1. 取得論文 metadata
        prog("載入論文資料...")
        papers = []
        for pid in paper_ids:
            p = self.sqlite_db.get_by_id(pid)
            if p:
                papers.append(p)
        if len(papers) < 2:
            return PaperCompareResult(papers=papers, error="找不到足夠的論文")

        # 2. 為每篇論文建立代表性文字
        prog("提取各論文關鍵段落...")
        paper_summaries = []
        for paper in papers:
            text = self._extract_representative_text(paper)
            if not text and paper.abstract:
                text = paper.abstract[:MAX_CHARS_PER_PAPER]
            year_str = f"（{paper.year}）" if paper.year else ""
            venue_str = f", {paper.venue}" if paper.venue else ""
            header = f"【論文 {paper.id}】{paper.title}{year_str}{venue_str}"
            paper_summaries.append(f"{header}\n{text}")

        # 3. 組合 prompt
        prog("LLM 比較分析中...")
        context = "\n\n---\n\n".join(paper_summaries)
        prompt = self._build_prompt(context, question, papers)

        # 4. 呼叫 Gemini
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            raw = response.text.strip()
        except Exception as e:
            return PaperCompareResult(papers=papers, error=f"LLM 呼叫失敗：{e}")

        # 5. 解析回傳（嘗試提取各段落）
        result = PaperCompareResult(papers=papers, raw_answer=raw)
        result.similarities = _extract_section(raw, ["相同點", "共同點", "Similarities"])
        result.differences  = _extract_section(raw, ["差異", "不同點", "Differences"])
        result.research_gaps = _extract_section(raw, ["研究缺口", "不足", "Gap", "Future"])
        result.recommendation = _extract_section(raw, ["建議", "推薦", "Recommendation"])
        return result

    def _extract_representative_text(self, paper: Paper) -> str:
        """依 section 重要性順序提取 chunk 文字"""
        chunks = self.chunk_store.get_by_paper(paper.id)
        if not chunks:
            return ""

        # 按 section_type 分桶（chunk_store 的 StoredChunk 還沒有 section_type，
        # 所以用 section 名稱來猜 canonical type）
        from ..processing.pdf_parser import _classify_section
        buckets: dict[str, list[str]] = {}
        for c in chunks:
            s_type, _ = _classify_section(c.section)
            buckets.setdefault(s_type, []).append(c.chunk_text)

        # 依優先順序拼接，字元上限
        parts = []
        total = 0
        for prio in COMPARE_SECTION_PRIORITY:
            for text in buckets.get(prio, [])[:2]:  # 每個 section 最多 2 chunk
                if total >= MAX_CHARS_PER_PAPER:
                    break
                excerpt = text[:400]
                parts.append(f"[{prio}] {excerpt}")
                total += len(excerpt)
            if total >= MAX_CHARS_PER_PAPER:
                break

        return "\n".join(parts)

    def _build_prompt(
        self,
        context: str,
        question: str,
        papers: list[Paper],
    ) -> str:
        titles = "\n".join(f"  {i+1}. {p.title}" for i, p in enumerate(papers))
        custom_q = f"\n\n【使用者問題】\n{question}" if question.strip() else ""
        return f"""你是學術研究分析助理，擅長比較多篇論文的研究方法與貢獻。

請比較以下 {len(papers)} 篇論文：
{titles}
{custom_q}

【各論文內容摘錄】
{context}

請以以下結構回答（繁體中文，學術語氣）：

## 方法相同點
（各論文在研究方法、假設或框架上的共通之處）

## 方法差異
（各論文在方法、模型、實驗設計上的根本不同）

## 結果與數據比較
（各論文的性能指標、實驗結果的比較，若有數字請列出）

## 研究缺口與不足
（各論文承認的局限性，或從比較中發現的研究空白）

## 綜合建議
（如果要做新研究，從這些論文中可以借鑑什麼？填補什麼缺口？）
"""


def _extract_section(text: str, keywords: list[str]) -> str:
    """從結構化回答中提取某個段落"""
    lines = text.split("\n")
    collecting = False
    result_lines = []
    for line in lines:
        if any(kw in line for kw in keywords):
            collecting = True
            continue
        if collecting:
            # 遇到下一個 ## 停止
            if line.startswith("##") or line.startswith("**"):
                if result_lines:
                    break
            result_lines.append(line)
    return "\n".join(result_lines).strip()
