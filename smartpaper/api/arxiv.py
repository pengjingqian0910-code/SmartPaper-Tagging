"""
Arxiv API 模組
補充 Crossref 查不到摘要的論文，作為第三個摘要來源
"""

import re
import time
import threading
import xml.etree.ElementTree as ET
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ARXIV_API_URL = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}

# 重試設定：最多 3 次，退避因子 2 → 等待 2s, 4s, 8s
_RETRY = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)

# ── 模組級速率限制 ────────────────────────────────────────────────
# 所有 arXiv 請求共用同一把鎖，確保串行執行且間距 ≥ MIN_INTERVAL
_rate_lock = threading.Lock()
_last_request_time: float = 0.0
_backoff_until: float = 0.0       # 收到 429 後全域封鎖到此時間點
_MIN_INTERVAL = 8.0               # 正常請求間距（秒）
_BACKOFF_SECS  = 300.0            # 收到 429 後封鎖 5 分鐘

# ── 關鍵字搜尋結果快取（TTL 10 分鐘）────────────────────────────
_kw_cache: dict[str, tuple[float, list]] = {}  # query → (timestamp, results)
_KW_CACHE_TTL = 600  # seconds


def _rate_limit_wait() -> bool:
    """
    等待至可安全發送請求為止。
    若目前在全域封鎖期間內則立即回傳 False（呼叫方應放棄本次請求）。
    """
    global _last_request_time
    with _rate_lock:
        now = time.time()
        # 全域 429 封鎖期間：直接拒絕
        if now < _backoff_until:
            remaining = int(_backoff_until - now)
            print(f"[arXiv] 封鎖中，還需等待 {remaining}s（因近期 429）")
            return False
        # 正常速率限制
        elapsed = now - _last_request_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_request_time = time.time()
        return True


def _trigger_backoff():
    """收到 429 時呼叫，設定全域封鎖時間。"""
    global _backoff_until
    with _rate_lock:
        _backoff_until = time.time() + _BACKOFF_SECS
        print(f"[arXiv] 已觸發全域封鎖 {int(_BACKOFF_SECS)}s，暫停所有 arXiv 請求")


