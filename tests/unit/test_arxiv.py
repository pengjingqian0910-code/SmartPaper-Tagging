"""
Unit tests — smartpaper/api/arxiv.py
Mock requests，驗證 XML 解析與標題比對邏輯
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.api.arxiv import ArxivAPI


SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Attention Is All You Need</title>
    <summary>We propose a new network architecture based solely on attention mechanisms.</summary>
    <author><name>Ashish Vaswani</name></author>
    <published>2017-06-12T00:00:00Z</published>
    <link href="https://arxiv.org/abs/1706.03762" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

EMPTY_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""


def _mock_http(xml_text: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = xml_text
    resp.raise_for_status.return_value = None
    return resp


class TestArxivSearchByTitle:
    """ArXiv search_by_title 回傳 dict 或 None"""

    def setup_method(self):
        self.api = ArxivAPI()

    def test_successful_search_returns_result(self):
        with patch.object(self.api.session, "get", return_value=_mock_http(SAMPLE_ATOM)):
            result = self.api.search_by_title("Attention Is All You Need")
        assert result is not None
        # 回傳 dict
        title = result.get("title", "") if isinstance(result, dict) else result.title
        assert "attention" in title.lower()

    def test_abstract_extracted(self):
        with patch.object(self.api.session, "get", return_value=_mock_http(SAMPLE_ATOM)):
            result = self.api.search_by_title("Attention Is All You Need")
        assert result is not None
        abstract = result.get("abstract", "") if isinstance(result, dict) else result.abstract
        assert abstract

    def test_empty_feed_returns_none(self):
        with patch.object(self.api.session, "get", return_value=_mock_http(EMPTY_ATOM)):
            result = self.api.search_by_title("Nonexistent Paper")
        assert result is None

    def test_network_error_returns_none(self):
        import requests as req
        with patch.object(self.api.session, "get", side_effect=req.RequestException("Timeout")):
            result = self.api.search_by_title("Any Paper")
        assert result is None

    def test_mismatched_title_not_returned(self):
        with patch.object(self.api.session, "get", return_value=_mock_http(SAMPLE_ATOM)):
            result = self.api.search_by_title("Quantum Computing with Photons")
        assert result is None


class TestArxivParseBestMatch:
    def setup_method(self):
        self.api = ArxivAPI()

    def test_exact_match(self):
        result = self.api._parse_best_match(SAMPLE_ATOM, "Attention Is All You Need")
        assert result is not None
        title = result.get("title", "") if isinstance(result, dict) else result
        assert title  # 有值

    def test_no_entry_returns_none(self):
        result = self.api._parse_best_match(EMPTY_ATOM, "Any Title")
        assert result is None

    def test_low_overlap_returns_none(self):
        result = self.api._parse_best_match(SAMPLE_ATOM, "Quantum Computing Photon Entanglement")
        assert result is None

    def test_partial_overlap_accepted(self):
        result = self.api._parse_best_match(SAMPLE_ATOM, "Attention Mechanism All You Need")
        assert result is not None
