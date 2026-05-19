"""
Gemini Function Calling QA 服務
讓 Gemini 自主決定要搜尋什麼、要讀取哪些論文，而非手動 RAG。

修正點：
  - 使用顯式 FunctionDeclaration，禁用 SDK auto function calling
  - function response 使用 role='user'（Gemini API 規範）
  - 手動多輪迴圈，完整控制每一輪的執行
"""

import json
import threading
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
MAX_TOOL_ROUNDS = 6
MAX_CHUNK_CHARS = 600
MAX_ABSTRACT_CHARS = 500

_SYSTEM = (
    "你是一位專業的學術研究助理，使用繁體中文回答。\n"
    "你有以下工具可以查詢本地論文庫：\n"
    "  • search_papers：依問題語義搜尋最相關論文\n"
    "  • get_paper_abstract：取得某篇論文的完整摘要\n"
    "  • get_paper_chunks：取得某篇論文的全文段落（需 PDF 已匯入）\n"
    "  • list_papers_by_tag：依標籤篩選論文\n\n"
    "回答規則：\n"
    "1. 先呼叫適當工具取得資料，再給出完整答案\n"
    "2. 在回答中用 [論文編號] 標注引用來源\n"
    "3. 語氣學術但易於理解，使用繁體中文\n"
    "4. 若工具回傳無結果，請告知用戶並建議補充相關論文\n"
)

# ── 顯式工具宣告（Gemini FunctionDeclaration 格式）────────────────────────

