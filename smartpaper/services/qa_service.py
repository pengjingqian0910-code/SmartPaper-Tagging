"""
開放式問答服務（RAG QA）
雙 collection 查詢：PDF 全文 chunks + 摘要 fallback
支援對話歷史（滑動視窗）
"""

from typing import Optional
from dataclasses import dataclass, field

from ..api.gemini import GeminiTagger
from ..database.chunk_store import ChunkStore
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper
from .reranker import Reranker
from .search import SearchService
from .conversation_memory import ConversationMemory, TOP_K_INJECT
from .qa_skill import ConversationSkill
from .intent_classifier import IntentClassifier
from .semantic_cache import SemanticCache


MAX_HISTORY_TURNS = 5     # 保留最近 N 輪對話
MAX_CHUNK_CHARS = 600     # 每個 chunk 送給 LLM 的最大字元
MAX_ABSTRACT_CHARS = 500  # 摘要 fallback 的最大字元
MAX_CHUNKS_PER_PAPER = 2  # 同一篇論文最多取幾個 chunk（避免壟斷 context）


@dataclass
class ChatMessage:
    role: str   # "user" | "assistant"
    content: str


@dataclass
class SourceChunk:
    """一個回答來源，可以是全文 chunk 或摘要"""
    paper: Paper
    section: str           # chunk 所屬章節，摘要為 "Abstract"
    page_num: int          # PDF 頁碼，摘要為 0
    snippet: str           # 送入 LLM 的文字片段
    is_fulltext: bool      # True = 來自全文 chunk，False = 來自摘要
    is_table: bool = False
    section_type: str = "other"
    importance_weight: float = 1.0


@dataclass
class QAResult:
    answer: str
    source_chunks: list[SourceChunk] = field(default_factory=list)
    query: str = ""
    # ── 新增欄位（向後相容，有預設值）───────────────────────────────
    intent: str = "qa"            # "qa" | "action" | "chitchat"
    intent_conf: float = 1.0      # 意圖信心度 0-1
    cache_hit: bool = False       # 是否命中語義快取
    cache_type: str = ""          # "exact" | "semantic" | ""

    @property
    def sources(self) -> list[Paper]:
        """回溯相容：回傳去重後的論文列表"""
        seen, papers = set(), []
        for sc in self.source_chunks:
            if sc.paper.id not in seen:
                seen.add(sc.paper.id)
                papers.append(sc.paper)
        return papers


