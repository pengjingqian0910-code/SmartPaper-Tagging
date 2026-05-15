"""
引用關係服務
使用 Semantic Scholar API 建立論文間的引用圖，
並提供 Related Work 候選推薦
"""

from typing import Optional, Callable

from ..database.sqlite_db import SQLiteDB
from ..models import Paper
from ..api import semantic_scholar as ss_api


class CitationService:
    """論文引用關係服務"""

    def __init__(self, sqlite_db: Optional[SQLiteDB] = None):
        self.db = sqlite_db or SQLiteDB()

    # ── 建立引用圖 ────────────────────────────────────────────────────

    def build_citation_graph(
        self,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        skip_existing: bool = True,
    ) -> dict:
        """
        對資料庫中所有有 DOI 的論文，從 Semantic Scholar 取得引用關係

        Args:
            progress_callback: (title, current, total)
            skip_existing: 已有引用資料的論文跳過

        Returns:
            {"processed": N, "skipped": M, "total_links": K}
        """
        all_papers = self.db.get_all(limit=5000)
        papers_with_doi = [p for p in all_papers if p.doi]

        processed = 0
        skipped = 0
        total_links = 0
        total = len(papers_with_doi)

        for idx, paper in enumerate(papers_with_doi):
            if progress_callback:
                progress_callback(paper.title, idx + 1, total)

            if skip_existing and self.db.has_citations(paper.id):
                skipped += 1
                continue

            refs = ss_api.fetch_references(paper.doi)
            for ref in refs:
                self.db.add_citation(
                    citing_paper_id=paper.id,
                    cited_doi=ref.get("doi"),
                    cited_title=ref.get("title"),
                )
                total_links += 1

            processed += 1

        # 嘗試把 cited_doi 對應到資料庫內的論文
        resolved = self.db.resolve_citation_paper_ids()

        return {
            "processed": processed,
            "skipped": skipped,
            "total_links": total_links,
            "resolved_internal": resolved,
        }

    # ── 查詢引用關係 ──────────────────────────────────────────────────

    def get_references(self, paper_id: int) -> dict:
        """
        取得這篇論文引用的論文

        Returns:
            {
                "in_db": [Paper, ...],      # 資料庫中有的論文
                "external": [{"title": ..., "doi": ...}, ...]  # 資料庫外的論文
            }
        """
        rows = self.db.get_references(paper_id)
        in_db = []
        external = []
        for row in rows:
            if row["cited_paper_id"]:
                paper = self.db.get_by_id(row["cited_paper_id"])
                if paper:
                    in_db.append(paper)
            else:
                external.append({
                    "title": row["cited_title"] or "未知標題",
                    "doi": row["cited_doi"],
                })
        return {"in_db": in_db, "external": external}

    def get_citing_papers(self, paper_id: int) -> list[Paper]:
        """取得引用這篇論文的論文（資料庫內）"""
        return self.db.get_citing_papers(paper_id)

    def get_stats(self, paper_id: int) -> dict:
        """取得引用統計"""
        return self.db.citation_count_in_db(paper_id)

    # ── Related Work 推薦 ─────────────────────────────────────────────

    def find_related_work(self, paper_id: int, top_k: int = 10) -> list[dict]:
        """
        為指定論文推薦 Related Work 候選，依相關性排序

        策略：
        1. 直接引用（此論文引用的、且在資料庫中）← 最強信號
        2. 被同樣引用（co-cited）← 同一研究社群
        3. 反向引用（引用此論文的）← 後續工作

        Args:
            paper_id: 論文 ID
            top_k: 回傳前 N 筆

        Returns:
            [{"paper": Paper, "relation": "cites|co-cited|cited-by", "weight": float}, ...]
        """
        scores: dict[int, dict] = {}

        def _add(p: Paper, relation: str, weight: float):
            if p.id == paper_id:
                return
            if p.id not in scores:
                scores[p.id] = {"paper": p, "relation": relation, "weight": 0.0}
            scores[p.id]["weight"] += weight
            # 保留最強的關係標籤
            if weight > scores[p.id]["weight"] - weight:
                scores[p.id]["relation"] = relation

        # 1. 直接引用的論文（在 DB 內）
        refs = self.get_references(paper_id)
        for p in refs["in_db"]:
            _add(p, "直接引用", 3.0)

        # 2. 被同樣引用（co-cited）：找出引用同一批論文的其他論文
        for p in refs["in_db"]:
            co_citers = self.db.get_citing_papers(p.id)
            for co in co_citers:
                _add(co, "共同引用", 1.0)

        # 3. 引用此論文的論文
        citing = self.get_citing_papers(paper_id)
        for p in citing:
            _add(p, "引用此論文", 2.0)

        ranked = sorted(scores.values(), key=lambda x: x["weight"], reverse=True)
        return ranked[:top_k]
