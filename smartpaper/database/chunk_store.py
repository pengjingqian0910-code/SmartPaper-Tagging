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
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id    INTEGER NOT NULL,
                    section     TEXT    NOT NULL,
                    chunk_text  TEXT    NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    page_num    INTEGER,
                    is_table    INTEGER DEFAULT 0,
                    created_at  TEXT    NOT NULL,
                    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_paper ON paper_chunks(paper_id)"
            )
            conn.commit()

    # ── Write ────────────────────────────────────────────────────────────

    def insert_chunks(self, paper_id: int, chunks: list[dict]) -> int:
        """
        批次插入 chunks。chunks 每個 dict 需有：
        section, chunk_text, chunk_index, page_num, is_table

        回傳插入筆數。
        """
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT INTO paper_chunks
                   (paper_id, section, chunk_text, chunk_index, page_num, is_table, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
        return StoredChunk(
            id=row["id"],
            paper_id=row["paper_id"],
            section=row["section"],
            chunk_text=row["chunk_text"],
            chunk_index=row["chunk_index"],
            page_num=row["page_num"],
            is_table=bool(row["is_table"]),
            created_at=row["created_at"],
        )
