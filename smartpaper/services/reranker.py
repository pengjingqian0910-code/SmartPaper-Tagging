"""
Re-ranking 服務模組
CrossEncoder 重排分，附 BM25 pre-filter 與 score memoization 加速
"""

import hashlib
import re
from typing import Optional

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# 候選數超過此門檻才啟動 BM25 pre-filter
_BM25_THRESHOLD = 20
# score cache 上限，超過時清除最舊的 20%
_SCORE_CACHE: dict[tuple, float] = {}
_SCORE_CACHE_MAX = 8000


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"\b\w+\b", text)
    cjk = re.findall(r"[一-鿿]", text)
    return tokens + cjk


def _bm25_prefilter(
    candidates: list[dict],
    query: str,
    text_key: str,
    keep: int,
) -> list[dict]:
    """用 BM25 快速縮減候選數，讓 CrossEncoder 只看最相關的 keep 篇。"""
    try:
        from rank_bm25 import BM25Okapi
        corpus = [_tokenize(c.get(text_key, "")) for c in candidates]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(_tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [candidates[i] for i in order[:keep]]
    except Exception:
        return candidates[:keep]


class Reranker:
    """CrossEncoder re-ranking，延遲載入模型以節省啟動時間"""

    def __init__(self, model_name: str = RERANKER_MODEL):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        text_key: str = "document",
        top_k: Optional[int] = None,
    ) -> list[dict]:
        if not candidates:
            return candidates

        # ── BM25 pre-filter ────────────────────────────────────────────
        working = candidates
        if len(candidates) > _BM25_THRESHOLD:
            keep = max(top_k * 2 if top_k else _BM25_THRESHOLD, _BM25_THRESHOLD)
            working = _bm25_prefilter(candidates, query, text_key, keep)

        # ── Score memoization ──────────────────────────────────────────
        to_score: list[tuple[int, str, tuple]] = []   # (idx_in_working, text, cache_key)
        for i, c in enumerate(working):
            text = c.get(text_key, "")
            key = (query, _text_hash(text))
            if key in _SCORE_CACHE:
                c["rerank_score"] = _SCORE_CACHE[key]
            else:
                to_score.append((i, text, key))

        # ── CrossEncoder: only for uncached candidates ─────────────────
        if to_score:
            pairs = [(query, text) for _, text, _ in to_score]
            scores = self.model.predict(pairs)
            # Evict oldest 20% if cache is full
            if len(_SCORE_CACHE) >= _SCORE_CACHE_MAX:
                evict_n = _SCORE_CACHE_MAX // 5
                for k in list(_SCORE_CACHE.keys())[:evict_n]:
                    del _SCORE_CACHE[k]
            for (i, _, key), score in zip(to_score, scores):
                score_f = float(score)
                _SCORE_CACHE[key] = score_f
                working[i]["rerank_score"] = score_f

        ranked = sorted(working, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return ranked[:top_k] if top_k is not None else ranked