def _build_tool() -> types.Tool:
    """建立 Gemini Tool，包含所有工具的 FunctionDeclaration。"""
    return types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="search_papers",
            description="Search the local academic paper database by semantic similarity to the query.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING,
                                         description="Natural language search query"),
                    "n_results": types.Schema(type=types.Type.INTEGER,
                                              description="Number of papers to return (max 10)"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_paper_abstract",
            description="Get the full abstract and metadata of a specific paper by its ID.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "paper_id": types.Schema(type=types.Type.INTEGER,
                                             description="Integer ID obtained from search_papers"),
                },
                required=["paper_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_paper_chunks",
            description="Get full-text sections of a paper (requires PDF to be imported). Returns up to 6 chunks.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "paper_id": types.Schema(type=types.Type.INTEGER,
                                             description="Integer ID of the paper"),
                    "section_filter": types.Schema(type=types.Type.STRING,
                                                   description="Optional keyword to filter sections, e.g. 'method', 'result'"),
                },
                required=["paper_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_papers_by_tag",
            description="List papers that have a specific tag label.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "tag": types.Schema(type=types.Type.STRING,
                                        description="Tag name to filter by"),
                },
                required=["tag"],
            ),
        ),
    ])


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
        self._tool = _build_tool()

        # 本次 ask() 的追蹤狀態
        self._retrieved_papers: dict[int, Paper] = {}
        self._retrieved_chunks: list[SourceChunk] = []
        self._lock = threading.Lock()

    # ── 工具執行層（由 _run_fc_loop 呼叫）──────────────────────────────────

    def _execute_tool(self, name: str, args: dict) -> str:
        """根據工具名稱執行對應方法，回傳 JSON 字串。"""
        try:
            if name == "search_papers":
                return self._tool_search_papers(
                    query=str(args.get("query", "")),
                    n_results=int(args.get("n_results", 5)),
                )
            elif name == "get_paper_abstract":
                return self._tool_get_paper_abstract(paper_id=int(args["paper_id"]))
            elif name == "get_paper_chunks":
                return self._tool_get_paper_chunks(
                    paper_id=int(args["paper_id"]),
                    section_filter=str(args.get("section_filter", "")),
                )
            elif name == "list_papers_by_tag":
                return self._tool_list_papers_by_tag(tag=str(args.get("tag", "")))
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as ex:
            return json.dumps({"error": str(ex)})

    def _tool_search_papers(self, query: str, n_results: int = 5) -> str:
        n = min(n_results, 10)
        results = self.search.hybrid_search(query, n_results=n, use_rerank=True)
        out = []
        for sr in results:
            p = sr.paper
            with self._lock:
                self._retrieved_papers[p.id] = p
            out.append({
                "id": p.id,
                "title": p.title,
                "year": p.year,
                "tags": p.tags or [],
                "abstract_snippet": (p.abstract or "")[:200],
            })
        return json.dumps(out, ensure_ascii=False)

    def _tool_get_paper_abstract(self, paper_id: int) -> str:
        paper = self.sqlite_db.get_by_id(paper_id)
        if not paper:
            return json.dumps({"error": f"Paper {paper_id} not found"})
        with self._lock:
            self._retrieved_papers[paper.id] = paper
            if paper.abstract:
                self._retrieved_chunks.append(SourceChunk(
                    paper=paper, section="Abstract", page_num=0,
                    snippet=paper.abstract[:MAX_ABSTRACT_CHARS], is_fulltext=False,
                ))
        return json.dumps({
            "id": paper.id, "title": paper.title,
            "authors": paper.authors or [],
            "year": paper.year, "venue": paper.venue,
            "abstract": paper.abstract or "",
        }, ensure_ascii=False)

    def _tool_get_paper_chunks(self, paper_id: int, section_filter: str = "") -> str:
        paper = self.sqlite_db.get_by_id(paper_id)
        if not paper:
            return json.dumps({"error": f"Paper {paper_id} not found"})
        chunks = self.chunk_store.get_by_paper(paper_id)
        if not chunks:
            return json.dumps({"info": "No full-text chunks. Try get_paper_abstract instead."})
        if section_filter:
            sf = section_filter.lower()
            filtered = [c for c in chunks if sf in (c.section or "").lower()]
            if filtered:
                chunks = filtered
        chunks = chunks[:6]
        with self._lock:
            self._retrieved_papers[paper.id] = paper
            for c in chunks:
                self._retrieved_chunks.append(SourceChunk(
                    paper=paper, section=c.section or "全文",
                    page_num=c.page_num or 0,
                    snippet=c.chunk_text[:MAX_CHUNK_CHARS], is_fulltext=True,
                ))
        out = [{"section": c.section, "page": c.page_num,
                "text": c.chunk_text[:MAX_CHUNK_CHARS]} for c in chunks]
        return json.dumps(out, ensure_ascii=False)

    def _tool_list_papers_by_tag(self, tag: str) -> str:
        papers = self.sqlite_db.get_by_tag(tag)
        return json.dumps(
            [{"id": p.id, "title": p.title, "year": p.year} for p in papers[:20]],
            ensure_ascii=False,
        )

    # ── 主要問答介面 ─────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        history: Optional[list[ChatMessage]] = None,
        top_k: int = 5,
        filter_paper_ids: Optional[set[int]] = None,
        context_paper_ids: Optional[set[int]] = None,
    ) -> QAResult:
        history = history or []
        turn = self.memory.next_turn()

        with self._lock:
            self._retrieved_papers = {}
            self._retrieved_chunks = []

        top_memories = self.memory.get_top_k(query=question, k=TOP_K_INJECT)
        memory_text = self.memory.to_prompt(top_memories) if top_memories else ""
        system = _SYSTEM + (f"\n\n【對話記憶】\n{memory_text}" if memory_text else "")

        contents = self._build_contents(question, history)
        answer = self._run_fc_loop(contents, system)

        # 整理 source_chunks（去重）
        seen: set[tuple] = set()
        source_chunks: list[SourceChunk] = []
        for sc in self._retrieved_chunks:
            key = (sc.paper.id, sc.section)
            if key not in seen:
                seen.add(key)
                source_chunks.append(sc)
        source_chunks = source_chunks[:top_k]

        # fallback：若無 chunks，用摘要
        if not source_chunks:
            for paper in list(self._retrieved_papers.values())[:top_k]:
                if paper.abstract:
                    source_chunks.append(SourceChunk(
                        paper=paper, section="Abstract", page_num=0,
                        snippet=paper.abstract[:MAX_ABSTRACT_CHARS], is_fulltext=False,
                    ))

        self.skill.extract_async(turn, question, answer, source_chunks, self.memory)
        return QAResult(answer=answer, source_chunks=source_chunks, query=question)

    def suggest_followups(self, question: str, answer: str, n: int = 2) -> list[str]:
        prompt = (
            f"用戶剛問了：「{question}」\n"
            f"AI 回答了：「{answer[:400]}」\n\n"
            f"請根據以上問答內容，提出 {n} 個值得繼續深入的追問。\n"
            "要求：每個問題獨立一行，不要加編號或符號，直接是問句，20字以內。\n"
            f"只輸出 {n} 行問句，不要其他文字。"
        )
        try:
            response = self._gemini.client.models.generate_content(
                model=self._gemini.model_name, contents=prompt,
            )
            lines = [l.strip() for l in response.text.strip().splitlines() if l.strip()]
            return lines[:n]
        except Exception:
            return []

    # ── 內部方法 ─────────────────────────────────────────────────────────

    def _build_contents(self, question: str, history: list[ChatMessage]) -> list:
        contents = []
        for msg in history[-(MAX_HISTORY_TURNS * 2):]:
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

    def _run_fc_loop(self, contents: list, system: str) -> str:
        """
        手動多輪 Function Calling 迴圈。
        - 使用顯式 FunctionDeclaration（不傳 Python callable，避免 SDK auto-execute）
        - function response 使用 role='user'（Gemini API 規範）
        """
        fc_config = types.GenerateContentConfig(
            tools=[self._tool],
            system_instruction=system,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        # 最終回答階段不帶工具（避免模型繼續呼叫）
        final_config = types.GenerateContentConfig(system_instruction=system)

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._gemini.client.models.generate_content(
                    model=self._gemini.model_name,
                    contents=contents,
                    config=fc_config,
                )
            except Exception as e:
                return f"⚠️ Gemini API 呼叫失敗：{e}"

            candidate = response.candidates[0]
            model_content = candidate.content
            parts = model_content.parts

            # 收集 function calls 和 text parts
            fc_parts = [p for p in parts if getattr(p, "function_call", None) is not None]
            text_parts = [p for p in parts if getattr(p, "text", None)]

            # 沒有 function call → 最終答案
            if not fc_parts:
                return "\n".join(p.text for p in text_parts).strip() or "（無法生成回答）"

            # 加入 model 的這輪輸出到歷史
            contents.append(model_content)

            # 執行所有 function calls，收集 responses
            fn_response_parts = []
            for fc_part in fc_parts:
                fc = fc_part.function_call
                result_str = self._execute_tool(fc.name, dict(fc.args) if fc.args else {})
                fn_response_parts.append(types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result_str},
                    )
                ))

            # ⚠️ 關鍵：function response 必須用 role='user'（Gemini API 規範）
            contents.append(types.Content(
                role="user",
                parts=fn_response_parts,
            ))

        # 超過 MAX_TOOL_ROUNDS：強制給最終回答（不帶工具避免繼續呼叫）
        try:
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text="請根據以上工具查詢結果，給出完整的最終回答。")],
            ))
            final = self._gemini.client.models.generate_content(
                model=self._gemini.model_name,
                contents=contents,
                config=final_config,
            )
            return final.text.strip()
        except Exception as e:
            return f"⚠️ 最終回答生成失敗：{e}"
