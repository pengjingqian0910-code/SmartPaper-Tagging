"""
SQLite 資料庫操作模組
處理論文 Metadata 的持久化存儲
"""

import sqlite3
import json
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from ..models import Paper
from ..config import SQLITE_DB_PATH

_CACHE_MAX = 2000


class SQLiteDB:
    """SQLite 資料庫管理類"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or SQLITE_DB_PATH
        self._cache: OrderedDict[int, Paper] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._init_db()

    # ── 記憶體 LRU 快取 ───────────────────────────────────────────────

    def _cache_get(self, paper_id: int) -> Optional[Paper]:
        with self._cache_lock:
            if paper_id not in self._cache:
                return None
            self._cache.move_to_end(paper_id)
            return self._cache[paper_id]

    def _cache_put(self, paper: Paper) -> None:
        if paper.id is None:
            return
        with self._cache_lock:
            if paper.id in self._cache:
                self._cache.move_to_end(paper.id)
            else:
                if len(self._cache) >= _CACHE_MAX:
                    self._cache.popitem(last=False)
            self._cache[paper.id] = paper

    def _cache_evict(self, paper_id: int) -> None:
        with self._cache_lock:
            self._cache.pop(paper_id, None)

    def _init_db(self) -> None:
        """初始化資料庫表格"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    abstract TEXT,
                    doi TEXT UNIQUE,
                    tags TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 引用關係表：記錄論文 A 引用論文 B
            conn.execute("""
                CREATE TABLE IF NOT EXISTS citations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    citing_paper_id INTEGER NOT NULL,
                    cited_paper_id INTEGER,
                    cited_doi TEXT,
                    cited_title TEXT,
                    FOREIGN KEY (citing_paper_id) REFERENCES papers(id)
                )
            """)

            # 概念表：方法、資料集、評測指標、任務
            conn.execute("""
                CREATE TABLE IF NOT EXISTS concepts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    UNIQUE(name, type)
                )
            """)

            # 論文與概念的多對多關聯（即倒排索引）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_concepts (
                    paper_id INTEGER NOT NULL,
                    concept_id INTEGER NOT NULL,
                    PRIMARY KEY (paper_id, concept_id),
                    FOREIGN KEY (paper_id) REFERENCES papers(id),
                    FOREIGN KEY (concept_id) REFERENCES concepts(id)
                )
            """)

            # 舊資料庫升級：補充新欄位（IF NOT EXISTS 不適用於欄位，用 try/except）
            for col_def in [
                "ALTER TABLE papers ADD COLUMN authors TEXT",
                "ALTER TABLE papers ADD COLUMN venue TEXT",
                "ALTER TABLE papers ADD COLUMN year INTEGER",
                "ALTER TABLE papers ADD COLUMN citation_count INTEGER",
                "ALTER TABLE papers ADD COLUMN pdf_path TEXT",
            ]:
                try:
                    conn.execute(col_def)
                except Exception:
                    pass  # 欄位已存在則忽略

            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_paper_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_paper_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_doi ON citations(cited_doi)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_concepts_paper ON paper_concepts(paper_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_concepts_concept ON paper_concepts(concept_id)")

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """取得資料庫連接的 context manager"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_paper(self, row: sqlite3.Row) -> Paper:
        """將資料庫 row 轉換為 Paper 物件"""
        keys = row.keys()
        return Paper(
            id=row["id"],
            title=row["title"],
            abstract=row["abstract"],
            doi=row["doi"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            authors=json.loads(row["authors"]) if ("authors" in keys and row["authors"]) else [],
            source=row["source"],
            venue=row["venue"] if "venue" in keys else None,
            year=row["year"] if "year" in keys else None,
            citation_count=row["citation_count"] if "citation_count" in keys else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def insert(self, paper: Paper) -> int:
        """
        新增論文

        Args:
            paper: Paper 物件

        Returns:
            新增的論文 ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO papers (title, abstract, doi, tags, authors, source, venue, year, citation_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper.title,
                    paper.abstract,
                    paper.doi,
                    json.dumps(paper.tags, ensure_ascii=False),
                    json.dumps(paper.authors, ensure_ascii=False),
                    paper.source,
                    paper.venue,
                    paper.year,
                    paper.citation_count,
                    paper.created_at.isoformat(),
                    paper.updated_at.isoformat(),
                ),
            )
            conn.commit()
            paper_id = cursor.lastrowid
        paper.id = paper_id
        self._cache_put(paper)
        return paper_id

    def get_by_id(self, paper_id: int) -> Optional[Paper]:
        cached = self._cache_get(paper_id)
        if cached is not None:
            return cached
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
        if row:
            paper = self._row_to_paper(row)
            self._cache_put(paper)
            return paper
        return None

    def get_by_ids(self, ids: list[int]) -> dict[int, Paper]:
        """批次查詢，先查快取再補 SQL，一次 IN 查詢取回所有未快取論文。"""
        if not ids:
            return {}
        result: dict[int, Paper] = {}
        missing: list[int] = []
        for pid in ids:
            p = self._cache_get(pid)
            if p is not None:
                result[pid] = p
            else:
                missing.append(pid)
        if missing:
            placeholders = ",".join("?" * len(missing))
            with self._get_connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM papers WHERE id IN ({placeholders})", missing
                ).fetchall()
            for row in rows:
                paper = self._row_to_paper(row)
                self._cache_put(paper)
                result[paper.id] = paper
        return result

    def get_by_doi(self, doi: str) -> Optional[Paper]:
        """
        根據 DOI 取得論文

        Args:
            doi: DOI 識別碼

        Returns:
            Paper 物件或 None
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE doi = ?", (doi,)
            ).fetchone()
            return self._row_to_paper(row) if row else None

    def get_by_title(self, title: str) -> Optional[Paper]:
        """
        根據標題取得論文 (精確匹配)

        Args:
            title: 論文標題

        Returns:
            Paper 物件或 None
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE title = ?", (title,)
            ).fetchone()
            return self._row_to_paper(row) if row else None

    def search_by_title(self, keyword: str) -> list[Paper]:
        """
        根據標題關鍵字搜尋論文

        Args:
            keyword: 搜尋關鍵字

        Returns:
            符合的 Paper 清單
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE title LIKE ? ORDER BY updated_at DESC",
                (f"%{keyword}%",),
            ).fetchall()
            return [self._row_to_paper(row) for row in rows]

    def get_by_tag(self, tag: str) -> list[Paper]:
        """
        根據標籤篩選論文

        Args:
            tag: 標籤名稱

        Returns:
            符合的 Paper 清單
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE tags LIKE ? ORDER BY updated_at DESC",
                (f'%"{tag}"%',),
            ).fetchall()
            return [self._row_to_paper(row) for row in rows]

    def get_all(self, limit: int = 100, offset: int = 0) -> list[Paper]:
        """
        取得所有論文 (分頁)

        Args:
            limit: 每頁數量
            offset: 偏移量

        Returns:
            Paper 清單
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [self._row_to_paper(row) for row in rows]

    def update(self, paper: Paper) -> bool:
        """
        更新論文

        Args:
            paper: Paper 物件 (必須包含 id)

        Returns:
            是否更新成功
        """
        if paper.id is None:
            return False

        paper.updated_at = datetime.now()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE papers
                SET title = ?, abstract = ?, doi = ?, tags = ?, authors = ?, source = ?, venue = ?, year = ?, citation_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    paper.title,
                    paper.abstract,
                    paper.doi,
                    json.dumps(paper.tags, ensure_ascii=False),
                    json.dumps(paper.authors, ensure_ascii=False),
                    paper.source,
                    paper.venue,
                    paper.year,
                    paper.citation_count,
                    paper.updated_at.isoformat(),
                    paper.id,
                ),
            )
            conn.commit()
        if cursor.rowcount > 0:
            self._cache_put(paper)
            return True
        return False

    def delete(self, paper_id: int) -> bool:
        """
        刪除論文

        Args:
            paper_id: 論文 ID

        Returns:
            是否刪除成功
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
            conn.commit()
        if cursor.rowcount > 0:
            self._cache_evict(paper_id)
            return True
        return False

    def count(self) -> int:
        """取得論文總數"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM papers").fetchone()
            return row["count"]

    def get_all_tags(self) -> list[str]:
        """取得所有不重複的標籤"""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT tags FROM papers WHERE tags IS NOT NULL").fetchall()

        all_tags = set()
        for row in rows:
            if row["tags"]:
                tags = json.loads(row["tags"])
                all_tags.update(tags)

        return sorted(list(all_tags))

    # ── Citation methods ──────────────────────────────────────────────

    def add_citation(
        self,
        citing_paper_id: int,
        cited_paper_id: Optional[int] = None,
        cited_doi: Optional[str] = None,
        cited_title: Optional[str] = None,
    ) -> None:
        """新增一條引用關係（幂等：相同 citing+cited_doi 不重複插入）"""
        with self._get_connection() as conn:
            if cited_paper_id is not None:
                existing = conn.execute(
                    "SELECT 1 FROM citations WHERE citing_paper_id=? AND cited_paper_id=?",
                    (citing_paper_id, cited_paper_id),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT 1 FROM citations WHERE citing_paper_id=? AND cited_doi=?",
                    (citing_paper_id, cited_doi),
                ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO citations (citing_paper_id, cited_paper_id, cited_doi, cited_title)
                       VALUES (?, ?, ?, ?)""",
                    (citing_paper_id, cited_paper_id, cited_doi, cited_title),
                )
                conn.commit()

    def resolve_citation_paper_ids(self) -> int:
        """嘗試把 cited_doi 對應到資料庫內的論文 ID，回傳更新筆數"""
        updated = 0
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, cited_doi FROM citations WHERE cited_paper_id IS NULL AND cited_doi IS NOT NULL"
            ).fetchall()
            for row in rows:
                match = conn.execute(
                    "SELECT id FROM papers WHERE doi=?", (row["cited_doi"],)
                ).fetchone()
                if match:
                    conn.execute(
                        "UPDATE citations SET cited_paper_id=? WHERE id=?",
                        (match["id"], row["id"]),
                    )
                    updated += 1
            conn.commit()
        return updated

    def get_references(self, paper_id: int) -> list[dict]:
        """取得這篇論文引用的論文列表（cited_paper_id 有值 = 在資料庫內）"""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT c.cited_paper_id, c.cited_doi, c.cited_title,
                          p.title as db_title
                   FROM citations c
                   LEFT JOIN papers p ON c.cited_paper_id = p.id
                   WHERE c.citing_paper_id = ?""",
                (paper_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_citing_papers(self, paper_id: int) -> list[Paper]:
        """取得引用這篇論文的所有論文（在資料庫內）"""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT p.* FROM papers p
                   JOIN citations c ON c.citing_paper_id = p.id
                   WHERE c.cited_paper_id = ?""",
                (paper_id,),
            ).fetchall()
            return [self._row_to_paper(r) for r in rows]

    def citation_count_in_db(self, paper_id: int) -> dict:
        """回傳 {"citing": N, "cited_by": M} 在資料庫內的引用統計"""
        with self._get_connection() as conn:
            citing = conn.execute(
                "SELECT COUNT(*) FROM citations WHERE citing_paper_id=?", (paper_id,)
            ).fetchone()[0]
            cited_by = conn.execute(
                "SELECT COUNT(*) FROM citations WHERE cited_paper_id=?", (paper_id,)
            ).fetchone()[0]
        return {"citing": citing, "cited_by": cited_by}

    def has_citations(self, paper_id: int) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM citations WHERE citing_paper_id=? LIMIT 1", (paper_id,)
            ).fetchone()
            return row is not None

    # ── Concept methods ───────────────────────────────────────────────

    def upsert_concept(self, name: str, concept_type: str) -> int:
        """取得或建立概念，回傳 concept id"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM concepts WHERE name=? AND type=?", (name, concept_type)
            ).fetchone()
            if row:
                return row["id"]
            cursor = conn.execute(
                "INSERT INTO concepts (name, type) VALUES (?, ?)", (name, concept_type)
            )
            conn.commit()
            return cursor.lastrowid

    def add_paper_concept(self, paper_id: int, concept_id: int) -> None:
        """新增論文-概念關聯（忽略重複）"""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO paper_concepts (paper_id, concept_id) VALUES (?, ?)",
                (paper_id, concept_id),
            )
            conn.commit()

    def replace_paper_concepts(self, paper_id: int, concepts: dict) -> None:
        """
        覆蓋某篇論文的所有概念
        concepts 格式：{"method": ["BERT", ...], "dataset": [...], "metric": [...], "task": [...]}
        """
        with self._get_connection() as conn:
            conn.execute("DELETE FROM paper_concepts WHERE paper_id=?", (paper_id,))
            for ctype, names in concepts.items():
                for name in names:
                    name = name.strip()
                    if not name:
                        continue
                    row = conn.execute(
                        "SELECT id FROM concepts WHERE name=? AND type=?", (name, ctype)
                    ).fetchone()
                    if row:
                        cid = row["id"]
                    else:
                        cursor = conn.execute(
                            "INSERT INTO concepts (name, type) VALUES (?, ?)", (name, ctype)
                        )
                        cid = cursor.lastrowid
                    conn.execute(
                        "INSERT OR IGNORE INTO paper_concepts (paper_id, concept_id) VALUES (?, ?)",
                        (paper_id, cid),
                    )
            conn.commit()

    def get_paper_concepts(self, paper_id: int) -> dict:
        """
        取得論文的所有概念，按類型分組
        回傳 {"method": [...], "dataset": [...], "metric": [...], "task": [...]}
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT c.name, c.type FROM concepts c
                   JOIN paper_concepts pc ON c.id = pc.concept_id
                   WHERE pc.paper_id = ?
                   ORDER BY c.type, c.name""",
                (paper_id,),
            ).fetchall()
        result: dict = {}
        for row in rows:
            result.setdefault(row["type"], []).append(row["name"])
        return result

    def _concept_ids_for_paper(self, paper_id: int) -> list[int]:
        """回傳論文的所有 concept_id（供知識圖譜計算共享概念用）"""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT concept_id FROM paper_concepts WHERE paper_id=?", (paper_id,)
            ).fetchall()
        return [r[0] for r in rows]

    def has_concepts(self, paper_id: int) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM paper_concepts WHERE paper_id=? LIMIT 1", (paper_id,)
            ).fetchone()
            return row is not None

    def search_by_concept(self, query: str) -> list[Paper]:
        """
        根據概念名稱搜尋論文（倒排索引查詢）
        回傳包含該概念的論文，依共享概念數遞減排序
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT p.*, COUNT(pc.concept_id) as match_count
                   FROM papers p
                   JOIN paper_concepts pc ON p.id = pc.paper_id
                   JOIN concepts c ON pc.concept_id = c.id
                   WHERE c.name LIKE ?
                   GROUP BY p.id
                   ORDER BY match_count DESC""",
                (f"%{query}%",),
            ).fetchall()
            return [self._row_to_paper(r) for r in rows]

    def get_all_concepts(self, concept_type: Optional[str] = None) -> list[dict]:
        """取得所有概念，可按類型篩選，依使用論文數排序"""
        with self._get_connection() as conn:
            if concept_type:
                rows = conn.execute(
                    """SELECT c.name, c.type, COUNT(pc.paper_id) as paper_count
                       FROM concepts c
                       LEFT JOIN paper_concepts pc ON c.id = pc.concept_id
                       WHERE c.type = ?
                       GROUP BY c.id ORDER BY paper_count DESC""",
                    (concept_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT c.name, c.type, COUNT(pc.paper_id) as paper_count
                       FROM concepts c
                       LEFT JOIN paper_concepts pc ON c.id = pc.concept_id
                       GROUP BY c.id ORDER BY paper_count DESC""",
                ).fetchall()
            return [{"name": r["name"], "type": r["type"], "paper_count": r["paper_count"]} for r in rows]

    def rename_tag(self, old_name: str, new_name: str) -> int:
        """
        把所有論文中的 old_name 標籤改為 new_name（若 new_name 已存在則合併）。
        回傳受影響的論文數。
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, tags FROM papers WHERE tags LIKE ?",
                (f'%"{old_name}"%',),
            ).fetchall()
            updated = 0
            for row in rows:
                tags = json.loads(row["tags"]) if row["tags"] else []
                if old_name not in tags:
                    continue
                new_tags = []
                for t in tags:
                    if t == old_name:
                        if new_name and new_name not in new_tags:
                            new_tags.append(new_name)
                    else:
                        if t not in new_tags:
                            new_tags.append(t)
                conn.execute(
                    "UPDATE papers SET tags=?, updated_at=datetime('now') WHERE id=?",
                    (json.dumps(new_tags, ensure_ascii=False), row["id"]),
                )
                updated += 1
            conn.commit()
        return updated

    def delete_tag(self, tag_name: str) -> int:
        """從所有論文中移除 tag_name，回傳受影響論文數。"""
        return self.rename_tag(tag_name, "")

    def get_tag_counts(self) -> list[tuple[str, int]]:
        """回傳 [(tag, count), ...] 依論文數降序"""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT tags FROM papers WHERE tags IS NOT NULL"
            ).fetchall()
        counter: dict[str, int] = {}
        for row in rows:
            for tag in (json.loads(row["tags"]) if row["tags"] else []):
                counter[tag] = counter.get(tag, 0) + 1
        return sorted(counter.items(), key=lambda x: -x[1])

    def exists(self, title: str = None, doi: str = None) -> bool:
        """
        檢查論文是否已存在

        Args:
            title: 論文標題
            doi: DOI 識別碼

        Returns:
            是否存在
        """
        with self._get_connection() as conn:
            if doi:
                row = conn.execute(
                    "SELECT 1 FROM papers WHERE doi = ?", (doi,)
                ).fetchone()
                if row:
                    return True

            if title:
                row = conn.execute(
                    "SELECT 1 FROM papers WHERE title = ?", (title,)
                ).fetchone()
                if row:
                    return True

        return False

    def set_pdf_path(self, paper_id: int, pdf_path: str) -> None:
        """儲存論文的原始 PDF 檔案路徑"""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE papers SET pdf_path = ? WHERE id = ?",
                (str(pdf_path), paper_id),
            )
            conn.commit()

    def get_pdf_path(self, paper_id: int) -> Optional[str]:
        """取得論文的原始 PDF 檔案路徑，若無則回傳 None"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT pdf_path FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
        return row["pdf_path"] if row and row["pdf_path"] else None
