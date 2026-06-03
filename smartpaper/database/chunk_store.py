"""
Chunk 儲存模組
管理 paper_chunks 表（PDF 全文切割後的段落）
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import SQLITE_DB_PATH


@dataclass
class StoredChunk:
    id: int
    paper_id: int
    section: str
    chunk_text: str
    chunk_index: int
    page_num: int
    is_table: bool
    created_at: str
    # Small-to-Big 欄位（可能為 None，代表此 chunk 本身是 large/parent）
    parent_chunk_id: Optional[int] = None
    chunk_level: str = "large"   # "large" | "small"


class ChunkStore:
    """管理 PDF 全文 chunk 的 SQLite 表"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or SQLITE_DB_PATH
        self._init_table()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_table(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_chunks (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id         INTEGER NOT NULL,
                    section          TEXT    NOT NULL,
                    chunk_text       TEXT    NOT NULL,
                    chunk_index      INTEGER NOT NULL,
                    page_num         INTEGER,
                    is_table         INTEGER DEFAULT 0,
                    created_at       TEXT    NOT NULL,
                    parent_chunk_id  INTEGER DEFAULT NULL,
                    chunk_level      TEXT    DEFAULT 'large',
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_paper ON paper_chunks(paper_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_parent ON paper_chunks(parent_chunk_id)"
            )
            # 為舊資料做 schema migration（已有 table 但缺少新欄位）
            for col, definition in [
                ("parent_chunk_id", "INTEGER DEFAULT NULL"),
                ("chunk_level",     "TEXT DEFAULT 'large'"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE paper_chunks ADD COLUMN {col} {definition}")
                except Exception:
                    pass   # column already exists
            conn.commit()

    # ── Write ────────────────────────────────────────────────────────────

    def insert_chunks(self, paper_id: int, chunks: list[dict]) -> int:
        """
        批次插入 large chunks。chunks 每個 dict 需有：
        section, chunk_text, chunk_index, page_num, is_table

        回傳插入筆數。
        """
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO paper_chunks
                   (paper_id, section, chunk_text, chunk_index, page_num,
                    is_table, created_at, parent_chunk_id, chunk_level)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'large')""",
                [
                    (
                        paper_id,
                        c["section"],
                        c["chunk_text"],
                        c["chunk_index"],
                        c.get("page_num"),
                        1 if c.get("is_table") else 0,
                        now,
                    )
                    for c in chunks
                ],
            )
            conn.commit()
        return len(chunks)

    def insert_small_chunks(
        self, paper_id: int, small_chunks: list[dict]
    ) -> list[int]:
        """
        批次插入 small chunks，每個 dict 需有：
        section, chunk_text, chunk_index, page_num, is_table, parent_chunk_id

        回傳新插入的 rowid 列表。
        """
        now = datetime.now().isoformat()
        ids = []
        with self._get_conn() as conn:
            for c in small_chunks:
                cursor = conn.execute(
                    """INSERT INTO paper_chunks
                       (paper_id, section, chunk_text, chunk_index, page_num,
                        is_table, created_at, parent_chunk_id, chunk_level)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'small')""",
                    (
                        paper_id,
                        c["section"],
                        c["chunk_text"],
                        c["chunk_index"],
                        c.get("page_num"),
                        1 if c.get("is_table") else 0,
                        now,
                        c["parent_chunk_id"],
                    ),
                )
                ids.append(cursor.lastrowid)
            conn.commit()
        return ids

    def get_last_inserted_ids(self, paper_id: int, chunk_level: str = "large") -> list[int]:
        """取得某篇論文最新匯入的 large chunk IDs（for building parent refs）"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id FROM paper_chunks
                   WHERE paper_id = ? AND chunk_level = ?
                   ORDER BY chunk_index""",
                (paper_id, chunk_level),
            ).fetchall()
        return [r[0] for r in rows]

    def get_parent_texts(self, parent_ids: list[int]) -> dict[int, "StoredChunk"]:
        """用 parent_chunk_id 批次取得 large chunk（for Small-to-Big 展開）"""
        if not parent_ids:
            return {}
        placeholders = ",".join("?" * len(parent_ids))
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM paper_chunks WHERE id IN ({placeholders})",
                parent_ids,
            ).fetchall()
        return {r["id"]: self._row_to_chunk(r) for r in rows}

    def delete_by_paper(self, paper_id: int) -> int:
        """刪除某篇論文的所有 chunk，回傳刪除筆數"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,)
            )
            conn.commit()
            return cursor.rowcount

    # ── Read ─────────────────────────────────────────────────────────────

    def get_by_paper(self, paper_id: int) -> list[StoredChunk]:
        """取得某篇論文的所有 chunks，按 chunk_index 排序"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM paper_chunks
                   WHERE paper_id = ? ORDER BY chunk_index""",
                (paper_id,),
            ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def has_fulltext(self, paper_id: int) -> bool:
        """該論文是否已有全文 chunk"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM paper_chunks WHERE paper_id = ? LIMIT 1",
                (paper_id,),
            ).fetchone()
        return row is not None

    def chunk_count(self, paper_id: int) -> int:
        """回傳某篇論文的 chunk 總數"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM paper_chunks WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()
        return row[0]

    def papers_with_fulltext(self) -> list[int]:
        """回傳所有已有全文的 paper_id 列表"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT paper_id FROM paper_chunks"
            ).fetchall()
        return [r[0] for r in rows]

    def total_chunks(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM paper_chunks").fetchone()
        return row[0]

    # ── Helper ───────────────────────────────────────────────────────────

    def _row_to_chunk(self, row: sqlite3.Row) -> StoredChunk:
        keys = row.keys()
        return StoredChunk(
            id=row["id"],
            paper_id=row["paper_id"],
            section=row["section"],
            chunk_text=row["chunk_text"],
            chunk_index=row["chunk_index"],
            page_num=row["page_num"],
            is_table=bool(row["is_table"]),
            created_at=row["created_at"],
            parent_chunk_id=row["parent_chunk_id"] if "parent_chunk_id" in keys else None,
            chunk_level=row["chunk_level"] if "chunk_level" in keys else "large",
        )
