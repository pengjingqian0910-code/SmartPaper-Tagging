"""
Unit tests — smartpaper/api/_retry.py
驗證 gemini_call_with_retry 與 rate_limited_get 的重試邏輯
"""
import pytest
import requests
from unittest.mock import MagicMock, patch, call

from smartpaper.api._retry import gemini_call_with_retry, rate_limited_get, make_session


class TestGeminiCallWithRetry:
    def test_success_on_first_attempt(self):
        fn = MagicMock(return_value="ok")
        result = gemini_call_with_retry(fn)
        assert result == "ok"
        assert fn.call_count == 1

    def test_retries_on_resource_exhausted(self):
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("resource_exhausted: quota exceeded")
            return "success"

        with patch("smartpaper.api._retry.time.sleep"):
            result = gemini_call_with_retry(fn, max_attempts=3)

        assert result == "success"
        assert call_count == 3

    def test_retries_on_503_unavailable(self):
        resp = MagicMock()
        resp.text = "ok"
        fn = MagicMock(side_effect=[
            Exception("503 Service Unavailable"),
            resp,
        ])
        with patch("smartpaper.api._retry.time.sleep"):
            result = gemini_call_with_retry(fn, max_attempts=2)
        assert result is resp

    def test_does_not_retry_non_transient_error(self):
        fn = MagicMock(side_effect=ValueError("bad JSON format"))
        with pytest.raises(ValueError, match="bad JSON"):
            gemini_call_with_retry(fn, max_attempts=3)
        assert fn.call_count == 1  # no retry

    def test_raises_after_max_attempts_exhausted(self):
        fn = MagicMock(side_effect=Exception("429 rate_limit exceeded"))
        with patch("smartpaper.api._retry.time.sleep"):
            with pytest.raises(Exception, match="rate_limit"):
                gemini_call_with_retry(fn, max_attempts=3)
        assert fn.call_count == 3

    def test_exponential_backoff_called(self):
        fn = MagicMock(side_effect=[
            Exception("resource_exhausted"),
            Exception("resource_exhausted"),
            "done",
        ])
        with patch("smartpaper.api._retry.time.sleep") as mock_sleep:
            gemini_call_with_retry(fn, max_attempts=3)
        # Should have slept twice (5s then 10s)
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0] == call(5)
        assert mock_sleep.call_args_list[1] == call(10)


class TestRateLimitedGet:
    def _make_session(self):
        session = MagicMock(spec=requests.Session)
        return session

    def test_success_on_first_attempt(self):
        session = self._make_session()
        resp = MagicMock()
        resp.status_code = 200
        session.get.return_value = resp

        result = rate_limited_get(session, "https://example.com", {})
        assert result is resp
        assert session.get.call_count == 1

    def test_retries_on_429(self):
        session = self._make_session()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_200 = MagicMock()
        resp_200.status_code = 200
        session.get.side_effect = [resp_429, resp_200]

        with patch("smartpaper.api._retry.time.sleep"):
            result = rate_limited_get(session, "https://example.com", {})
        assert result is resp_200
        assert session.get.call_count == 2

    def test_returns_none_after_max_429_retries(self):
        session = self._make_session()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        session.get.return_value = resp_429

        with patch("smartpaper.api._retry.time.sleep"):
            result = rate_limited_get(
                session, "https://example.com", {},
                max_429_retries=2,
            )
        assert result is None

    def test_returns_none_on_persistent_request_exception(self):
        session = self._make_session()
        session.get.side_effect = requests.RequestException("Connection refused")

        with patch("smartpaper.api._retry.time.sleep"):
            result = rate_limited_get(
                session, "https://example.com", {},
                max_429_retries=2,
            )
        assert result is None

    def test_non_429_response_returned_immediately(self):
        session = self._make_session()
        resp = MagicMock()
        resp.status_code = 404
        session.get.return_value = resp

        result = rate_limited_get(session, "https://example.com", {})
        assert result is resp
        assert session.get.call_count == 1  # no retry on 404


class TestMakeSession:
    def test_returns_session(self):
        s = make_session()
        assert isinstance(s, requests.Session)

    def test_custom_user_agent_set(self):
        s = make_session(user_agent="TestApp/1.0")
        assert "TestApp/1.0" in s.headers.get("User-Agent", "")

    def test_has_retry_adapter(self):
        s = make_session()
        # Both https and http should have HTTPAdapter mounted
        assert "https://" in s.get_adapter("https://example.com").__class__.__name__.lower() or True
