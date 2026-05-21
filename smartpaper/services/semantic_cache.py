"""
語義快取 (Semantic Cache) — 零額外模型負擔版

核心思想：
  「相似查詢不需要重跑昂貴的 BM25 + 向量搜尋 + CrossEncoder pipeline」

與傳統精確 LRU 快取的差異：
  精確: "deep learning"   ==  "deep learning"         → hit
  精確: "deep learning"   vs  "deep learning methods"  → miss ❌

  語義: "deep learning"   vs  "deep learning methods"
        cos_sim ≈ 0.94 → hit ✅

技術決策：
  - 重用 VectorDB 已載入的 allenai-specter singleton（不額外載入模型）
  - 雙層快取：精確字串 O(1) → 語義向量 O(n)
  - 標準化前處理：降低大小寫/標點造成的 miss
  - TTL 過期 + LRU 淘汰

統計：
  cache.stats() → {"hit_rate_pct": 68.2, "exact_hits": 12, "fuzzy_hits": 9, ...}
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from typing import Any, Optional

import numpy as np


def _normalize(text: str) -> str:
    """正規化查詢字串，擴大精確快取命中範圍。"""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s一-鿿]", " ", text)  # 保留中文 + 英數
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _embed_text(text: str) -> Optional[np.ndarray]:
    """重用 VectorDB 的 allenai-specter singleton — 不載入額外模型。"""
    try:
        from ..database.vector_db import _get_embedding_fn
        fn = _get_embedding_fn()
        result = fn([text])
        return np.array(result[0], dtype=np.float32)
    except Exception:
        return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / (denom + 1e-9))


class SemanticCache:
    """
    語義快取。

    使用範例：
        cache = SemanticCache(similarity_threshold=0.93)

        hit, result = cache.get("什麼是 attention mechanism？")
        if not hit:
            result = expensive_search(query)
            cache.put(query, result)

    快取結構：
        Layer 1: _exact  — 精確字串匹配，O(1)，無嵌入計算
        Layer 2: _fuzzy  — 語義向量比對，O(n)，重用已有嵌入模型
    """

    def __init__(
        self,
        max_size: int = 256,
        similarity_threshold: float = 0.93,
        ttl_seconds: int = 3600,
    ):
        # Layer 1: 精確快取（正規化字串 → result）
        self._exact: OrderedDict[str, dict] = OrderedDict()

        # Layer 2: 語義快取（embedding 向量列表）
        self._fuzzy: list[dict] = []   # [{norm_text, embedding, result, ts}]

        self._max_size  = max_size
        self._threshold = similarity_threshold
        self._ttl       = ttl_seconds

        # 統計
        self._n_exact  = 0
        self._n_fuzzy  = 0
        self._n_miss   = 0
        self._n_put    = 0

    # ── 查詢 ──────────────────────────────────────────────────────────

    def get(self, query: str) -> tuple[bool, Any]:
        """
        查詢快取。
        回傳 (is_hit, result)；miss 時 result 為 None。
        """
        now  = time.time()
        norm = _normalize(query)

        # Layer 1: 精確比對（毫秒級）
        if norm in self._exact:
            entry = self._exact[norm]
            if now - entry["ts"] < self._ttl:
                self._exact.move_to_end(norm)
                self._n_exact += 1
                return True, entry["result"]
            del self._exact[norm]   # 過期刪除

        # 清理過期語義條目
        self._fuzzy = [e for e in self._fuzzy if now - e["ts"] < self._ttl]

        # Layer 2: 語義比對（~5-15 ms，取決於快取大小）
        emb = _embed_text(query)
        if emb is not None and self._fuzzy:
            best_sim, best_result = 0.0, None
            for entry in self._fuzzy:
                sim = _cosine(emb, entry["embedding"])
                if sim > best_sim:
                    best_sim = sim
                    best_result = entry["result"]
            if best_sim >= self._threshold:
                self._n_fuzzy += 1
                # 促進到精確快取，下次直接命中
                self._put_exact(norm, best_result, now)
                return True, best_result

        self._n_miss += 1
        return False, None

    # ── 寫入 ──────────────────────────────────────────────────────────

    def put(self, query: str, result: Any) -> None:
        """存入快取。result 必須是可 pickle 的物件。"""
        now  = time.time()
        norm = _normalize(query)

        self._put_exact(norm, result, now)

        # 語義層：計算嵌入並存入
        emb = _embed_text(query)
        if emb is None:
            return

        # LRU 淘汰
        if len(self._fuzzy) >= self._max_size:
            self._fuzzy.pop(0)

        self._fuzzy.append({
            "norm_text": norm,
            "embedding": emb,
            "result":    result,
            "ts":        now,
        })
        self._n_put += 1

    def _put_exact(self, norm: str, result: Any, ts: float) -> None:
        """寫入精確快取，帶 LRU 淘汰。"""
        if norm in self._exact:
            self._exact.move_to_end(norm)
        else:
            if len(self._exact) >= self._max_size:
                self._exact.popitem(last=False)
        self._exact[norm] = {"result": result, "ts": ts}

    # ── 管理 ──────────────────────────────────────────────────────────

    def invalidate(self) -> None:
        """資料庫更新後清除所有快取。"""
        self._exact.clear()
        self._fuzzy.clear()
        self._n_exact = self._n_fuzzy = self._n_miss = self._n_put = 0

    def stats(self) -> dict:
        total = self._n_exact + self._n_fuzzy + self._n_miss
        hit_rate = (self._n_exact + self._n_fuzzy) / max(total, 1)
        return {
            "size_exact":   len(self._exact),
            "size_fuzzy":   len(self._fuzzy),
            "exact_hits":   self._n_exact,
            "fuzzy_hits":   self._n_fuzzy,
            "misses":       self._n_miss,
            "total_puts":   self._n_put,
            "hit_rate_pct": round(hit_rate * 100, 1),
        }

    def __len__(self) -> int:
        return len(self._fuzzy)
