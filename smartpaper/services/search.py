"""
搜尋服務模組
提供語義搜尋、BM25 關鍵字搜尋、RRF 混合搜尋
"""

from typing import Optional

from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper, SearchResult
from .reranker import Reranker
from .bm25_index import BM25Index, reciprocal_rank_fusion


class SearchService:
    """搜尋服務類"""

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
    ):
        """
        初始化搜尋服務

        Args:
            sqlite_db: SQLite 資料庫實例
            vector_db: 向量資料庫實例
        """
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self.reranker = Reranker()
        self._bm25 = BM25Index()

    def _ensure_bm25(self) -> None:
        """懶載入：第一次搜尋時建立 BM25 索引"""
        if not self._bm25.is_built:
            papers = self.sqlite_db.get_all(limit=5000)
            self._bm25.build(papers)

    def invalidate_bm25(self) -> None:
        """資料庫更新後呼叫此方法讓 BM25 索引失效，下次搜尋自動重建"""
        self._bm25 = BM25Index()

    def semantic_search(
        self,
        query: str,
        n_results: int = 10,
        min_score: float = 0.0,
        use_rerank: bool = True,
    ) -> list[SearchResult]:
        """
        語義搜尋 (透過向量資料庫，可選擇啟用 re-ranking)

        Args:
            query: 搜尋查詢 (自然語言)
            n_results: 回傳結果數量
            min_score: 最低相似度分數過濾
            use_rerank: 是否使用 CrossEncoder re-ranking

        Returns:
            SearchResult 清單
        """
        # 擴大初始搜尋量，讓 re-ranker 有更多候選
        fetch_n = n_results * 3 if use_rerank else n_results
        vector_results = self.vector_db.search(query=query, n_results=fetch_n)

        candidates = []
        for vr in vector_results:
            if vr["score"] < min_score:
                continue
            paper = self.sqlite_db.get_by_id(vr["paper_id"])
            if paper:
                candidates.append({
                    "paper": paper,
                    "score": vr["score"],
                    "document": f"{paper.title}. {paper.abstract[:300] if paper.abstract else ''}",
                })

        if use_rerank and candidates:
            try:
                candidates = self.reranker.rerank(
                    query=query,
                    candidates=candidates,
                    text_key="document",
                    top_k=n_results,
                )
                return [SearchResult(paper=c["paper"], score=c["rerank_score"]) for c in candidates]
            except Exception as e:
                print(f"Re-ranking 失敗，回退到向量搜尋: {e}")

        return [SearchResult(paper=c["paper"], score=c["score"]) for c in candidates[:n_results]]

    def keyword_search(
        self,
        keyword: str,
        search_in: str = "title",
    ) -> list[Paper]:
        """
        關鍵字搜尋 (透過 SQLite)

        Args:
            keyword: 搜尋關鍵字
            search_in: 搜尋欄位 ("title", "abstract", "all")

        Returns:
            Paper 清單
        """
        if search_in == "title":
            return self.sqlite_db.search_by_title(keyword)
        elif search_in == "tag":
            return self.sqlite_db.get_by_tag(keyword)
        else:
            # 搜尋標題
            results = self.sqlite_db.search_by_title(keyword)
            # 也可以擴展搜尋摘要 (需要 SQLite FTS 或自行實作)
            return results

    def search_by_tag(self, tag: str) -> list[Paper]:
        """
        根據標籤搜尋

        Args:
            tag: 標籤名稱

        Returns:
            Paper 清單
        """
        return self.sqlite_db.get_by_tag(tag)

    def get_all_tags(self) -> list[str]:
        """
        取得所有標籤

        Returns:
            標籤清單
        """
        return self.sqlite_db.get_all_tags()

    def bm25_search(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        """
        BM25 全文搜尋（標題 + 摘要）

        Args:
            query: 搜尋查詢
            top_k: 回傳結果數量

        Returns:
            SearchResult 清單
        """
        self._ensure_bm25()
        raw = self._bm25.search(query, top_k=top_k)
        max_score = raw[0]["bm25_score"] if raw else 1.0
        return [
            SearchResult(
                paper=r["paper"],
                score=r["bm25_score"] / max_score,  # 正規化到 0-1
            )
            for r in raw
        ]

    def hybrid_search(
        self,
        query: str,
        n_results: int = 10,
        use_rerank: bool = True,
    ) -> list[SearchResult]:
        """
        BM25 + 向量語意搜尋，透過 Reciprocal Rank Fusion 合併排名

        Args:
            query: 搜尋查詢
            n_results: 最終回傳結果數量
            use_rerank: 是否最後用 CrossEncoder re-rank

        Returns:
            SearchResult 清單
        """
        # ── 1. 語意搜尋（擴大候選量）
        fetch_n = max(n_results * 3, 30)
        vector_results = self.vector_db.search(query=query, n_results=fetch_n)
        semantic_list = []
        paper_cache: dict[int, Paper] = {}
        for vr in vector_results:
            paper = self.sqlite_db.get_by_id(vr["paper_id"])
            if paper:
                paper_cache[paper.id] = paper
                semantic_list.append({"paper": paper, "paper_id": paper.id, "score": vr["score"]})

        # ── 2. BM25 搜尋
        self._ensure_bm25()
        bm25_raw = self._bm25.search(query, top_k=fetch_n)
        bm25_list = []
        for r in bm25_raw:
            paper_cache[r["paper"].id] = r["paper"]
            bm25_list.append({"paper": r["paper"], "paper_id": r["paper"].id, "bm25_score": r["bm25_score"]})

        # ── 3. RRF 合併
        fused = reciprocal_rank_fusion(
            ranked_lists=[semantic_list, bm25_list],
            paper_id_keys=["paper_id", "paper_id"],
        )

        # 補齊 paper 物件（RRF 函式已保留）
        for item in fused:
            if item["paper"] is None:
                item["paper"] = paper_cache.get(item["paper_id"])

        fused = [f for f in fused if f["paper"] is not None]

        # ── 4. CrossEncoder Re-ranking
        if use_rerank and fused:
            try:
                rerank_inputs = [
                    {
                        "paper": f["paper"],
                        "document": f"{f['paper'].title}. {f['paper'].abstract[:300] if f['paper'].abstract else ''}",
                    }
                    for f in fused
                ]
                reranked = self.reranker.rerank(
                    query=query,
                    candidates=rerank_inputs,
                    text_key="document",
                    top_k=n_results,
                )
                return [SearchResult(paper=c["paper"], score=c["rerank_score"]) for c in reranked]
            except Exception as e:
                print(f"Hybrid re-ranking 失敗: {e}")

        return [SearchResult(paper=f["paper"], score=f["rrf_score"]) for f in fused[:n_results]]

    def find_similar(self, paper_id: int, n_results: int = 5) -> list[SearchResult]:
        """
        找出相似論文

        Args:
            paper_id: 論文 ID
            n_results: 回傳結果數量

        Returns:
            相似論文清單
        """
        # 取得論文摘要
        paper = self.sqlite_db.get_by_id(paper_id)
        if not paper or not paper.abstract:
            return []

        # 用摘要作為查詢進行語義搜尋
        results = self.semantic_search(
            query=paper.abstract,
            n_results=n_results + 1,  # +1 因為會包含自己
        )

        # 排除自己
        return [r for r in results if r.paper.id != paper_id][:n_results]
