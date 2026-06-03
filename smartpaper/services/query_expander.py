"""
Query Expansion（查詢擴展）
用 Gemini 將使用者查詢改寫成語意互補的多個版本，
再透過 RRF 合併結果，提升搜尋召回率。
"""

from __future__ import annotations
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..api.gemini import GeminiTagger


_PROMPT = """\
你是學術搜尋助理。將下面的搜尋查詢改寫成 2 個語意互補的版本：
- 版本1：強調方法論或技術細節
- 版本2：強調應用場景或問題領域

只輸出 2 行，每行一個查詢，不加編號、不加說明。

原始查詢：{query}"""


class QueryExpander:
    """
    輕量查詢擴展器。
    失敗時（API 未設定、網路錯誤）靜默降級，回傳空清單。
    """

    def __init__(self):
        self._gemini: "GeminiTagger | None" = None

    def _get_gemini(self) -> "GeminiTagger | None":
        if self._gemini is not None:
            return self._gemini
        try:
            from ..config import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                return None
            from ..api.gemini import GeminiTagger
            self._gemini = GeminiTagger()
        except Exception:
            pass
        return self._gemini

    def expand(self, query: str) -> list[str]:
        """
        回傳 0-2 個額外查詢變體（不含原始查詢）。
        任何失敗都回傳空清單，讓呼叫端 gracefully fallback。
        """
        if len(query.strip()) < 4:
            return []
        gemini = self._get_gemini()
        if gemini is None:
            return []
        try:
            raw = gemini.generate_content(_PROMPT.format(query=query.strip()))
            variants = [
                line.strip()
                for line in raw.strip().splitlines()
                if line.strip() and not re.match(r'^[\d\.\-\*]', line)
            ]
            # 去掉與原始查詢重複或過短的
            return [v for v in variants[:2] if v != query and len(v) > 4]
        except Exception:
            return []
