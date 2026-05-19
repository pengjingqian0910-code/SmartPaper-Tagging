"""
Gemini Function Calling QA 服務
讓 Gemini 自主決定要搜尋什麼、要讀取哪些論文，而非手動 RAG。

工具清單：
  search_papers       — 語義搜尋論文庫
  get_paper_abstract  — 取得單篇論文的完整摘要
  get_paper_chunks    — 取得單篇論文的全文段落（PDF chunks）
  list_papers_by_tag  — 依標籤列出論文
"""

import json
import threading
from dataclasses import dataclass, field
from typing import Optional

from google.genai import types

from ..api.gemini import GeminiTagger
from ..database.chunk_store import ChunkStore
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper
from .qa_service import ChatMessage, QAResult, SourceChunk
from .search import SearchService
from .conversation_memory import ConversationMemory, TOP_K_INJECT
from .qa_skill import ConversationSkill

MAX_HISTORY_TURNS = 5
MAX_TOOL_ROUNDS = 6        # 最多讓 Gemini 呼叫幾輪工具
MAX_CHUNK_CHARS = 600
MAX_ABSTRACT_CHARS = 500

_SYSTEM = (
    "你是一位專業的學術研究助理，使用繁體中文回答。\n"
    "你可以呼叫以下工具來查詢論文庫：\n"
    "  • search_papers：語義搜尋，找最相關的論文\n"
    "  • get_paper_abstract：取得某篇論文的完整摘要\n"
    "  • get_paper_chunks：取得某篇論文的全文段落（需 PDF 已匯入）\n"
    "  • list_papers_by_tag：依標籤篩選論文\n\n"
    "回答規則：\n"
    "1. 先呼叫適當工具取得資料，再給出完整答案\n"
    "2. 在回答中用 [論文編號] 標注引用來源\n"
    "3. 語氣學術但易於理解，使用繁體中文\n"
    "4. 若工具回傳無結果，請告知用戶並建議補充相關論文\n"
)