class QAService:
    """
    學術論文問答服務（全文 + 摘要雙路徑）

    查詢流程：
    1. 搜尋 fulltext collection（若有 PDF 全文）
    2. 搜尋 abstracts collection 補充沒有全文的論文
    3. CrossEncoder rerank 全部候選
    4. 每篇論文最多 MAX_CHUNKS_PER_PAPER 個 chunk
    5. 組合 context 送給 Gemini，要求標注 [N] 引用
    """

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
        search_service: Optional[SearchService] = None,
        chunk_store: Optional[ChunkStore] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self.search = search_service or SearchService(self.sqlite_db, self.vector_db)
        self.chunk_store = chunk_store or ChunkStore()
        self.reranker = Reranker()
        self._gemini = GeminiTagger()
        self.memory = ConversationMemory()
        self.skill = ConversationSkill()
        # 意圖分類器（規則層，不呼叫 LLM，毫秒級）
        self._intent = IntentClassifier(use_llm_fallback=False)
        # QA 層語義快取（快取完整 QA 回答，對話無 context 時才命中）
        self._qa_cache = SemanticCache(similarity_threshold=0.95, ttl_seconds=1800)

    # ──────────────────────────────────────────────
    # 主要問答介面
    # ──────────────────────────────────────────────

    def ask(
        self,
        question: str,
        history: Optional[list[ChatMessage]] = None,
        top_k: int = 5,
        filter_paper_ids: Optional[set[int]] = None,
        context_paper_ids: Optional[set[int]] = None,
    ) -> QAResult:
        """
        對論文庫提問，回傳有引用來源的答案。

        Args:
            question: 用戶問題
            history:  對話歷史（由呼叫端維護）
            top_k:    最終送進 LLM 的來源數量上限

        Returns:
            QAResult(answer, source_chunks, query)
        """
        history = history or []

        # ── Step 0: 意圖分類（毫秒級規則層，無 API 呼叫）──────────────
        intent, intent_conf = self._intent.classify(question)

        # 閒聊直接回應，完全跳過 RAG pipeline
        if intent == "chitchat":
            answer = self._chitchat_response(question)
            return QAResult(
                answer=answer,
                source_chunks=[],
                query=question,
                intent="chitchat",
                intent_conf=intent_conf,
            )

        # ── Step 1: QA 語義快取（無對話 context 時嘗試命中）──────────
        cache_hit, cache_type = False, ""
        if not history and not filter_paper_ids and not context_paper_ids:
            sem_hit, cached = self._qa_cache.get(question)
            if sem_hit and cached is not None:
                cached.cache_hit = True
                cached.cache_type = "semantic"
                cached.intent = intent
                cached.intent_conf = intent_conf
                return cached

        # ── Step 2: 完整 RAG pipeline ────────────────────────────────
        turn = self.memory.next_turn()

        source_chunks = self._retrieve(
            question,
            top_k=top_k,
            filter_paper_ids=filter_paper_ids,
            context_paper_ids=context_paper_ids,
        )

        context = self._build_context(source_chunks)
        top_memories = self.memory.get_top_k(query=question, k=TOP_K_INJECT)
        memory_text = self.memory.to_prompt(top_memories) if top_memories else ""

        prompt = self._build_prompt(question, context, history, memory_text)
        answer = self._call_llm(prompt)

        # 非同步萃取本輪記憶（背景執行，不阻塞回傳）
        self.skill.extract_async(turn, question, answer, source_chunks, self.memory)

        result = QAResult(
            answer=answer,
            source_chunks=source_chunks,
            query=question,
            intent=intent,
            intent_conf=intent_conf,
            cache_hit=False,
            cache_type="",
        )

        # 無 context 依賴時才寫入 QA 快取
        if not history and not filter_paper_ids and not context_paper_ids:
            self._qa_cache.put(question, result)

        return result

    def _chitchat_response(self, question: str) -> str:
        """閒聊回應（不呼叫 RAG，不消耗向量資源）"""
        greetings = {
            "你好": "你好！我是 SmartPaper 學術助理。有什麼論文相關的問題嗎？",
            "hi":   "Hi! I'm your SmartPaper research assistant. Feel free to ask about your papers!",
            "嗨":   "嗨！我可以幫你查詢文獻庫、回答論文問題，或分析研究主題。",
        }
        q_lower = question.lower().strip()
        for key, reply in greetings.items():
            if q_lower.startswith(key):
                return reply

        # 通用閒聊
        try:
            prompt = (
                f"用戶說：「{question}」\n\n"
                "你是 SmartPaper 學術論文管理助理，請用一到兩句話友善回應（繁體中文），"
                "並自然地引導用戶詢問論文相關問題。不要捏造任何論文或資料。"
            )
            resp = self._gemini.client.models.generate_content(
                model=self._gemini.model_name, contents=prompt
            )
            return resp.text.strip()
        except Exception:
            return "您好！請問有什麼論文相關的問題需要我幫忙查詢嗎？"

    # ──────────────────────────────────────────────
    # 檢索邏輯
    # ──────────────────────────────────────────────

    def _retrieve(self, query: str, top_k: int,
                  filter_paper_ids: Optional[set[int]] = None,
                  context_paper_ids: Optional[set[int]] = None) -> list[SourceChunk]:
        """雙路徑檢索：全文 chunks + 摘要 fallback"""
        candidates: list[dict] = []   # {text, source_chunk, paper}

        # ── 路徑 A：全文 chunk 搜尋
        fulltext_results = self.vector_db.search_chunks(query, n_results=top_k * 4)
        paper_chunk_counts: dict[int, int] = {}

        for cr in fulltext_results:
            pid = cr["paper_id"]
            if pid is None:
                continue
            if filter_paper_ids is not None and pid not in filter_paper_ids:
                continue
            count = paper_chunk_counts.get(pid, 0)
            if count >= MAX_CHUNKS_PER_PAPER:
                continue
            paper = self.sqlite_db.get_by_id(pid)
            if not paper:
                continue
            paper_chunk_counts[pid] = count + 1
            snippet = cr["chunk_text"][:MAX_CHUNK_CHARS]
            importance = cr.get("importance_weight", 1.0)
            sc = SourceChunk(
                paper=paper,
                section=cr["section"],
                page_num=cr.get("page_num", 0),
                snippet=snippet,
                is_fulltext=True,
                is_table=cr.get("is_table", False),
                section_type=cr.get("section_type", "other"),
                importance_weight=importance,
            )
            candidates.append({
                "text": snippet,
                "source_chunk": sc,
                "paper": paper,
                "importance_weight": importance,
            })

        # ── 路徑 B：摘要搜尋（補充沒有全文 chunk 的論文）
        papers_covered = set(paper_chunk_counts.keys())
        abstract_results = self.search.hybrid_search(query, n_results=top_k * 2)
        for sr in abstract_results:
            if (sr.paper and sr.paper.id not in papers_covered and sr.paper.abstract
                    and (filter_paper_ids is None or sr.paper.id in filter_paper_ids)):
                snippet = sr.paper.abstract[:MAX_ABSTRACT_CHARS]
                sc = SourceChunk(
                    paper=sr.paper,
                    section="Abstract",
                    page_num=0,
                    snippet=snippet,
                    is_fulltext=False,
                )
                candidates.append({"text": snippet, "source_chunk": sc, "paper": sr.paper})

        # ── 路徑 C：追問記憶 — 強制注入上一輪引用的論文（若未被前兩路覆蓋）
        if context_paper_ids:
            already_covered = {c["source_chunk"].paper.id for c in candidates}
            for pid in context_paper_ids:
                if pid in already_covered:
                    continue
                if filter_paper_ids is not None and pid not in filter_paper_ids:
                    continue
                paper = self.sqlite_db.get_by_id(pid)
                if not paper:
                    continue
                # 優先用全文 chunk，其次用摘要
                chunk_rows = self.chunk_store.get_by_paper(pid)
                if chunk_rows:
                    snippet = chunk_rows[0].chunk_text[:MAX_CHUNK_CHARS]
                    sc = SourceChunk(
                        paper=paper,
                        section=chunk_rows[0].section or "全文",
                        page_num=chunk_rows[0].page_num or 0,
                        snippet=snippet,
                        is_fulltext=True,
                    )
                elif paper.abstract:
                    snippet = paper.abstract[:MAX_ABSTRACT_CHARS]
                    sc = SourceChunk(paper=paper, section="Abstract",
                                     page_num=0, snippet=snippet, is_fulltext=False)
                else:
                    continue
                candidates.append({"text": sc.snippet, "source_chunk": sc, "paper": paper})

        if not candidates:
            return []

        # ── CrossEncoder rerank + section importance boosting
        try:
            reranked = self.reranker.rerank(
                query=query,
                candidates=candidates,
                text_key="text",
                top_k=None,  # 先全部 rerank 再自己切
            )
            # 將 rerank_score 乘上 importance_weight，讓 Methodology/Results 優先
            for c in reranked:
                base = c.get("rerank_score", 0.0)
                w = c.get("importance_weight", 1.0)
                c["weighted_score"] = base * w
            reranked.sort(key=lambda x: -x["weighted_score"])
            return [c["source_chunk"] for c in reranked[:top_k]]
        except Exception:
            return [c["source_chunk"] for c in candidates[:top_k]]

    # ──────────────────────────────────────────────
    # Context 組裝
    # ──────────────────────────────────────────────

    def _build_context(self, source_chunks: list[SourceChunk]) -> str:
        parts = []
        for i, sc in enumerate(source_chunks, 1):
            paper = sc.paper
            year_str = f" ({paper.year})" if paper.year else ""
            venue_str = f" — {paper.venue}" if paper.venue else ""
            fulltext_flag = "全文" if sc.is_fulltext else "摘要"
            table_flag = "（表格）" if sc.is_table else ""
            page_str = f"，第 {sc.page_num} 頁" if sc.page_num and sc.is_fulltext else ""

            header = (
                f"[{i}] {paper.title}{year_str}{venue_str}\n"
                f"     [{fulltext_flag} / {sc.section}{table_flag}{page_str}]"
            )
            parts.append(f"{header}\n{sc.snippet}")
        return "\n\n".join(parts)

    def _get_user_profile_text(self) -> str:
        """載入使用者研究身份設定，組成 prompt 前綴。"""
        try:
            profile = self.sqlite_db.get_user_profile()
        except Exception:
            return ""
        parts = []
        if profile.get("research_field"):
            parts.append(f"研究領域：{profile['research_field']}")
        if profile.get("research_keywords"):
            parts.append(f"核心關鍵詞：{profile['research_keywords']}")
        style_map = {
            "formal":   "正式學術語氣，使用嚴謹術語",
            "balanced": "平衡簡潔，學術但易懂",
            "concise":  "精簡扼要，避免冗余",
        }
        style = style_map.get(profile.get("writing_style", ""), "")
        if style:
            parts.append(f"偏好回答風格：{style}")
        if not parts:
            return ""
        return "【使用者研究背景】\n" + "\n".join(parts)

    def _build_prompt(
        self,
        question: str,
        context: str,
        history: list[ChatMessage],
        memory_text: str = "",
    ) -> str:
        profile_text = self._get_user_profile_text()
        profile_block = f"\n\n{profile_text}" if profile_text else ""

        system = (
            "你是一位專業的學術研究助理，擅長根據論文內容回答研究問題。\n"
            "回答規則：\n"
            "1. 優先根據【參考資料】的內容作答，並用 [數字] 標注引用來源，例如「根據 [1][3] 的研究...」\n"
            "2. 若參考資料只有部分相關，請根據現有資料給出最佳回答，並說明資料的侷限\n"
            "3. 若有表格資料（標記為「表格」），可以引用其中的數字或比較結果\n"
            "4. 若【對話記憶】中有相關內容，可結合使用，但仍以【參考資料】為主\n"
            "5. 若有【使用者研究背景】，請根據其領域與風格偏好調整回答深度與語氣\n"
            "6. 回答使用繁體中文，語氣學術但易於理解\n"
            "7. 只有在參考資料完全沒有任何相關內容時，才說明無法回答，並建議使用者補充相關論文\n"
        )

        trimmed = history[-(MAX_HISTORY_TURNS * 2):]
        history_text = ""
        if trimmed:
            turns = []
            for msg in trimmed:
                label = "用戶" if msg.role == "user" else "助理"
                turns.append(f"{label}：{msg.content[:400]}")  # 截短避免 context 過長
            history_text = "\n\n【對話歷史】\n" + "\n\n".join(turns)

        memory_block = f"\n\n{memory_text}" if memory_text else ""

        return (
            f"{system}"
            f"{profile_block}"
            f"{memory_block}"
            f"{history_text}\n\n"
            f"【參考資料】\n{context}\n\n"
            f"【用戶問題】\n{question}\n\n"
            "請根據上述參考資料回答，並在適當位置標注引用編號："
        )

    def _call_llm(self, prompt: str) -> str:
        try:
            response = self._gemini.client.models.generate_content(
                model=self._gemini.model_name,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            return f"⚠️ LLM 呼叫失敗：{e}"

    def _call_llm_stream(self, prompt: str):
        """Gemini 串流生成，yield 每個文字 chunk。"""
        try:
            from google.genai import types as _gt
            response = self._gemini.client.models.generate_content_stream(
                model=self._gemini.model_name,
                contents=prompt,
            )
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"⚠️ LLM 串流失敗：{e}"

    def ask_stream(
        self,
        question: str,
        history: Optional[list[ChatMessage]] = None,
        top_k: int = 5,
        filter_paper_ids: Optional[set[int]] = None,
        context_paper_ids: Optional[set[int]] = None,
    ):
        """
        串流版問答：先 yield QAResult（answer=""，含 source_chunks），
        再 yield str chunk（逐步累積答案），最後 yield None 表示結束。
        呼叫端用法：
            for item in service.ask_stream(question, ...):
                if item is None:
                    break
                elif isinstance(item, QAResult):
                    show_sources(item.source_chunks)
                else:
                    append_text(item)
        """
        history = history or []

        # 意圖分類
        intent, intent_conf = self._intent.classify(question)
        if intent == "chitchat":
            answer = self._chitchat_response(question)
            yield QAResult(answer=answer, query=question,
                           intent="chitchat", intent_conf=intent_conf)
            yield None
            return

        # QA 語義快取（命中時一次性 yield，不串流）
        if not history and not filter_paper_ids and not context_paper_ids:
            sem_hit, cached = self._qa_cache.get(question)
            if sem_hit and cached is not None:
                cached.cache_hit = True
                cached.cache_type = "semantic"
                cached.intent = intent
                cached.intent_conf = intent_conf
                yield cached
                yield None
                return

        # 完整 RAG pipeline
        turn = self.memory.next_turn()
        source_chunks = self._retrieve(
            question, top_k=top_k,
            filter_paper_ids=filter_paper_ids,
            context_paper_ids=context_paper_ids,
        )
        context = self._build_context(source_chunks)
        top_memories = self.memory.get_top_k(query=question, k=TOP_K_INJECT)
        memory_text = self.memory.to_prompt(top_memories) if top_memories else ""
        prompt = self._build_prompt(question, context, history, memory_text)

        # 先送出 sources（answer 為空）讓 UI 先顯示來源區塊
        meta_result = QAResult(
            answer="",
            source_chunks=source_chunks,
            query=question,
            intent=intent,
            intent_conf=intent_conf,
        )
        yield meta_result

        # 串流 LLM 輸出
        full_answer = ""
        for chunk in self._call_llm_stream(prompt):
            full_answer += chunk
            yield chunk

        # 完成後更新 meta_result 並寫入快取
        meta_result.answer = full_answer
        self.skill.extract_async(turn, question, full_answer, source_chunks, self.memory)
        if not history and not filter_paper_ids and not context_paper_ids:
            self._qa_cache.put(question, meta_result)

        yield None

    def suggest_followups(self, question: str, answer: str, n: int = 2) -> list[str]:
        """根據問題和回答，產生 n 個引導式追問建議"""
        prompt = (
            f"用戶剛問了：「{question}」\n"
            f"AI 回答了：「{answer[:400]}」\n\n"
            f"請根據以上問答內容，提出 {n} 個值得繼續深入的追問，"
            "幫助用戶更深入理解這些論文。\n"
            "要求：每個問題獨立一行，不要加編號或符號，直接是問句，20字以內。\n"
            f"只輸出 {n} 行問句，不要其他文字。"
        )
        try:
            response = self._gemini.client.models.generate_content(
                model=self._gemini.model_name,
                contents=prompt,
            )
            lines = [l.strip() for l in response.text.strip().splitlines() if l.strip()]
            return lines[:n]
        except Exception:
            return []
