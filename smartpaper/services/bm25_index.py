"""
BM25 全文搜尋索引
用於與向量搜尋結合，透過 Reciprocal Rank Fusion 實現混合搜尋
"""

import re
from typing import Optional

from ..models import Paper


class BM25Index:
    """BM25Okapi 索引，對標題 + 摘要全文建索引"""

    def __init__(self):
        self._papers: list[Paper] = []
        self._bm25 = None

    def build(self, papers: list[Paper]) -> None:
        """從論文清單建立索引（每次查詢前呼叫，或資料更新後重建）"""
        from rank_bm25 import BM25Okapi  # lazy import

        self._papers = papers
        corpus = [self._tokenize(f"{p.title} {p.abstract or ''}") for p in papers]
        self._bm25 = BM25Okapi(corpus)

    def _tokenize(self, text: str) -> list[str]:
        """簡單小寫 + 英文/CJK 分詞"""
        text = text.lower()
        # 英文字 + 數字
        tokens = re.findall(r'\b\w+\b', text)
        # 中文字元逐字切
        cjk = re.findall(r'[一-鿿]', text)
        return tokens + cjk

    def search(self, query: str, top_k: int = 20) -> list[dict]:
        """
        回傳 [{"paper": Paper, "bm25_score": float, "rank": int}, ...]
        只回傳 score > 0 的結果
        """
        if not self._bm25 or not self._papers:
            return []

        tokens = self._tokenize(query)
        scores = self._bm25.get_scores(tokens)

        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        rank = 1
        for idx, score in indexed[:top_k]:
            if score <= 0:
                break
            results.append({
                "paper": self._papers[idx],
                "bm25_score": float(score),
                "rank": rank,
            })
            rank += 1

        return results

    @property
    def is_built(self) -> bool:
        return self._bm25 is not None


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    paper_id_keys: list[str],
    k: int = 60,
) -> list[dict]:
    """
    Reciprocal Rank Fusion 合併多個排名列表

    Args:
        ranked_lists: 各搜尋方式的結果清單，每個元素是 list[dict]
        paper_id_keys: 每個列表中用來取得 paper id 的方式，
                       若為 "paper_id" 則直接用 item["paper_id"]，
                       若為 "paper" 則用 item["paper"].id
        k: RRF 平滑常數（通常 60）

    Returns:
        [{"paper_id": int, "rrf_score": float, "paper": Paper, ...}, ...]
        按 rrf_score 遞減排序
    """
    rrf_scores: dict[int, float] = {}
    paper_objects: dict[int, object] = {}

    for results, id_key in zip(ranked_lists, paper_id_keys):
        for rank, item in enumerate(results, start=1):
            if id_key == "paper":
                pid = item["paper"].id
                paper_objects[pid] = item["paper"]
            else:
                pid = item[id_key]
                if "paper" in item:
                    paper_objects[pid] = item["paper"]

            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (k + rank)

    sorted_ids = sorted(rrf_scores, key=lambda pid: rrf_scores[pid], reverse=True)
    return [
        {
            "paper_id": pid,
            "rrf_score": rrf_scores[pid],
            "paper": paper_objects.get(pid),
        }
        for pid in sorted_ids
        if paper_objects.get(pid) is not None
    ]
