"""
Integration tests — smartpaper/services/pipeline.py
Mock 所有外部 API，驗證完整處理流程
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.services.pipeline import Pipeline
from smartpaper.models import Paper, ProcessingStatus, CrossrefResponse


def _make_crossref_result(title="Test Paper", doi="10.1234/test", abstract="Abstract."):
    return CrossrefResponse(
        title=title,
        doi=doi,
        abstract=abstract,
        authors=["Author A"],
        published_date="2023",
        journal="ICML",
    )


def _build_pipeline(db, mock_vdb=None):
    """建立使用 mock 外部依賴的 Pipeline"""
    if mock_vdb is None:
        mock_vdb = MagicMock()
        mock_vdb.add = MagicMock()
        mock_vdb.count.return_value = 0

    mock_crossref = MagicMock()
    mock_crossref.search_by_title.return_value = _make_crossref_result()

    mock_tagger = MagicMock()
    mock_tagger.tag_paper.return_value = ["NLP", "Deep Learning"]

    pipeline = Pipeline(
        sqlite_db=db,
        vector_db=mock_vdb,
        crossref_api=mock_crossref,
        auto_tagger=mock_tagger,
    )
    return pipeline, mock_crossref, mock_tagger, mock_vdb


class TestProcessPapersList:
    def test_success_path(self, db):
        pipeline, crossref, tagger, vdb = _build_pipeline(db)
        papers = [
            {"title": "Attention Is All You Need", "abstract": "Transformer paper."},
            {"title": "BERT Pre-training", "abstract": "Bidirectional LM."},
        ]
        status = pipeline.process_papers_list(
            papers=papers,
            skip_existing=False,
            generate_tags=True,
            fetch_missing=False,
        )
        assert isinstance(status, ProcessingStatus)
        assert status.total == 2
        assert status.success == 2
        assert status.failed == 0

    def test_skips_existing_doi(self, db, sample_paper):
        pid = db.insert(sample_paper)
        pipeline, *_ = _build_pipeline(db)
        papers = [{"title": sample_paper.title, "doi": sample_paper.doi, "abstract": ""}]
        status = pipeline.process_papers_list(
            papers=papers,
            skip_existing=True,
            generate_tags=False,
            fetch_missing=False,
        )
        # 已存在的論文應被跳過，DB 數量不增
        assert db.count() == 1

    def test_tags_generated_when_enabled(self, db):
        pipeline, crossref, tagger, vdb = _build_pipeline(db)
        papers = [{"title": "New Paper", "abstract": "Some abstract."}]
        pipeline.process_papers_list(
            papers=papers, skip_existing=False, generate_tags=True, fetch_missing=False
        )
        tagger.tag_paper.assert_called()

    def test_tags_not_generated_when_disabled(self, db):
        pipeline, crossref, tagger, vdb = _build_pipeline(db)
        papers = [{"title": "Paper No Tags", "abstract": "Abstract."}]
        pipeline.process_papers_list(
            papers=papers, skip_existing=False, generate_tags=False, fetch_missing=False
        )
        tagger.tag_paper.assert_not_called()

    def test_vector_added_for_each_paper(self, db):
        pipeline, crossref, tagger, vdb = _build_pipeline(db)
        papers = [
            {"title": "Paper A", "abstract": "Abstract A."},
            {"title": "Paper B", "abstract": "Abstract B."},
        ]
        pipeline.process_papers_list(
            papers=papers, skip_existing=False, generate_tags=False, fetch_missing=False
        )
        assert vdb.add.call_count >= 2

    def test_progress_callback_called(self, db):
        pipeline, *_ = _build_pipeline(db)
        callback_calls = []
        papers = [
            {"title": "Paper X", "abstract": "Abs X."},
            {"title": "Paper Y", "abstract": "Abs Y."},
        ]
        pipeline.process_papers_list(
            papers=papers,
            skip_existing=False,
            generate_tags=False,
            fetch_missing=False,
            progress_callback=lambda s: callback_calls.append(s),
        )
        assert len(callback_calls) > 0
        assert all(isinstance(s, ProcessingStatus) for s in callback_calls)

    def test_empty_input(self, db):
        pipeline, *_ = _build_pipeline(db)
        status = pipeline.process_papers_list(papers=[], skip_existing=False, generate_tags=False)
        assert status.total == 0
        assert status.success == 0

    def test_crossref_fetch_when_no_abstract(self, db):
        pipeline, crossref, tagger, vdb = _build_pipeline(db)
        papers = [{"title": "Paper Without Abstract"}]
        pipeline.process_papers_list(
            papers=papers, skip_existing=False, generate_tags=False, fetch_missing=True
        )
        crossref.search_by_title.assert_called()

    def test_crossref_skipped_when_abstract_provided(self, db):
        pipeline, crossref, tagger, vdb = _build_pipeline(db)
        papers = [{"title": "Paper With Abstract", "abstract": "Already have it."}]
        pipeline.process_papers_list(
            papers=papers, skip_existing=False, generate_tags=False, fetch_missing=False
        )
        crossref.search_by_title.assert_not_called()


class TestGetStatistics:
    def test_returns_dict(self, db):
        pipeline, *_ = _build_pipeline(db)
        stats = pipeline.get_statistics()
        assert isinstance(stats, dict)

    def test_total_papers_correct(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        pipeline, *_ = _build_pipeline(db)
        stats = pipeline.get_statistics()
        assert stats.get("total_papers", 0) == len(sample_papers)

    def test_unique_tags_counted(self, db, sample_papers):
        for p in sample_papers:
            db.insert(p)
        pipeline, *_ = _build_pipeline(db)
        stats = pipeline.get_statistics()
        assert stats.get("unique_tags", 0) > 0
