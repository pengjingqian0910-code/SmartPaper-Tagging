"""
Unit tests — smartpaper/api/gemini.py
Mock google.genai，驗證標籤解析邏輯
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.api.gemini import GeminiTagger


def _make_tagger(mock_client=None):
    with patch("smartpaper.api.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = mock_client or MagicMock()
        tagger = GeminiTagger(api_key="fake-key")
    tagger.client = mock_client or MagicMock()
    return tagger


class TestParseTagsResponse:
    def setup_method(self):
        self.tagger = _make_tagger()

    def test_json_array(self):
        tags = self.tagger._parse_tags_response('["NLP", "Deep Learning", "BERT"]')
        assert tags == ["NLP", "Deep Learning", "BERT"]

    def test_json_with_whitespace(self):
        tags = self.tagger._parse_tags_response('  ["NLP", "ML"]  ')
        assert "NLP" in tags
        assert "ML" in tags

    def test_comma_separated_fallback(self):
        tags = self.tagger._parse_tags_response("NLP, Deep Learning, BERT")
        assert len(tags) >= 2
        assert any("NLP" in t for t in tags)

    def test_numbered_list_fallback(self):
        text = "1. Machine Learning\n2. Deep Learning\n3. NLP"
        tags = self.tagger._parse_tags_response(text)
        assert len(tags) >= 2

    def test_empty_response(self):
        tags = self.tagger._parse_tags_response("")
        assert isinstance(tags, list)

    def test_json_object_with_tags_key(self):
        tags = self.tagger._parse_tags_response('{"tags": ["NLP", "AI"]}')
        assert "NLP" in tags or "AI" in tags

    def test_strips_quotes_and_brackets(self):
        tags = self.tagger._parse_tags_response('["Machine Learning"]')
        assert any("Machine Learning" in t for t in tags)


class TestGenerateTags:
    def _make_mock_client(self, response_text: str):
        resp = MagicMock()
        resp.text = response_text
        client = MagicMock()
        client.models.generate_content.return_value = resp
        return client

    def test_returns_tagging_result(self):
        from smartpaper.models import TaggingResult
        client = self._make_mock_client('["NLP", "Deep Learning", "BERT"]')
        tagger = _make_tagger(client)
        result = tagger.generate_tags(abstract="An NLP paper about BERT.")
        assert isinstance(result, TaggingResult)
        assert isinstance(result.tags, list)
        assert len(result.tags) > 0

    def test_uses_title_in_prompt(self):
        client = self._make_mock_client('["NLP"]')
        tagger = _make_tagger(client)
        tagger.generate_tags(abstract="Abstract text.", title="My Special Paper")
        call_args = client.models.generate_content.call_args
        prompt = str(call_args)
        assert "My Special Paper" in prompt

    def test_api_error_returns_empty_tags(self):
        from smartpaper.models import TaggingResult
        client = MagicMock()
        # Non-transient error → no retry, raises immediately
        client.models.generate_content.side_effect = Exception("Some programming error")
        tagger = _make_tagger(client)
        result = tagger.generate_tags(abstract="Some abstract.")
        assert isinstance(result, TaggingResult)
        assert result.tags == []

    def test_transient_api_error_retries(self):
        from smartpaper.models import TaggingResult
        from unittest.mock import call
        resp = MagicMock()
        resp.text = '["NLP"]'
        client = MagicMock()
        # Fail twice with quota error then succeed
        client.models.generate_content.side_effect = [
            Exception("resource_exhausted"),
            Exception("resource_exhausted"),
            resp,
        ]
        tagger = _make_tagger(client)
        with patch("smartpaper.api._retry.time.sleep"):
            result = tagger.generate_tags(abstract="Some abstract.")
        assert isinstance(result, TaggingResult)
        assert result.tags == ["NLP"]
        assert client.models.generate_content.call_count == 3

    def test_empty_abstract_does_not_crash(self):
        from smartpaper.models import TaggingResult
        client = self._make_mock_client("[]")
        tagger = _make_tagger(client)
        result = tagger.generate_tags(abstract="")
        assert isinstance(result, TaggingResult)

    def test_custom_categories_in_prompt(self):
        client = self._make_mock_client('["Healthcare"]')
        tagger = _make_tagger(client)
        tagger.generate_tags(abstract="Medical paper.", custom_categories=["Healthcare", "AI"])
        call_args = client.models.generate_content.call_args
        prompt = str(call_args)
        assert "Healthcare" in prompt


class TestBatchGenerateTags:
    def test_batch_processes_all_papers(self):
        client = MagicMock()
        resp = MagicMock()
        resp.text = '["NLP", "ML"]'
        client.models.generate_content.return_value = resp
        tagger = _make_tagger(client)

        papers = [
            {"title": "Paper A", "abstract": "Abstract A"},
            {"title": "Paper B", "abstract": "Abstract B"},
        ]
        results = tagger.batch_generate_tags(papers)
        assert len(results) == 2
        assert client.models.generate_content.call_count == 2

    def test_batch_empty_input(self):
        tagger = _make_tagger()
        results = tagger.batch_generate_tags([])
        assert results == []
