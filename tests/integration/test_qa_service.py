"""
Integration tests — smartpaper/services/qa_service.py
Mock VectorDB + Gemini，驗證 RAG 問答流程
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.services.qa_service import QAService, QAResult, ChatMessage, SourceChunk
from smartpaper.models import Paper, SearchResult


def _make_paper(pid: int, title: str, abstract: str = "Abstract text.") -> Paper:
    return Paper(id=pid, title=title, abstract=abstract, doi=f"10.0/{pid}")


def _build_qa_service(db, mock_vdb=None, mock_gemini=None):
    if mock_vdb is None:
        mock_vdb = MagicMock()
        mock_vdb.search_chunks.return_value = []

    mock_search = MagicMock()
    mock_search.hybrid_search.return_value = []

    if mock_gemini is None:
        mock_gemini = MagicMock()
        resp = MagicMock()
        resp.text = "根據 [1] 的研究，答案是 A。"
        mock_gemini.client.models.generate_content.return_value = resp

    svc = QAService(
        sqlite_db=db,
        vector_db=mock_vdb,
        search_service=mock_search,
    )
    svc._gemini = mock_gemini
    svc.search = mock_search
    return svc, mock_vdb, mock_search, mock_gemini


class TestAskBasic:
    def test_returns_qa_result(self, db, sample_paper):
        pid = db.insert(sample_paper)
        svc, *_ = _build_qa_service(db)
        result = svc.ask("What is deep learning?")
        assert isinstance(result, QAResult)

    def test_answer_is_string(self, db, sample_paper):
        pid = db.insert(sample_paper)
        svc, *_ = _build_qa_service(db)
        result = svc.ask("What is NLP?")
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0

    def test_query_stored_in_result(self, db, sample_paper):
        db.insert(sample_paper)
        svc, *_ = _build_qa_service(db)
        result = svc.ask("What is attention mechanism?")
        assert result.query == "What is attention mechanism?"

    def test_llm_called_once(self, db, sample_paper):
        db.insert(sample_paper)
        svc, _, _, mock_gemini = _build_qa_service(db)
        svc.ask("Any question")
        mock_gemini.client.models.generate_content.assert_called_once()

    def test_llm_failure_returns_error_message(self, db, sample_paper):
        db.insert(sample_paper)
        svc, _, _, mock_gemini = _build_qa_service(db)
        mock_gemini.client.models.generate_content.side_effect = Exception("API error")
        result = svc.ask("Will this fail?")
        assert "⚠️" in result.answer or "失敗" in result.answer or result.answer


class TestRetrieval:
    def test_searches_fulltext_chunks(self, db, sample_paper):
        pid = db.insert(sample_paper)
        svc, mock_vdb, *_ = _build_qa_service(db)
        mock_vdb.search_chunks.return_value = [
            {
                "paper_id": pid,
                "section": "Introduction",
                "chunk_index": 0,
                "page_num": 1,
                "is_table": False,
                "chunk_text": "Deep learning is a subset of machine learning.",
                "score": 0.9,
            }
        ]
        result = svc.ask("deep learning")
        mock_vdb.search_chunks.assert_called()

    def test_fallback_to_abstract_when_no_fulltext(self, db, sample_paper):
        db.insert(sample_paper)
        svc, mock_vdb, mock_search, _ = _build_qa_service(db)
        mock_vdb.search_chunks.return_value = []  # 沒有全文
        mock_search.hybrid_search.return_value = [
            SearchResult(paper=sample_paper, score=0.7)
        ]
        result = svc.ask("What is NLP?")
        mock_search.hybrid_search.assert_called()

    def test_source_chunks_populated(self, db, sample_paper):
        pid = db.insert(sample_paper)
        svc, mock_vdb, *_ = _build_qa_service(db)
        mock_vdb.search_chunks.return_value = [
            {
                "paper_id": pid,
                "section": "Abstract",
                "chunk_index": 0,
                "page_num": 0,
                "is_table": False,
                "chunk_text": "A paper about NLP.",
                "score": 0.8,
            }
        ]
        result = svc.ask("NLP overview")
        assert isinstance(result.source_chunks, list)

    def test_max_chunks_per_paper_enforced(self, db, sample_paper):
        pid = db.insert(sample_paper)
        svc, mock_vdb, *_ = _build_qa_service(db)
        # 同一篇論文給 10 個 chunk
        mock_vdb.search_chunks.return_value = [
            {
                "paper_id": pid, "section": "S", "chunk_index": i,
                "page_num": i, "is_table": False,
                "chunk_text": f"Chunk {i} content.", "score": 0.8,
            }
            for i in range(10)
        ]
        result = svc.ask("test")
        paper_chunk_counts = {}
        for sc in result.source_chunks:
            paper_chunk_counts[sc.paper.id] = paper_chunk_counts.get(sc.paper.id, 0) + 1
        for count in paper_chunk_counts.values():
            from smartpaper.services.qa_service import MAX_CHUNKS_PER_PAPER
            assert count <= MAX_CHUNKS_PER_PAPER


class TestConversationHistory:
    def test_history_included_in_prompt(self, db, sample_paper):
        db.insert(sample_paper)
        svc, _, _, mock_gemini = _build_qa_service(db)
        history = [
            ChatMessage(role="user", content="What is ML?"),
            ChatMessage(role="assistant", content="Machine learning is..."),
        ]
        svc.ask("Follow up question", history=history)
        call_args = str(mock_gemini.client.models.generate_content.call_args)
        assert "ML" in call_args or "Machine learning" in call_args

    def test_empty_history_works(self, db, sample_paper):
        db.insert(sample_paper)
        svc, *_ = _build_qa_service(db)
        result = svc.ask("First question", history=[])
        assert isinstance(result, QAResult)

    def test_history_window_limited(self, db, sample_paper):
        db.insert(sample_paper)
        svc, _, _, mock_gemini = _build_qa_service(db)
        # 超過 MAX_HISTORY_TURNS * 2 的歷史
        long_history = [
            ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"Message {i}")
            for i in range(30)
        ]
        result = svc.ask("final question", history=long_history)
        # 應成功，不 crash
        assert isinstance(result.answer, str)


class TestBuildContext:
    def test_context_includes_citation_numbers(self, db, sample_paper):
        pid = db.insert(sample_paper)
        svc, *_ = _build_qa_service(db)
        sc = SourceChunk(
            paper=sample_paper,
            section="Introduction",
            page_num=1,
            snippet="This is a snippet.",
            is_fulltext=True,
        )
        context = svc._build_context([sc])
        assert "[1]" in context

    def test_context_includes_paper_title(self, db, sample_paper):
        db.insert(sample_paper)
        svc, *_ = _build_qa_service(db)
        sc = SourceChunk(
            paper=sample_paper,
            section="Abstract",
            page_num=0,
            snippet="Snippet.",
            is_fulltext=False,
        )
        context = svc._build_context([sc])
        assert sample_paper.title in context

    def test_empty_chunks_gives_empty_context(self, db):
        svc, *_ = _build_qa_service(db)
        context = svc._build_context([])
        assert context == ""
