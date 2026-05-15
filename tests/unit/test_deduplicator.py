"""
Unit tests — smartpaper/services/deduplicator.py
重複論文偵測與合併邏輯
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.services.deduplicator import Deduplicator, _normalize, _similarity
from smartpaper.models import Paper


def _make_paper(pid: int, title: str, doi: str = None, tags: list = None) -> Paper:
    return Paper(id=pid, title=title, doi=doi, tags=tags or [])


class TestDeduplicatorNormalize:
    def test_lowercase(self):
        assert _normalize("Hello World") == "hello world"

    def test_strip_punctuation(self):
        result = _normalize("Hello, World!")
        assert "," not in result
        assert "!" not in result

    def test_collapse_whitespace(self):
        result = _normalize("Hello   World")
        assert "  " not in result

    def test_empty_string(self):
        assert _normalize("") == ""


class TestDeduplicatorSimilarity:
    def test_identical_titles_score_one(self):
        score = _similarity("deep learning", "deep learning")
        assert score == pytest.approx(1.0)

    def test_completely_different_low_score(self):
        score = _similarity("deep learning", "quantum physics")
        assert score < 0.5

    def test_slight_variation_high_score(self):
        score = _similarity(
            "Attention Is All You Need",
            "Attention is all you need",
        )
        assert score > 0.9

    def test_empty_strings(self):
        score = _similarity("", "")
        assert isinstance(score, float)


class TestDeduplicatorFindDuplicates:
    def _make_mock_db(self, papers: list[Paper]):
        db = MagicMock()
        db.get_all.return_value = papers
        return db

    def test_no_duplicates_returns_empty(self):
        papers = [
            _make_paper(1, "Deep Learning"),
            _make_paper(2, "Natural Language Processing"),
            _make_paper(3, "Computer Vision"),
        ]
        dup = Deduplicator(sqlite_db=self._make_mock_db(papers))
        groups = dup.find_duplicates(threshold=0.85)
        assert groups == []

    def test_identical_titles_are_duplicates(self):
        papers = [
            _make_paper(1, "Attention Is All You Need"),
            _make_paper(2, "Attention Is All You Need"),
        ]
        dup = Deduplicator(sqlite_db=self._make_mock_db(papers))
        groups = dup.find_duplicates(threshold=0.85)
        assert len(groups) >= 1
        assert len(groups[0]) >= 2

    def test_same_doi_are_duplicates(self):
        papers = [
            _make_paper(1, "Paper A", doi="10.1234/same"),
            _make_paper(2, "Paper B (extended)", doi="10.1234/same"),
        ]
        dup = Deduplicator(sqlite_db=self._make_mock_db(papers))
        groups = dup.find_duplicates(threshold=0.85)
        assert len(groups) >= 1

    def test_below_threshold_not_grouped(self):
        papers = [
            _make_paper(1, "Machine Learning Basics"),
            _make_paper(2, "Deep Reinforcement Learning Advanced"),
        ]
        dup = Deduplicator(sqlite_db=self._make_mock_db(papers))
        groups = dup.find_duplicates(threshold=0.85)
        assert groups == []


class TestDeduplicatorMerge:
    def _make_mock_db(self, papers_by_id: dict):
        db = MagicMock()
        db.get_by_id.side_effect = lambda pid: papers_by_id.get(pid)
        return db

    def test_merge_calls_delete_for_duplicates(self):
        keep = _make_paper(1, "Paper One", tags=["NLP"])
        dup_p = _make_paper(2, "Paper One Duplicate", tags=["ML"])
        db = self._make_mock_db({1: keep, 2: dup_p})
        dedup = Deduplicator(sqlite_db=db)
        dedup.merge(keep_id=1, delete_ids=[2])
        db.delete.assert_called_with(2)

    def test_merge_transfers_tags(self):
        keep = _make_paper(1, "Paper One", tags=["NLP"])
        dup_p = _make_paper(2, "Duplicate", tags=["ML", "Extra"])
        db = self._make_mock_db({1: keep, 2: dup_p})
        dedup = Deduplicator(sqlite_db=db)
        dedup.merge(keep_id=1, delete_ids=[2])
        # update 應被呼叫（合併標籤後更新 keep）
        db.update.assert_called()

    def test_merge_returns_deleted_count(self):
        keep = _make_paper(1, "Paper One", tags=[])
        dup_p = _make_paper(2, "Duplicate", tags=[])
        db = self._make_mock_db({1: keep, 2: dup_p})
        dedup = Deduplicator(sqlite_db=db)
        count = dedup.merge(keep_id=1, delete_ids=[2])
        assert count == 1
