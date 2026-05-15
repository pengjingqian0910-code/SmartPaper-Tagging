"""
論文去重服務
使用 fuzzy title 比對找出重複或近似重複的論文
"""

import re
from difflib import SequenceMatcher
from typing import Optional

from ..models import Paper
from ..database.sqlite_db import SQLiteDB


def _normalize(title: str) -> str:
    """標題正規化：小寫、去除標點、壓縮空白"""
    title = title.lower()
    title = re.sub(r'[^\w\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


class Deduplicator:
    """論文去重服務"""

    def __init__(self, sqlite_db: Optional[SQLiteDB] = None):
        self.db = sqlite_db or SQLiteDB()

    def find_duplicates(
        self,
        papers: Optional[list[Paper]] = None,
        threshold: float = 0.85,
    ) -> list[list[Paper]]:
        """
        找出標題相似度超過 threshold 的論文組

        Args:
            papers: 論文清單（None 則讀取全部）
            threshold: 相似度門檻 (0-1)，預設 0.85

        Returns:
            重複組清單，每組包含 2 篇以上相似論文
        """
        if papers is None:
            papers = self.db.get_all(limit=5000)

        used: set[int] = set()
        groups: list[list[Paper]] = []

        for i, p1 in enumerate(papers):
            if i in used:
                continue
            group = [p1]
            for j in range(i + 1, len(papers)):
                if j in used:
                    continue
                p2 = papers[j]
                # 先比 DOI（如果兩者都有 DOI 且相同，一定重複）
                if p1.doi and p2.doi and p1.doi.lower() == p2.doi.lower():
                    group.append(p2)
                    used.add(j)
                elif _similarity(p1.title, p2.title) >= threshold:
                    group.append(p2)
                    used.add(j)

            if len(group) > 1:
                used.add(i)
                groups.append(group)

        return groups

    def merge(self, keep_id: int, delete_ids: list[int]) -> int:
        """
        保留 keep_id 的論文，刪除 delete_ids 中的論文

        Returns:
            實際刪除的筆數
        """
        deleted = 0
        keep = self.db.get_by_id(keep_id)
        if not keep:
            return 0

        for did in delete_ids:
            victim = self.db.get_by_id(did)
            if not victim:
                continue
            # 合併標籤（取聯集）
            merged_tags = list(set(keep.tags or []) | set(victim.tags or []))
            keep.tags = merged_tags
            # 如果保留的論文缺少摘要，從被刪論文補
            if not keep.abstract and victim.abstract:
                keep.abstract = victim.abstract
            # 如果保留的論文缺少 venue/year，從被刪論文補
            if not keep.venue and victim.venue:
                keep.venue = victim.venue
            if not keep.year and victim.year:
                keep.year = victim.year
            self.db.delete(did)
            deleted += 1

        self.db.update(keep)
        return deleted
