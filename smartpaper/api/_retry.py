"""Shared retry utilities for all SmartPaper API calls."""
import time
from typing import Callable, Optional, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

T = TypeVar("T")

# Automatic retry for server-side errors (500/502/503/504) with exponential backoff
_HTTP_RETRY = Retry(
    total=3,
    backoff_factor=1,           # waits 1s, 2s, 4s between retries
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
    raise_on_status=False,
)

_TRANSIENT_KEYWORDS = (
    "resource_exhausted", "429", "503", "unavailable",
    "quota", "rate_limit", "rateerror", "timeout", "connection",
    "internal", "overloaded",
)


def make_session(user_agent: str = "SmartPaper/1.0") -> requests.Session:
    """Return a requests.Session with automatic retry for transient HTTP errors."""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    adapter = HTTPAdapter(max_retries=_HTTP_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def gemini_call_with_retry(fn: Callable[[], T], max_attempts: int = 3) -> T:
    """
    Call a zero-arg Gemini API function with exponential-backoff retry
    on quota / rate-limit / transient server errors.
    Non-transient exceptions (e.g. ValueError, JSON errors) propagate immediately.
    """
    wait = 5
    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            is_transient = any(kw in err_str for kw in _TRANSIENT_KEYWORDS)
            if is_transient and attempt < max_attempts:
                print(
                    f"[Gemini] Transient error (attempt {attempt}/{max_attempts}), "
                    f"retrying in {wait}s: {type(e).__name__}: {e}"
                )
                time.sleep(wait)
                wait *= 2
                last_err = e
            else:
                raise
    raise last_err  # only reached if all attempts failed with transient errors


def rate_limited_get(
    session: requests.Session,
    url: str,
    params: dict,
    *,
    timeout: int = 15,
    max_429_retries: int = 3,
    service_name: str = "API",
) -> Optional[requests.Response]:
    """
    GET with explicit 429 handling on top of the session's automatic retry adapter.
    Returns the Response on success, None on persistent failure.
    """
    for attempt in range(1, max_429_retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = 10 * attempt
                print(
                    f"[{service_name}] 429 Too Many Requests, "
                    f"waiting {wait}s (attempt {attempt}/{max_429_retries})…"
                )
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as e:
            if attempt < max_429_retries:
                wait = 3 * attempt
                print(f"[{service_name}] Request error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"[{service_name}] Request failed after {max_429_retries} attempts: {e}")
                return None
    return None
