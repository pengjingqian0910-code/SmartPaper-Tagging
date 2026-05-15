"""
Unit tests — smartpaper/api/crossref.py
使用 patch.object 攔截 Session.get，不發真實 HTTP
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.api.crossref import CrossrefAPI
from smartpaper.models import CrossrefResponse


def _mock_response(data: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def _crossref_payload(title="Test Paper", doi="10.9999/xyz", abstract="An abstract."):
    return {
        "message": {
            "total-results": 1,
            "items": [{
                "title": [title],
                "DOI": doi,
                "abstract": f"<jats:p>{abstract}</jats:p>",
                "author": [{"given": "Alice", "family": "Smith"}],
                "published": {"date-parts": [[2023]]},
                "container-title": ["Nature"],
            }],
        }
    }


class TestCrossrefSearchByTitle:
    def setup_method(self):
        self.api = CrossrefAPI(email="test@example.com")

    def test_successful_search(self):
        with patch.object(self.api.session, "get", return_value=_mock_response(_crossref_payload())):
            result = self.api.search_by_title("Test Paper")
        assert result is not None
        assert isinstance(result, CrossrefResponse)

    def test_doi_extracted(self):
        with patch.object(self.api.session, "get", return_value=_mock_response(_crossref_payload(doi="10.9999/xyz"))):
            result = self.api.search_by_title("Test Paper")
        assert result is not None
        assert result.doi == "10.9999/xyz"

    def test_abstract_html_cleaned(self):
        with patch.object(self.api.session, "get", return_value=_mock_response(
            _crossref_payload(abstract="Clean abstract text.")
        )):
            result = self.api.search_by_title("Test Paper")
        assert result is not None
        assert "<jats:p>" not in result.abstract
        assert "Clean abstract text." in result.abstract

    def test_empty_results_returns_none(self):
        with patch.object(self.api.session, "get", return_value=_mock_response({
            "message": {"total-results": 0, "items": []}
        })):
            result = self.api.search_by_title("Nonexistent Paper XYZ")
        assert result is None

    def test_network_error_returns_none(self):
        import requests
        with patch.object(self.api.session, "get", side_effect=requests.RequestException("Connection refused")):
            result = self.api.search_by_title("Any Paper")
        assert result is None

    def test_author_parsed(self):
        with patch.object(self.api.session, "get", return_value=_mock_response(_crossref_payload())):
            result = self.api.search_by_title("Test Paper")
        assert result is not None
        assert result.authors
        assert any("Smith" in a for a in result.authors)

    def test_year_parsed(self):
        with patch.object(self.api.session, "get", return_value=_mock_response(_crossref_payload())):
            result = self.api.search_by_title("Test Paper")
        assert result is not None
        assert "2023" in str(result.published_date)


class TestCrossrefGetByDoi:
    def setup_method(self):
        self.api = CrossrefAPI()

    def test_doi_lookup_success(self):
        payload = {
            "message": {
                "title": ["DOI Paper"],
                "DOI": "10.9999/doi",
                "abstract": "Abstract text.",
                "author": [],
                "published": {"date-parts": [[2022]]},
                "container-title": ["Science"],
            }
        }
        with patch.object(self.api.session, "get", return_value=_mock_response(payload)):
            result = self.api.get_by_doi("10.9999/doi")
        assert result is not None
        assert "DOI Paper" in result.title

    def test_doi_lookup_failure_returns_none(self):
        import requests
        with patch.object(self.api.session, "get", side_effect=requests.RequestException("Not found")):
            result = self.api.get_by_doi("10.0000/invalid")
        assert result is None


class TestCrossrefBatchSearch:
    def setup_method(self):
        self.api = CrossrefAPI()

    def test_batch_returns_list(self):
        with patch.object(self.api.session, "get", return_value=_mock_response(_crossref_payload())):
            results = self.api.search_batch(["Paper A", "Paper B"], delay=0)
        assert isinstance(results, list)
        assert len(results) == 2

    def test_batch_empty_input(self):
        results = self.api.search_batch([], delay=0)
        assert results == []
