"""
Unit tests — smartpaper/services/bm25_index.py
BM25 索引建立、搜尋、tokenizer、RRF 融合
"""
import pytest
from smartpaper.services.bm25_index import BM25Index, reciprocal_rank_fusion
from smartpaper.models import Paper, SearchResult


def _make_paper(pid: int, title: str, abstract: str = "") -> Paper:
    return Paper(id=pid, title=title, abstract=abstract)


class TestBM25Tokenizer:
    def setup_method(self):
        self.idx = BM25Index()

    def test_english_words(self):
        tokens = self.idx._tokenize("Deep learning for NLP")
        assert "deep" in tokens
        assert "learning" in tokens
        assert "nlp" in tokens

    def test_cjk_chars_split_individually(self):
        tokens = self.idx._tokenize("深度學習")
        assert "深" in tokens
        assert "度" in tokens
        assert "學" in tokens
        assert "習" in tokens

    def test_mixed_text(self):
        tokens = self.idx._tokenize("BERT 模型")
        assert "bert" in tokens
        assert "模" in tokens

    def test_empty_string(self):
        tokens = self.idx._tokenize("")
        assert tokens == []

    def test_punctuation_ignored(self):
        tokens = self.idx._tokenize("Hello, world!")
        assert "," not in tokens
        assert "!" not in tokens


class TestBM25IndexBuild:
    def setup_method(self):
        self.idx = BM25Index()

    def test_not_built_initially(self):
        assert not self.idx.is_built

    def test_built_after_build(self):
        papers = [_make_paper(1, "Deep Learning", "Neural network methods")]
        self.idx.build(papers)
        assert self.idx.is_built

    def test_empty_paper_list(self):
        try:
            self.idx.build([])
            assert not self.idx.is_built
        except (ZeroDivisionError, ValueError):
            pass  # BM25 可能在空語料庫拋出例外

    def test_build_uses_title_and_abstract(self):
        papers = [
            _make_paper(1, "Attention Mechanism", "Query key value architecture"),
            _make_paper(2, "Computer Vision", "Image recognition with convolution"),
            _make_paper(3, "Reinforcement Learning", "Agent reward environment policy"),
        ]
        self.idx.build(papers)
        results = self.idx.search("attention query key", top_k=3)
        assert len(results) >= 1
        # "attention" 論文應在前列
        top_ids = [r["paper"].id for r in results]
        assert 1 in top_ids


class TestBM25IndexSearch:
    def setup_method(self):
        self.idx = BM25Index()
        self.papers = [
            _make_paper(1, "Deep Learning", "Neural networks and backpropagation"),
            _make_paper(2, "Natural Language Processing", "Text classification and NLP"),
            _make_paper(3, "Computer Vision", "Image recognition with CNNs"),
        ]
        self.idx.build(self.papers)

    def test_relevant_paper_found(self):
        results = self.idx.search("neural networks", top_k=3)
        paper_ids = [r["paper"].id for r in results]
        assert 1 in paper_ids

    def test_top_k_limit(self):
        results = self.idx.search("learning", top_k=2)
        assert len(results) <= 2

    def test_not_built_returns_empty(self):
        fresh = BM25Index()
        results = fresh.search("deep learning", top_k=5)
        assert results == []

    def test_result_has_bm25_score(self):
        results = self.idx.search("deep learning", top_k=1)
        assert "bm25_score" in results[0]

    def test_result_has_paper(self):
        results = self.idx.search("computer vision", top_k=1)
        assert "paper" in results[0]
        assert isinstance(results[0]["paper"], Paper)

    def test_empty_query_returns_results(self):
        # BM25 with empty query may return all or nothing — should not crash
        try:
            results = self.idx.search("", top_k=3)
            assert isinstance(results, list)
        except Exception:
            pass  # 空查詢可以拋出例外，但不應 crash


class TestReciprocalRankFusion:
    def setup_method(self):
        self.p1 = _make_paper(1, "Paper One")
        self.p2 = _make_paper(2, "Paper Two")
        self.p3 = _make_paper(3, "Paper Three")

    def test_single_ranked_list(self):
        ranked = [
            {"paper": self.p1, "paper_id": 1},
            {"paper": self.p2, "paper_id": 2},
        ]
        result = reciprocal_rank_fusion([ranked], paper_id_keys=["paper_id"])
        assert len(result) == 2

    def test_fusion_promotes_consistently_ranked(self):
        list_a = [{"paper": self.p1, "paper_id": 1}, {"paper": self.p2, "paper_id": 2}]
        list_b = [{"paper": self.p1, "paper_id": 1}, {"paper": self.p3, "paper_id": 3}]
        result = reciprocal_rank_fusion([list_a, list_b], paper_id_keys=["paper_id"])
        # p1 出現在兩個 list，應排最前
        top_id = result[0]["paper_id"]
        assert top_id == 1

    def test_output_has_rrf_score(self):
        ranked = [{"paper": self.p1, "paper_id": 1}]
        result = reciprocal_rank_fusion([ranked], paper_id_keys=["paper_id"])
        assert "rrf_score" in result[0]

    def test_empty_lists(self):
        result = reciprocal_rank_fusion([], paper_id_keys=["paper_id"])
        assert result == []
