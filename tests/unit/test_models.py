"""
Unit tests — smartpaper/models.py
驗證 Pydantic 資料模型的欄位預設值、屬性與行為
"""
import pytest
from smartpaper.models import Paper, ProcessingStatus, SearchResult
from smartpaper.services.qa_service import QAResult, SourceChunk


class TestPaper:
    def test_minimal_creation(self):
        paper = Paper(title="Test Paper")
        assert paper.title == "Test Paper"
        assert paper.abstract is None
        assert paper.doi is None
        assert paper.tags == []
        assert paper.authors == []

    def test_tags_default_list(self):
        p1 = Paper(title="A")
        p2 = Paper(title="B")
        p1.tags.append("X")
        assert "X" not in p2.tags  # 獨立 list，不共享

    def test_full_creation(self):
        paper = Paper(
            title="BERT",
            abstract="Bidirectional encoder",
            doi="10.1234/bert",
            tags=["NLP", "BERT"],
            authors=["Devlin"],
            venue="NAACL",
            year=2019,
            citation_count=50000,
        )
        assert paper.year == 2019
        assert paper.citation_count == 50000
        assert "NLP" in paper.tags

    def test_id_is_none_by_default(self):
        paper = Paper(title="No ID Yet")
        assert paper.id is None

    def test_title_required(self):
        with pytest.raises(Exception):
            Paper()  # title 必填


class TestProcessingStatus:
    def test_progress_zero_when_nothing_done(self):
        s = ProcessingStatus(total=10, processed=0, success=0, failed=0)
        assert s.progress == 0.0

    def test_progress_100_when_all_done(self):
        s = ProcessingStatus(total=10, processed=10, success=9, failed=1)
        assert s.progress == 100.0

    def test_progress_partial(self):
        s = ProcessingStatus(total=10, processed=5, success=5, failed=0)
        assert s.progress == 50.0

    def test_progress_safe_when_total_zero(self):
        s = ProcessingStatus(total=0, processed=0, success=0, failed=0)
        assert s.progress == 0.0

    def test_errors_default_empty(self):
        s = ProcessingStatus(total=5, processed=0, success=0, failed=0)
        assert s.errors == []


class TestSearchResult:
    def test_creation(self, sample_paper):
        sr = SearchResult(paper=sample_paper, score=0.85)
        assert sr.score == 0.85
        assert sr.paper.title == sample_paper.title

    def test_score_range(self, sample_paper):
        sr = SearchResult(paper=sample_paper, score=1.0)
        assert 0.0 <= sr.score <= 1.0


class TestQAResult:
    def test_sources_dedup(self):
        """QAResult.sources 應去除重複論文"""
        from smartpaper.services.qa_service import QAResult, SourceChunk
        p1 = Paper(id=1, title="Paper One")
        p2 = Paper(id=2, title="Paper Two")

        sc1 = SourceChunk(paper=p1, section="Introduction", page_num=1, snippet="text1", is_fulltext=True)
        sc2 = SourceChunk(paper=p1, section="Methods", page_num=2, snippet="text2", is_fulltext=True)
        sc3 = SourceChunk(paper=p2, section="Abstract", page_num=0, snippet="text3", is_fulltext=False)

        result = QAResult(answer="test", source_chunks=[sc1, sc2, sc3])
        sources = result.sources
        assert len(sources) == 2
        titles = {s.title for s in sources}
        assert "Paper One" in titles
        assert "Paper Two" in titles

    def test_sources_empty_when_no_chunks(self):
        from smartpaper.services.qa_service import QAResult
        result = QAResult(answer="No sources")
        assert result.sources == []

    def test_query_stored(self):
        from smartpaper.services.qa_service import QAResult
        result = QAResult(answer="answer", query="what is NLP?")
        assert result.query == "what is NLP?"
