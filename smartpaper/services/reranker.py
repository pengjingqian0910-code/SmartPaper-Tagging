"""
Re-ranking 服務模組
使用 CrossEncoder 對初始檢索結果重新排分，提升精準度
"""

from typing import Optional

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


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
        """
        對候選結果重新排分

        Args:
            query: 搜尋查詢
            candidates: 候選結果列表，每個元素為 dict
            text_key: 候選結果中文字欄位的 key
            top_k: 回傳前 N 筆，None 表示回傳全部

        Returns:
            依 rerank 分數排序後的候選列表（每個 dict 加入 "rerank_score" 欄位）
        """
        if not candidates:
            return candidates

        pairs = [(query, c.get(text_key, "")) for c in candidates]
        scores = self.model.predict(pairs)

        for candidate, score in zip(candidates, scores):
            candidate["rerank_score"] = float(score)

        ranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
        return ranked[:top_k] if top_k is not None else ranked
