"""
Semantic Scholar API 客戶端
取得論文的引用關係（references / citations）
API 文件：https://api.semanticscholar.org/graph/v1
"""

import time
import requests
from typing import Optional

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
REC_URL  = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper"
FIELDS       = "title,externalIds,year,authors,abstract"
DETAIL_FIELDS = "title,externalIds,year,authors,abstract,venue,citationCount"
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


def get_paper_by_doi(doi: str) -> Optional[dict]:
    """
    以 DOI 查詢單篇論文的詳細資訊。

    Returns:
        {"title", "authors": [{"name":...}], "year", "venue", "abstract",
         "citationCount", "doi"} 或 None
    """
    url = f"{BASE_URL}/DOI:{doi}"
    data = _get(url, {"fields": DETAIL_FIELDS})
    time.sleep(REQUEST_DELAY)
    if not data:
        return None
    ext = data.get("externalIds") or {}
    return {
        "title":         data.get("title", ""),
        "authors":       data.get("authors") or [],
        "year":          data.get("year"),
        "venue":         data.get("venue", ""),
        "abstract":      data.get("abstract", ""),
        "citationCount": data.get("citationCount", 0),
        "doi":           ext.get("DOI") or ext.get("doi") or doi,
    }


def search_papers(query: str, limit: int = 5) -> list[dict]:
    """
    以標題關鍵字搜尋 Semantic Scholar。

    Returns:
        list of {"title", "authors", "year", "venue", "abstract",
                 "citationCount", "doi"}
    """
    url = f"{BASE_URL}/search"
    data = _get(url, {"query": query, "fields": DETAIL_FIELDS, "limit": limit})
    time.sleep(REQUEST_DELAY)
    if not data:
        return []
    results = []
    for paper in data.get("data", []):
        if not paper.get("title"):
            continue
        ext = paper.get("externalIds") or {}
        results.append({
            "title":         paper.get("title", ""),
            "authors":       paper.get("authors") or [],
            "year":          paper.get("year"),
            "venue":         paper.get("venue", ""),
            "abstract":      paper.get("abstract", ""),
            "citationCount": paper.get("citationCount", 0),
            "doi":           ext.get("DOI") or ext.get("doi"),
        })
    return results


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


def fetch_recommendations(doi: str, n: int = 8) -> list[dict]:
    """
    透過 Semantic Scholar Recommendations API 取得相關論文推薦。

    Args:
        doi: 論文的 DOI
        n:   回傳推薦數量上限

    Returns:
        [{"title": ..., "doi": ..., "year": ..., "authors": [...], "abstract": ...}, ...]
    """
    url = f"{REC_URL}/DOI:{doi}"
    data = _get(url, {"fields": FIELDS, "limit": n})
    time.sleep(REQUEST_DELAY)
    if not data:
        return []
    results = []
    for paper in data.get("recommendedPapers", []):
        if not paper.get("title"):
            continue
        ext = paper.get("externalIds") or {}
        doi_val = ext.get("DOI") or ext.get("doi")
        arxiv_id = ext.get("ArXiv")
        authors = [a.get("name", "") for a in (paper.get("authors") or [])]
        results.append({
            "title": paper.get("title", ""),
            "doi": doi_val,
            "arxiv_id": arxiv_id,
            "year": paper.get("year"),
            "authors": authors,
            "abstract": (paper.get("abstract") or "")[:500],
        })
    return results[:n]


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