class FunctionCallingQAService:
    """Gemini Function Calling 版問答服務，與 QAService 介面相容。"""

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
        self._gemini = GeminiTagger()
        self.memory = ConversationMemory()
        self.skill = ConversationSkill()

        # 紀錄本次 ask() 檢索到的論文（for source attribution）
        self._retrieved_papers: dict[int, Paper] = {}
        self._retrieved_chunks: list[SourceChunk] = []
        self._lock = threading.Lock()

    # ── 工具函式（Gemini 可呼叫）────────────────────────────────────────

    def _tool_search_papers(self, query: str, n_results: int = 5) -> str:
        """
        Search academic papers by semantic similarity to the query.

        Args:
            query: Natural language search query
            n_results: Number of papers to return (max 10)

        Returns:
            JSON list of matching papers with id, title, year, tags, abstract snippet
        """
        n = min(int(n_results), 10)
        results = self.search.hybrid_search(query, n_results=n, use_rerank=True)
        out = []
        for i, sr in enumerate(results, 1):
            p = sr.paper
            snippet = (p.abstract or "")[:200]
            with self._lock:
                self._retrieved_papers[p.id] = p
            out.append({
                "id": p.id,
                "title": p.title,
                "year": p.year,
                "tags": p.tags or [],
                "abstract_snippet": snippet,
            })
        return json.dumps(out, ensure_ascii=False)

    def _tool_get_paper_abstract(self, paper_id: int) -> str:
        """
        Get the full abstract of a specific paper by its ID.

        Args:
            paper_id: Integer ID of the paper (obtained from search_papers)

        Returns:
            JSON with title, authors, year, venue, abstract
        """
        paper = self.sqlite_db.get_by_id(int(paper_id))
        if not paper:
            return json.dumps({"error": f"Paper {paper_id} not found"})
        with self._lock:
            self._retrieved_papers[paper.id] = paper
            if paper.abstract:
                sc = SourceChunk(
                    paper=paper,
                    section="Abstract",
                    page_num=0,
                    snippet=paper.abstract[:MAX_ABSTRACT_CHARS],
                    is_fulltext=False,
                )
                self._retrieved_chunks.append(sc)
        return json.dumps({
            "id": paper.id,
            "title": paper.title,
            "authors": paper.authors or [],
            "year": paper.year,
            "venue": paper.venue,
            "abstract": paper.abstract or "",
        }, ensure_ascii=False)

    def _tool_get_paper_chunks(self, paper_id: int, section_filter: str = "") -> str:
        """
        Get full-text sections/chunks of a paper (requires PDF to be imported).

        Args:
            paper_id: Integer ID of the paper
            section_filter: Optional keyword to filter sections (e.g., 'method', 'result')

        Returns:
            JSON list of chunks with section name, page, and text
        """
        pid = int(paper_id)
        paper = self.sqlite_db.get_by_id(pid)
        if not paper:
            return json.dumps({"error": f"Paper {pid} not found"})

        chunks = self.chunk_store.get_by_paper(pid)
        if not chunks:
            return json.dumps({"info": "No full-text chunks available for this paper. Try get_paper_abstract instead."})

        if section_filter:
            sf = section_filter.lower()
            chunks = [c for c in chunks if sf in (c.section or "").lower()] or chunks[:5]

        with self._lock:
            self._retrieved_papers[paper.id] = paper
            for c in chunks[:6]:
                sc = SourceChunk(
                    paper=paper,
                    section=c.section or "全文",
                    page_num=c.page_num or 0,
                    snippet=c.chunk_text[:MAX_CHUNK_CHARS],
                    is_fulltext=True,
                )
                self._retrieved_chunks.append(sc)

        out = []
        for c in chunks[:6]:
            out.append({
                "section": c.section,
                "page": c.page_num,
                "text": c.chunk_text[:MAX_CHUNK_CHARS],
            })
        return json.dumps(out, ensure_ascii=False)

    def _tool_list_papers_by_tag(self, tag: str) -> str:
        """
        List papers that have a specific tag.

        Args:
            tag: Tag name to filter by

        Returns:
            JSON list of papers with id, title, year
        """
        papers = self.sqlite_db.get_by_tag(tag)
        out = [{"id": p.id, "title": p.title, "year": p.year} for p in papers[:20]]
        return json.dumps(out, ensure_ascii=False)

    # ── 主要問答介面 ─────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        history: Optional[list[ChatMessage]] = None,
        top_k: int = 5,
        filter_paper_ids: Optional[set[int]] = None,
        context_paper_ids: Optional[set[int]] = None,
    ) -> QAResult:
        """與 QAService.ask() 介面相容的方法。"""
        history = history or []
        turn = self.memory.next_turn()

        # 重置本次的追蹤狀態
        with self._lock:
            self._retrieved_papers = {}
            self._retrieved_chunks = []

        # 組合對話歷史（送給 Gemini 的 contents）
        contents = self._build_contents(question, history)

        # 工具清單
        tools = [
            self._tool_search_papers,
            self._tool_get_paper_abstract,
            self._tool_get_paper_chunks,
            self._tool_list_papers_by_tag,
        ]

        # 注入記憶
        top_memories = self.memory.get_top_k(query=question, k=TOP_K_INJECT)
        memory_text = self.memory.to_prompt(top_memories) if top_memories else ""
        system = _SYSTEM + (f"\n\n【對話記憶】\n{memory_text}" if memory_text else "")

        # 多輪 Function Calling 迴圈
        answer = self._run_fc_loop(contents, tools, system)

        # 整理 source_chunks（去重，最多取 top_k 筆）
        seen_keys: set[tuple] = set()
        source_chunks: list[SourceChunk] = []
        for sc in self._retrieved_chunks:
            key = (sc.paper.id, sc.section)
            if key not in seen_keys:
                seen_keys.add(key)
                source_chunks.append(sc)
        source_chunks = source_chunks[:top_k]

        # 若 retrieved_chunks 為空但有 retrieved_papers，用摘要補
        if not source_chunks and self._retrieved_papers:
            for paper in list(self._retrieved_papers.values())[:top_k]:
                if paper.abstract:
                    source_chunks.append(SourceChunk(
                        paper=paper,
                        section="Abstract",
                        page_num=0,
                        snippet=paper.abstract[:MAX_ABSTRACT_CHARS],
                        is_fulltext=False,
                    ))

        # 非同步記憶萃取
        self.skill.extract_async(turn, question, answer, source_chunks, self.memory)

        return QAResult(answer=answer, source_chunks=source_chunks, query=question)

    def suggest_followups(self, question: str, answer: str, n: int = 2) -> list[str]:
        """產生追問建議（與 QAService 相同實作）。"""
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

    # ── 內部方法 ─────────────────────────────────────────────────────────

    def _build_contents(self, question: str, history: list[ChatMessage]) -> list:
        """將對話歷史轉成 Gemini contents 格式。"""
        contents = []
        trimmed = history[-(MAX_HISTORY_TURNS * 2):]
        for msg in trimmed:
            role = "user" if msg.role == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part(text=msg.content)],
            ))
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=question)],
        ))
        return contents

    def _run_fc_loop(self, contents: list, tools: list, system: str) -> str:
        """執行 Gemini Function Calling 多輪迴圈，回傳最終文字答案。"""
        tool_map = {fn.__name__.replace("_tool_", ""): fn for fn in tools}
        # Rename: _tool_search_papers → search_papers
        tool_map = {
            "search_papers": self._tool_search_papers,
            "get_paper_abstract": self._tool_get_paper_abstract,
            "get_paper_chunks": self._tool_get_paper_chunks,
            "list_papers_by_tag": self._tool_list_papers_by_tag,
        }

        # Gemini function objects（SDK auto-generates schema from Python functions）
        gemini_tools = list(tool_map.values())

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._gemini.client.models.generate_content(
                    model=self._gemini.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        tools=gemini_tools,
                        system_instruction=system,
                    ),
                )
            except Exception as e:
                return f"⚠️ Gemini API 呼叫失敗：{e}"

            candidate = response.candidates[0]
            parts = candidate.content.parts

            # 收集本輪所有 function calls
            fc_parts = [p for p in parts if p.function_call is not None]
            text_parts = [p for p in parts if p.text]

            # 如果沒有 function call → 最終答案
            if not fc_parts:
                return "\n".join(p.text for p in text_parts).strip() or "（無法生成回答）"

            # 執行所有 function calls，收集 responses
            contents.append(candidate.content)   # model 的這一輪輸出加入歷史

            fn_responses = []
            for fc_part in fc_parts:
                fc = fc_part.function_call
                fn = tool_map.get(fc.name)
                if fn is None:
                    result_str = json.dumps({"error": f"Unknown tool: {fc.name}"})
                else:
                    try:
                        kwargs = dict(fc.args) if fc.args else {}
                        result_str = fn(**kwargs)
                    except Exception as ex:
                        result_str = json.dumps({"error": str(ex)})

                fn_responses.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result_str},
                    )
                ))

            contents.append(types.Content(
                role="tool",
                parts=fn_responses,
            ))

        # 超過 MAX_TOOL_ROUNDS，強制要求 Gemini 給最終回答
        try:
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text="請根據以上工具查詢結果，給出完整的最終回答。")],
            ))
            final = self._gemini.client.models.generate_content(
                model=self._gemini.model_name,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system),
            )
            return final.text.strip()
        except Exception as e:
            return f"⚠️ 最終回答生成失敗：{e}"