class ArxivAPI:
    """Arxiv Open Access API 查詢類"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SmartPaper-Tagging/0.1 (Academic Research Tool)"
        })
        adapter = HTTPAdapter(max_retries=_RETRY)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def search_by_title(
        self,
        title: str,
        timeout: int = 30,
        max_attempts: int = 3,
    ) -> Optional[dict]:
        """
        根據標題在 Arxiv 搜尋論文摘要，失敗時指數退避重試。

        Args:
            title: 論文標題
            timeout: 單次請求 timeout（秒）
            max_attempts: 最多嘗試幾次（含第一次）

        Returns:
            {"abstract": str, "arxiv_id": str, "year": str, "title": str} 或 None
        """
        if not _rate_limit_wait():
            return None

        clean_title = re.sub(r'[^\w\s]', ' ', title).strip()
        params = {
            "search_query": f'ti:"{clean_title}"',
            "max_results": 5,
            "sortBy": "relevance",
        }

        wait = 2  # 初始等待秒數
        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.get(ARXIV_API_URL, params=params, timeout=timeout)
                if resp.status_code == 429:
                    _trigger_backoff()
                    return None
                resp.raise_for_status()
                return self._parse_best_match(resp.text, title)
            except requests.Timeout:
                if attempt < max_attempts:
                    print(f"Arxiv 連線逾時，{wait}s 後重試（第 {attempt}/{max_attempts} 次）...")
                    time.sleep(wait)
                    wait *= 2
                else:
                    print(f"Arxiv API 請求失敗（已重試 {max_attempts} 次）：連線逾時")
            except requests.RequestException as e:
                if attempt < max_attempts:
                    print(f"Arxiv 請求失敗，{wait}s 後重試（第 {attempt}/{max_attempts} 次）: {e}")
                    time.sleep(wait)
                    wait *= 2
                else:
                    print(f"Arxiv API 請求失敗（已重試 {max_attempts} 次）: {e}")
            except ET.ParseError as e:
                print(f"Arxiv XML 解析失敗: {e}")
                return None  # XML 解析錯誤不值得重試

        return None

    def search_by_keywords(
        self,
        query: str,
        n_results: int = 5,
        timeout: int = 30,
    ) -> list[dict]:
        """
        以關鍵字搜尋 arXiv（標題 OR 摘要）。

        Returns:
            list of {title, abstract, arxiv_id, year, url, authors}
        """
        # 清理 query：移除 boolean 運算子與特殊字元，只保留有意義的詞
        clean = re.sub(r'\b(OR|AND|ANDNOT|NOT)\b', ' ', query, flags=re.IGNORECASE)
        clean = re.sub(r'[^\w\s]', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        # 取前 5 個有意義的詞（長度 > 2），避免 query 過長
        words = [w for w in clean.split() if len(w) > 2][:5]
        if not words:
            return []
        search_terms = "+".join(words)
        cache_key = search_terms

        # ── TTL 快取：同樣 query 10 分鐘內直接回傳，不再打 API ──
        if cache_key in _kw_cache:
            ts, cached = _kw_cache[cache_key]
            if time.time() - ts < _KW_CACHE_TTL:
                return cached

        params = {
            "search_query": f"ti:{search_terms} OR abs:{search_terms}",
            "max_results": n_results,
            "sortBy": "relevance",
        }

        # 速率限制檢查：封鎖期間直接回傳空結果
        if not _rate_limit_wait():
            return []

        resp = None
        for attempt in range(1, 3):   # 最多 2 次（減少對 arXiv 的壓力）
            try:
                resp = self.session.get(ARXIV_API_URL, params=params, timeout=timeout)
                if resp.status_code == 429:
                    print(f"[arXiv] 429 rate limit，觸發全域封鎖 {int(_BACKOFF_SECS)}s")
                    _trigger_backoff()
                    return []   # 直接放棄，不再重試
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt < 2:
                    time.sleep(15)
                else:
                    print(f"[arXiv] 關鍵字搜尋失敗：{e}")
                    return []

        if resp is None:
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            print(f"[arXiv] XML 解析失敗：{e}")
            return []

        results = []
        for entry in root.findall("atom:entry", _NS):
            title_el   = entry.find("atom:title", _NS)
            summary_el = entry.find("atom:summary", _NS)
            id_el      = entry.find("atom:id", _NS)
            pub_el     = entry.find("atom:published", _NS)

            if title_el is None or summary_el is None or id_el is None:
                continue

            raw_id   = (id_el.text or "").strip()
            arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
            title    = " ".join((title_el.text or "").split())
            abstract = " ".join((summary_el.text or "").split())
            year     = None
            if pub_el is not None and pub_el.text:
                try:
                    year = int(pub_el.text[:4])
                except ValueError:
                    pass

            authors = [
                (a.find("atom:name", _NS).text or "").strip()
                for a in entry.findall("atom:author", _NS)
                if a.find("atom:name", _NS) is not None
            ]

            results.append({
                "title":     title,
                "abstract":  abstract,
                "arxiv_id":  arxiv_id,
                "year":      year,
                "url":       f"https://arxiv.org/abs/{arxiv_id}",
                "authors":   authors,
            })

        # 寫入快取
        _kw_cache[cache_key] = (time.time(), results)
        return results

    def _parse_best_match(self, xml_text: str, original_title: str) -> Optional[dict]:
        """從 Atom XML 結果中找出最佳匹配的論文"""
        root = ET.fromstring(xml_text)
        entries = root.findall("atom:entry", _NS)
        if not entries:
            return None

        orig_words = set(original_title.lower().split())
        best = None
        best_overlap = 0

        for entry in entries:
            title_el = entry.find("atom:title", _NS)
            summary_el = entry.find("atom:summary", _NS)
            if title_el is None or summary_el is None:
                continue

            entry_title = (title_el.text or "").strip()
            abstract = (summary_el.text or "").strip()
            if not abstract:
                continue

            entry_words = set(entry_title.lower().split())
            overlap = len(orig_words & entry_words)

            if overlap > best_overlap:
                best_overlap = overlap
                id_el = entry.find("atom:id", _NS)
                pub_el = entry.find("atom:published", _NS)
                best = {
                    "title": entry_title,
                    "abstract": abstract,
                    "arxiv_id": (id_el.text or "").strip() if id_el is not None else None,
                    "year": (pub_el.text or "")[:4] if pub_el is not None else None,
                }

        # 至少需要 3 個單字重疊，避免錯誤匹配
        if best and best_overlap >= 3:
            return best
        return None
