"""
搜尋服務模組
提供語義搜尋、BM25 關鍵字搜尋、RRF 混合搜尋
"""

from collections import OrderedDict
from typing import Optional

from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper, SearchResult
from .reranker import Reranker
from .bm25_index import BM25Index, reciprocal_rank_fusion
from .semantic_cache import SemanticCache
from .query_expander import QueryExpander

_QUERY_CACHE_MAX = 128


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
        self._query_cache: OrderedDict[tuple, list] = OrderedDict()
        self._sem_cache = SemanticCache(similarity_threshold=0.93, ttl_seconds=3600)
        self._expander = QueryExpander()

    def _ensure_bm25(self) -> None:
        """懶載入：第一次搜尋時建立 BM25 索引（優先從磁碟快取載入）"""
        if not self._bm25.is_built:
            if not self._bm25.load():          # 磁碟無快取 → 重建並儲存
                papers = self.sqlite_db.get_all(limit=5000)
                self._bm25.build(papers)
                self._bm25.save()              # 序列化到 data/bm25_cache.pkl

    def invalidate_bm25(self) -> None:
        """資料庫更新後讓 BM25 索引、精確快取、語義快取、磁碟快取全部失效"""
        BM25Index.invalidate_cache()
        self._bm25 = BM25Index()
        self._query_cache.clear()
        self._sem_cache.invalidate()

    def cache_stats(self) -> dict:
        """回傳語義快取統計資訊（用於 UI 顯示）"""
        return self._sem_cache.stats()

    def invalidate_search_cache(self) -> None:
        """手動清除 query-level LRU 快取"""
        self._query_cache.clear()

    def _cache_get(self, key: tuple) -> Optional[list]:
        if key not in self._query_cache:
            return None
        self._query_cache.move_to_end(key)
        return self._query_cache[key]

    def _cache_put(self, key: tuple, value: list) -> None:
        if key in self._query_cache:
            self._query_cache.move_to_end(key)
        else:
            if len(self._query_cache) >= _QUERY_CACHE_MAX:
                self._query_cache.popitem(last=False)
        self._query_cache[key] = value

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
        fetch_n = n_results * 3 if use_rerank else n_results
        vector_results = self.vector_db.search(query=query, n_results=fetch_n)

        # 批次查詢，取代 N 次個別 get_by_id
        ids = [vr["paper_id"] for vr in vector_results if vr["score"] >= min_score]
        paper_map = self.sqlite_db.get_by_ids(ids)

        candidates = []
        for vr in vector_results:
            if vr["score"] < min_score:
                continue
            paper = paper_map.get(vr["paper_id"])
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

        效能優化（由快到慢）：
          1. 精確 LRU 快取（O(1)，字串完全相同時命中）
          2. 語義快取（cos_sim ≥ 0.93，相似查詢重用結果）
          3. 完整 pipeline：BM25 + 向量 + CrossEncoder

        Args:
            query: 搜尋查詢
            n_results: 最終回傳結果數量
            use_rerank: 是否最後用 CrossEncoder re-rank

        Returns:
            SearchResult 清單
        """
        # ── Layer 1: 精確 LRU 快取 ────────────────────────────────────
        cache_key = ("hybrid", query, n_results, use_rerank)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # ── Layer 2: 語義快取（模糊命中）────────────────────────────
        sem_hit, sem_result = self._sem_cache.get(query)
        if sem_hit and sem_result is not None:
            # 也寫入精確快取，下次直接命中
            self._cache_put(cache_key, sem_result)
            return sem_result

        # ── 1. 語意搜尋（擴大候選量）
        fetch_n = max(n_results * 3, 30)
        vector_results = self.vector_db.search(query=query, n_results=fetch_n)

        # 批次查詢論文，取代 N 次個別 get_by_id
        vec_ids = [vr["paper_id"] for vr in vector_results]
        paper_cache = self.sqlite_db.get_by_ids(vec_ids)
        semantic_list = [
            {"paper": paper_cache[vr["paper_id"]], "paper_id": vr["paper_id"], "score": vr["score"]}
            for vr in vector_results
            if vr["paper_id"] in paper_cache
        ]

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
                results = [SearchResult(paper=c["paper"], score=c["rerank_score"]) for c in reranked]
                self._cache_put(cache_key, results)
                return results
            except Exception as e:
                print(f"Hybrid re-ranking 失敗: {e}")

        results = [SearchResult(paper=f["paper"], score=f["rrf_score"]) for f in fused[:n_results]]
        self._cache_put(cache_key, results)
        self._sem_cache.put(query, results)   # 寫入語義快取
        return results

    def find_similar(self, paper_id: int, n_results: int = 5) -> list[SearchResult]:
        """找出相似論文"""
        paper = self.sqlite_db.get_by_id(paper_id)
        if not paper or not paper.abstract:
            return []
        results = self.semantic_search(
            query=paper.abstract,
            n_results=n_results + 1,
        )
        return [r for r in results if r.paper.id != paper_id][:n_results]

    # ── Strategy A: Query Expansion ──────────────────────────────────

    def _run_hybrid_no_expand(self, query: str, n_results: int) -> list[SearchResult]:
        """不做查詢擴展的 hybrid 搜尋（供擴展版本呼叫，避免無限遞迴）"""
        fetch_n = max(n_results * 3, 30)
        vector_results = self.vector_db.search(query=query, n_results=fetch_n)
        vec_ids = [vr["paper_id"] for vr in vector_results]
        paper_cache = self.sqlite_db.get_by_ids(vec_ids)
        semantic_list = [
            {"paper": paper_cache[vr["paper_id"]], "paper_id": vr["paper_id"], "score": vr["score"]}
            for vr in vector_results if vr["paper_id"] in paper_cache
        ]
        self._ensure_bm25()
        bm25_raw = self._bm25.search(query, top_k=fetch_n)
        bm25_list = []
        for r in bm25_raw:
            paper_cache[r["paper"].id] = r["paper"]
            bm25_list.append({"paper": r["paper"], "paper_id": r["paper"].id, "bm25_score": r["bm25_score"]})
        fused = reciprocal_rank_fusion([semantic_list, bm25_list], ["paper_id", "paper_id"])
        for item in fused:
            if item["paper"] is None:
                item["paper"] = paper_cache.get(item["paper_id"])
        return [
            SearchResult(paper=f["paper"], score=f["rrf_score"])
            for f in fused if f["paper"] is not None
        ][:n_results * 2]

    # ── Strategy C: Tag-based Citation Expansion ──────────────────────

    def _expand_by_tags(
        self,
        results: list[SearchResult],
        n_add: int = 3,
    ) -> list[SearchResult]:
        """
        用頂部結果的 tag 集合找出相關但未出現的論文，
        以 0.4 × 最高分作為加入分數（近似引用圖擴展）。
        """
        if not results:
            return results

        existing_ids = {r.paper.id for r in results}
        top_tags: set[str] = set()
        for r in results[:5]:
            top_tags.update(r.paper.tags or [])

        if not top_tags:
            return results

        max_score = results[0].score
        added, seen_ids = [], set(existing_ids)
        for tag in list(top_tags)[:6]:
            for paper in self.sqlite_db.get_by_tag(tag):
                if paper.id not in seen_ids and len(added) < n_add:
                    added.append(SearchResult(paper=paper, score=max_score * 0.40))
                    seen_ids.add(paper.id)

        return results + added

    # ── Strategy D: Personalized Ranking ─────────────────────────────

    def _personalize(self, results: list[SearchResult]) -> list[SearchResult]:
        """
        對 starred / already-read 論文給予分數加成，
        使用 multiplicative boost 避免推爆上限。
        """
        for r in results:
            if r.paper.starred:
                # +12% of remaining headroom
                r.score = r.score + (1.0 - r.score) * 0.12
            elif getattr(r.paper, "read_status", "unread") == "read":
                r.score = r.score + (1.0 - r.score) * 0.04
        return sorted(results, key=lambda x: x.score, reverse=True)

    # ── Enhanced hybrid_search: A + C + D ────────────────────────────

    def enhanced_search(
        self,
        query: str,
        n_results: int = 10,
        use_rerank: bool = True,
        use_expansion: bool = True,
        use_tag_expand: bool = True,
        use_personalize: bool = True,
    ) -> list[SearchResult]:
        """
        完整四策略搜尋管線：
          A. Query Expansion  → 擴大召回率
          hybrid              → BM25 + 向量 + RRF + CrossEncoder
          C. Tag Expansion    → 引用圖近似擴展
          D. Personalization  → 個人偏好排序

        呼叫方式與 hybrid_search() 相同，可直接替換。
        """
        # ── Layer 1: 精確 LRU 快取 ───────────────────────────────────
        cache_key = ("enhanced", query, n_results, use_rerank)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # ── Layer 2: 語義快取 ────────────────────────────────────────
        sem_hit, sem_result = self._sem_cache.get(query)
        if sem_hit and sem_result is not None:
            self._cache_put(cache_key, sem_result)
            return sem_result

        # ── A: 查詢擴展（生成 0-2 個額外查詢）──────────────────────
        queries = [query]
        if use_expansion:
            variants = self._expander.expand(query)
            queries.extend(variants)

        # ── 對每個查詢跑 hybrid，以 RRF 再合併 ──────────────────────
        all_ranked_lists = []
        paper_pool: dict[int, Paper] = {}

        for q in queries:
            sub_results = self._run_hybrid_no_expand(q, n_results * 2)
            ranked = []
            for r in sub_results:
                paper_pool[r.paper.id] = r.paper
                ranked.append({"paper_id": r.paper.id, "paper": r.paper, "score": r.score})
            all_ranked_lists.append(ranked)

        if len(all_ranked_lists) > 1:
            fused = reciprocal_rank_fusion(all_ranked_lists, ["paper_id"] * len(all_ranked_lists))
            for item in fused:
                if item["paper"] is None:
                    item["paper"] = paper_pool.get(item["paper_id"])
            candidates = [
                {"paper": f["paper"], "document":
                 f"{f['paper'].title}. {(f['paper'].abstract or '')[:300]}"}
                for f in fused if f["paper"] is not None
            ]
        else:
            candidates = [
                {"paper": r.paper, "document":
                 f"{r.paper.title}. {(r.paper.abstract or '')[:300]}"}
                for r in all_ranked_lists[0]
            ] if all_ranked_lists else []

        # ── CrossEncoder re-rank ─────────────────────────────────────
        if use_rerank and candidates:
            try:
                reranked = self.reranker.rerank(
                    query=query,
                    candidates=candidates,
                    text_key="document",
                    top_k=n_results + 3,   # 留 3 個位置給 tag 擴展
                )
                results = [SearchResult(paper=c["paper"], score=c["rerank_score"])
                           for c in reranked]
            except Exception:
                results = [SearchResult(paper=c["paper"], score=0.5)
                           for c in candidates[:n_results]]
        else:
            results = [SearchResult(paper=c["paper"], score=0.5)
                       for c in candidates[:n_results]]

        # ── C: Tag-based 擴展 ────────────────────────────────────────
        if use_tag_expand:
            results = self._expand_by_tags(results, n_add=3)

        # ── D: 個人化排序 ────────────────────────────────────────────
        if use_personalize:
            results = self._personalize(results)

        final = results[:n_results]
        self._cache_put(cache_key, final)
        self._sem_cache.put(query, final)
        return final
