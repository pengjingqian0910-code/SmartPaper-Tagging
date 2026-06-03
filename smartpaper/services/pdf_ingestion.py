"""
PDF 全文匯入服務
整合 PDF 解析 → SQLite chunk 儲存 → ChromaDB 向量化
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..database.chunk_store import ChunkStore
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..processing.pdf_parser import parse_pdf, ParsedChunk


@dataclass
class IngestionResult:
    paper_id: int
    total_chunks: int = 0
    table_chunks: int = 0
    sections: list[str] = field(default_factory=list)
    total_pages: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.total_chunks > 0


class PDFIngestionService:
    """
    PDF 全文匯入服務

    流程：
    1. pdf_parser 解析 PDF → ParsedChunk 列表
    2. 儲存至 SQLite paper_chunks 表（ChunkStore）
    3. 每個 chunk 向量化後存入 ChromaDB fulltext collection
    """

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
        chunk_store: Optional[ChunkStore] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self.chunk_store = chunk_store or ChunkStore()

    def ingest(
        self,
        pdf_path: str | Path,
        paper_id: int,
        replace_existing: bool = True,
        progress_callback=None,   # callback(msg: str)
    ) -> IngestionResult:
        """
        匯入 PDF 全文到指定論文。

        Args:
            pdf_path:         PDF 檔案路徑
            paper_id:         對應的 papers 表 ID
            replace_existing: 若已有全文，是否先刪除再重新匯入

        Returns:
            IngestionResult
        """
        result = IngestionResult(paper_id=paper_id)

        # 確認論文存在
        paper = self.sqlite_db.get_by_id(paper_id)
        if not paper:
            result.error = f"找不到 paper_id={paper_id} 的論文"
            return result

        # 若已有全文且不替換，直接回傳
        if not replace_existing and self.chunk_store.has_fulltext(paper_id):
            existing_count = self.chunk_store.chunk_count(paper_id)
            result.total_chunks = existing_count
            return result

        # 刪除舊資料
        if replace_existing:
            self.chunk_store.delete_by_paper(paper_id)
            self.vector_db.delete_chunks_by_paper(paper_id)

        def _prog(msg):
            if progress_callback:
                progress_callback(msg)

        # 解析 PDF
        _prog("解析 PDF 文字...")
        parse_result = parse_pdf(pdf_path)
        if parse_result.error:
            result.error = parse_result.error
            return result

        if not parse_result.chunks:
            result.error = "PDF 解析後無可用文字（可能為掃描版或空白文件）"
            return result

        result.total_pages = parse_result.total_pages
        result.sections = parse_result.sections_found
        result.table_chunks = parse_result.table_count
        n = len(parse_result.chunks)
        _prog(f"找到 {n} 個 chunk，{parse_result.total_pages} 頁，存入資料庫...")

        # ── 儲存 large chunks（Section 級別，現有行為）──────────────
        chunk_dicts = [
            {
                "section": c.section,
                "chunk_text": c.text,
                "chunk_index": c.chunk_index,
                "page_num": c.page_num,
                "is_table": c.is_table,
                "section_type": c.section_type,
                "importance_weight": c.importance_weight,
            }
            for c in parse_result.chunks
        ]
        self.chunk_store.insert_chunks(paper_id, chunk_dicts)
        result.total_chunks = n

        # ── Small-to-Big：切出 sentence-level small chunks ───────────
        _prog("建立 Small-to-Big 索引（句子級別 chunk）...")
        large_ids = self.chunk_store.get_last_inserted_ids(paper_id, "large")
        small_dicts = []
        for parsed_chunk, large_id in zip(parse_result.chunks, large_ids):
            if parsed_chunk.is_table:
                continue   # 表格不再切小，直接用 large chunk
            for sc in _split_to_small_chunks(
                parsed_chunk.text, parsed_chunk.section,
                parsed_chunk.chunk_index, parsed_chunk.page_num, large_id
            ):
                small_dicts.append(sc)

        small_ids = []
        if small_dicts:
            small_ids = self.chunk_store.insert_small_chunks(paper_id, small_dicts)

        # 儲存 PDF 原始路徑，方便之後直接開啟檔案
        self.sqlite_db.set_pdf_path(paper_id, str(Path(pdf_path).resolve()))

        # ── 向量化：優先索引 small chunks；若無則 fallback large ─────
        _prog(f"向量化 chunk（{len(small_dicts) or n} 個）...")
        if small_dicts and small_ids:
            self._embed_small_chunks(paper_id, small_dicts, small_ids)
        else:
            self._embed_chunks(paper_id, parse_result.chunks)
        _prog(f"完成！{n} 個 large chunk → {len(small_dicts)} 個 small chunk")

        return result

    def delete_fulltext(self, paper_id: int) -> int:
        """
        刪除某篇論文的全文資料（SQLite + ChromaDB）。
        回傳刪除的 chunk 數量。
        """
        deleted = self.chunk_store.delete_by_paper(paper_id)
        self.vector_db.delete_chunks_by_paper(paper_id)
        return deleted

    def has_fulltext(self, paper_id: int) -> bool:
        return self.chunk_store.has_fulltext(paper_id)

    def get_stats(self, paper_id: int) -> dict:
        """回傳某篇論文的全文統計"""
        if not self.chunk_store.has_fulltext(paper_id):
            return {"has_fulltext": False}
        chunks = self.chunk_store.get_by_paper(paper_id)
        sections = list(dict.fromkeys(c.section for c in chunks))  # 保留順序去重
        table_count = sum(1 for c in chunks if c.is_table)
        return {
            "has_fulltext": True,
            "chunk_count": len(chunks),
            "table_count": table_count,
            "sections": sections,
        }

    def papers_with_fulltext(self) -> list[int]:
        return self.chunk_store.papers_with_fulltext()

    # ── 私有方法 ─────────────────────────────────────────────────────────

    def _embed_chunks(self, paper_id: int, chunks: list[ParsedChunk]) -> None:
        """批次向量化 large chunks 並存入 ChromaDB fulltext collection"""
        chunk_dicts = [
            {
                "chunk_index": c.chunk_index,
                "chunk_text": c.text,
                "section": c.section,
                "page_num": c.page_num,
                "is_table": c.is_table,
                "section_type": c.section_type,
                "importance_weight": c.importance_weight,
            }
            for c in chunks
        ]
        try:
            self.vector_db.add_chunks_batch(paper_id, chunk_dicts)
        except Exception as e:
            print(f"[PDFIngestion] 批次向量化失敗: {e}")

    def _embed_small_chunks(
        self, paper_id: int, small_dicts: list[dict], small_ids: list[int]
    ) -> None:
        """批次向量化 small chunks，document ID 包含 SQLite rowid 供 parent 查詢"""
        embed_dicts = []
        for sc, sid in zip(small_dicts, small_ids):
            embed_dicts.append({
                "chunk_index": sc["chunk_index"],
                "chunk_text":  sc["chunk_text"],
                "section":     sc["section"],
                "page_num":    sc.get("page_num"),
                "is_table":    sc.get("is_table", False),
                "section_type": "other",
                "importance_weight": 1.0,
                "small_chunk_id":    sid,            # 額外 metadata
                "parent_chunk_id":   sc["parent_chunk_id"],
            })
        try:
            self.vector_db.add_chunks_batch(
                paper_id, embed_dicts, id_prefix="small"
            )
        except Exception as e:
            print(f"[PDFIngestion] small chunk 向量化失敗: {e}")


# ── module-level helper ───────────────────────────────────────────────

def _split_to_small_chunks(
    text: str,
    section: str,
    base_index: int,
    page_num: int,
    parent_chunk_id: int,
    sentences_per_chunk: int = 3,
) -> list[dict]:
    """
    把一個 large chunk 的文字切成 sentence-level small chunks。
    每個 small chunk = sentences_per_chunk 個句子。
    """
    import re
    # 依句號/問號/驚嘆號斷句，保留標點
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 10]
    if not sentences:
        return []

    small_chunks = []
    for i in range(0, len(sentences), sentences_per_chunk):
        group = sentences[i: i + sentences_per_chunk]
        chunk_text = " ".join(group)
        if len(chunk_text) < 30:
            continue
        small_chunks.append({
            "section":         section,
            "chunk_text":      chunk_text,
            "chunk_index":     base_index * 100 + i,   # 確保不重複
            "page_num":        page_num,
            "is_table":        False,
            "parent_chunk_id": parent_chunk_id,
        })
    return small_chunks
