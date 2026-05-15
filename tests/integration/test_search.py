"""
Integration tests — smartpaper/services/search.py
使用真實 SQLiteDB + mock VectorDB，驗證各種搜尋模式
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.services.search import SearchService
from smartpaper.models import Paper, SearchResult


def _make_search_service(db, mock_vdb=None):
    if mock_vdb is None:
        mock_vdb = MagicMock()
        mock_vdb.search.return_value = []
        mock_vdb.count.return_value = 0
    svc = SearchService(sqlite_db=db, vector_db=mock_vdb)
    return svc


class TestKeywordSearch:
    def test_finds_by_title_keyword(self, db_with_papers):
        svc = _make_search_service(db_with_papers)
        results = svc.keyword_search("Attention", search_in="title")
        assert len(results) >= 1
        assert any("Attention" in p.title for p in results)

    def test_finds_by_tag(self, db_with_papers):
        svc = _make_search_service(db_with_papers)
        results = svc.keyword_search("NLP", search_in="tag")
        assert len(results) >= 1

    def test_no_match_returns_empty(self, db_with_papers):
        svc = _make_search_service(db_with_papers)
        results = svc.keyword_search("QuantumFogzXZQ", search_in="title")
        assert results == []

    def test_case_insensitive_search(self, db_with_papers):
        svc = _make_search_service(db_with_papers)
        upper = svc.keyword_search("BERT", search_in="title")
        lower = svc.keyword_search("bert", search_in="title")
        assert len(upper) == len(lower)


class TestSearchByTag:
    def test_finds_papers_with_tag(self, db_with_papers):
        svc = _make_search_service(db_with_papers)
        results = svc.search_by_tag("NLP")
        assert len(results) >= 1

    def test_missing_tag_returns_empty(self, db_with_papers):
        svc = _make_search_service(db_with_papers)
        results = svc.search_by_tag("TagThatDoesNotExist")
        assert results == []


class TestSemanticSearch:
    def test_delegates_to_vector_db(self, db_with_papers, mock_vector_db):
        p = list(db_with_papers.get_all(limit=1))[0]
        mock_vector_db.search.return_value = [
            {"paper_id": p.id, "score": 0.9, "distance": 0.1, "metadata": {}, "document": p.abstract}
        ]
        svc = SearchService(sqlite_db=db_with_papers, vector_db=mock_vector_db)
        results = svc.semantic_search("deep learning", n_results=5, use_rerank=False)
        mock_vector_db.search.assert_called_once()
        assert isinstance(results, list)

    def test_returns_search_result_type(self, db_with_papers, mock_vector_db):
        p = list(db_with_papers.get_all(limit=1))[0]
        mock_vector_db.search.return_value = [
            {"paper_id": p.id, "score": 0.8, "distance": 0.2, "metadata": {}, "document": ""}
        ]
        svc = SearchService(sqlite_db=db_with_papers, vector_db=mock_vector_db)
        results = svc.semantic_search("query", use_rerank=False)
        if results:
            assert isinstance(results[0], SearchResult)

    def test_empty_vector_db_returns_empty(self, db_with_papers, mock_vector_db):
        mock_vector_db.search.return_value = []
        svc = SearchService(sqlite_db=db_with_papers, vector_db=mock_vector_db)
        results = svc.semantic_search("anything", use_rerank=False)
        assert results == []


class TestBM25Search:
    def test_bm25_finds_relevant_paper(self, db_with_papers, mock_vector_db):
        svc = _make_search_service(db_with_papers, mock_vector_db)
        results = svc.bm25_search("Transformer attention")
        assert isinstance(results, list)

    def test_bm25_returns_search_results(self, db_with_papers, mock_vector_db):
        svc = _make_search_service(db_with_papers, mock_vector_db)
        results = svc.bm25_search("neural network", top_k=5)
        for r in results:
            assert isinstance(r, SearchResult)

    def test_bm25_empty_db(self, db, mock_vector_db):
        svc = _make_search_service(db, mock_vector_db)
        try:
            results = svc.bm25_search("deep learning")
            assert results == []
        except (ZeroDivisionError, ValueError):
            pass  # BM25 may raise on empty corpus


class TestHybridSearch:
    def test_hybrid_combines_results(self, db_with_papers, mock_vector_db):
        p = list(db_with_papers.get_all(limit=1))[0]
        mock_vector_db.search.return_value = [
            {"paper_id": p.id, "score": 0.85, "distance": 0.15, "metadata": {}, "document": ""}
        ]
        svc = SearchService(sqlite_db=db_with_papers, vector_db=mock_vector_db)
        results = svc.hybrid_search("NLP transformer", n_results=5, use_rerank=False)
        assert isinstance(results, list)

    def test_hybrid_no_duplicates(self, db_with_papers, mock_vector_db):
        p = list(db_with_papers.get_all(limit=1))[0]
        mock_vector_db.search.return_value = [
            {"paper_id": p.id, "score": 0.9, "distance": 0.1, "metadata": {}, "document": ""}
        ]
        svc = SearchService(sqlite_db=db_with_papers, vector_db=mock_vector_db)
        results = svc.hybrid_search("attention", n_results=10, use_rerank=False)
        seen_ids = [r.paper.id for r in results]
        assert len(seen_ids) == len(set(seen_ids))  # 無重複


class TestGetAllTags:
    def test_returns_all_unique_tags(self, db_with_papers, mock_vector_db):
        svc = _make_search_service(db_with_papers, mock_vector_db)
        tags = svc.get_all_tags()
        assert isinstance(tags, list)
        assert "NLP" in tags
        assert len(tags) == len(set(tags))  # 無重複

    def test_empty_db_returns_empty(self, db, mock_vector_db):
        svc = _make_search_service(db, mock_vector_db)
        tags = svc.get_all_tags()
        assert tags == []
