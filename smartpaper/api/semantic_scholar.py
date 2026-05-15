"""
Semantic Scholar API 客戶端
取得論文的引用關係（references / citations）
API 文件：https://api.semanticscholar.org/graph/v1
"""

import time
import requests
from typing import Optional

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
FIELDS = "title,externalIds,year,authors"
REQUEST_DELAY = 0.5   # 秒，避免觸發 rate limit（100 req/5s）


def _get(url: str, params: dict) -> Optional[dict]:
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(5)
            resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"Semantic Scholar API 失敗: {e}")
        return None


def _parse_ref_entry(entry: dict, key: str) -> Optional[dict]:
    """解析 references/citations 列表中的單筆資料"""
    paper = entry.get(key, {})
    if not paper:
        return None
    ext = paper.get("externalIds") or {}
    return {
        "title": paper.get("title", ""),
        "doi": ext.get("DOI") or ext.get("doi"),
        "year": paper.get("year"),
    }


def fetch_references(doi: str) -> list[dict]:
    """
    取得一篇論文引用的所有論文（outgoing references）

    Args:
        doi: 論文的 DOI

    Returns:
        [{"title": ..., "doi": ..., "year": ...}, ...]
    """
    url = f"{BASE_URL}/DOI:{doi}/references"
    data = _get(url, {"fields": FIELDS, "limit": 500})
    time.sleep(REQUEST_DELAY)
    if not data:
        return []
    return [
        r for r in (_parse_ref_entry(e, "citedPaper") for e in data.get("data", []))
        if r and r.get("title")
    ]


def fetch_citations(doi: str) -> list[dict]:
    """
    取得引用這篇論文的所有論文（incoming citations）

    Args:
        doi: 論文的 DOI

    Returns:
        [{"title": ..., "doi": ..., "year": ...}, ...]
    """
    url = f"{BASE_URL}/DOI:{doi}/citations"
    data = _get(url, {"fields": FIELDS, "limit": 500})
    time.sleep(REQUEST_DELAY)
    if not data:
        return []
    return [
        r for r in (_parse_ref_entry(e, "citingPaper") for e in data.get("data", []))
        if r and r.get("title")
    ]
