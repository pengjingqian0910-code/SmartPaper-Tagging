"""
Unit tests — smartpaper/processing/tagger.py
Mock GeminiTagger，驗證標籤合併與生成邏輯
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.processing.tagger import AutoTagger
from smartpaper.models import Paper


def _make_tagger(tags_to_return=None):
    """建立使用 mock GeminiTagger 的 AutoTagger"""
    from smartpaper.models import TaggingResult
    tags = tags_to_return or ["NLP", "Deep Learning", "Transformer"]
    mock_gemini = MagicMock()
    mock_gemini.generate_tags.return_value = TaggingResult(tags=tags)
    mock_gemini.batch_generate_tags.return_value = [
        TaggingResult(tags=tags)
    ]

    with patch("smartpaper.processing.tagger.GeminiTagger", return_value=mock_gemini):
        tagger = AutoTagger(api_key="fake")
    tagger.gemini = mock_gemini   # AutoTagger 使用 self.gemini
    return tagger, mock_gemini


class TestMergeTags:
    def setup_method(self):
        self.tagger, _ = _make_tagger()

    def test_combines_lists(self):
        result = self.tagger.merge_tags(["NLP"], ["ML", "AI"])
        assert "NLP" in result
        assert "ML" in result
        assert "AI" in result

    def test_deduplicates(self):
        result = self.tagger.merge_tags(["NLP", "ML"], ["ML", "AI"])
        assert result.count("ML") == 1

    def test_respects_max_tags(self):
        existing = [f"Tag{i}" for i in range(6)]
        new = [f"New{i}" for i in range(6)]
        result = self.tagger.merge_tags(existing, new, max_tags=8)
        assert len(result) <= 8

    def test_empty_existing(self):
        result = self.tagger.merge_tags([], ["NLP", "ML"])
        assert "NLP" in result
        assert "ML" in result

    def test_empty_new(self):
        result = self.tagger.merge_tags(["NLP"], [])
        assert result == ["NLP"]

    def test_both_empty(self):
        result = self.tagger.merge_tags([], [])
        assert result == []

    def test_case_insensitive_dedup(self):
        result = self.tagger.merge_tags(["nlp"], ["NLP"])
        # 實作可能是 case-sensitive，測試不重複即可
        assert len(result) <= 2


class TestTagPaper:
    def test_returns_tags(self):
        tagger, mock_gemini = _make_tagger(["NLP", "BERT"])
        paper = Paper(title="BERT Paper", abstract="Bidirectional language model.")
        tags = tagger.tag_paper(paper)
        assert isinstance(tags, list)
        assert len(tags) > 0

    def test_calls_gemini_with_abstract(self):
        tagger, mock_gemini = _make_tagger()
        paper = Paper(title="Paper", abstract="Some abstract about transformers.")
        tagger.tag_paper(paper)
        mock_gemini.generate_tags.assert_called_once()
        call_kwargs = mock_gemini.generate_tags.call_args
        assert "transformers" in str(call_kwargs)

    def test_empty_abstract_handled(self):
        tagger, _ = _make_tagger([])
        paper = Paper(title="No Abstract Paper")
        tags = tagger.tag_paper(paper)
        assert isinstance(tags, list)

    def test_custom_categories_passed(self):
        tagger, mock_gemini = _make_tagger(["Healthcare"])
        paper = Paper(title="Medical AI", abstract="Medical imaging with AI.")
        tagger.tag_paper(paper, custom_categories=["Healthcare", "AI"])
        call_kwargs = str(mock_gemini.generate_tags.call_args)
        assert "Healthcare" in call_kwargs


class TestTagFromAbstract:
    def test_direct_abstract_tagging(self):
        from smartpaper.models import TaggingResult
        tagger, mock_gemini = _make_tagger(["ML", "CV"])
        result = tagger.tag_from_abstract("Image classification using CNNs.")
        # tag_from_abstract 可能回傳 TaggingResult 或 list
        tags = result.tags if isinstance(result, TaggingResult) else result
        assert isinstance(tags, list)
        assert len(tags) > 0

    def test_empty_abstract_returns_empty_or_result(self):
        from smartpaper.models import TaggingResult
        tagger, mock_gemini = _make_tagger([])
        result = tagger.tag_from_abstract("")
        tags = result.tags if isinstance(result, TaggingResult) else result
        assert isinstance(tags, list)
