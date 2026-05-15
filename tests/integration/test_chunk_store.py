"""
Integration tests — smartpaper/database/chunk_store.py
使用暫存 SQLite 驗證 PDF chunk 儲存邏輯
"""
import pytest
from smartpaper.database.chunk_store import ChunkStore, StoredChunk


def _make_chunks(paper_id: int, n: int = 3) -> list[dict]:
    return [
        {
            "section": f"Section {i}",
            "chunk_text": f"This is chunk {i} content with enough words to be useful.",
            "chunk_index": i,
            "page_num": i + 1,
            "is_table": (i == 0),
        }
        for i in range(n)
    ]


class TestInsertAndGet:
    def test_insert_returns_count(self, chunk_store):
        chunks = _make_chunks(paper_id=1, n=5)
        count = chunk_store.insert_chunks(1, chunks)
        assert count == 5

    def test_get_by_paper_returns_all(self, chunk_store):
        chunks = _make_chunks(1, 3)
        chunk_store.insert_chunks(1, chunks)
        stored = chunk_store.get_by_paper(1)
        assert len(stored) == 3

    def test_get_returns_stored_chunk_type(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 1))
        stored = chunk_store.get_by_paper(1)
        assert isinstance(stored[0], StoredChunk)

    def test_chunk_text_preserved(self, chunk_store):
        chunks = [{"section": "Intro", "chunk_text": "Unique content XYZ.",
                   "chunk_index": 0, "page_num": 1, "is_table": False}]
        chunk_store.insert_chunks(1, chunks)
        stored = chunk_store.get_by_paper(1)
        assert stored[0].chunk_text == "Unique content XYZ."

    def test_is_table_flag_preserved(self, chunk_store):
        chunks = _make_chunks(1, 3)
        chunk_store.insert_chunks(1, chunks)
        stored = chunk_store.get_by_paper(1)
        # chunk_index=0 是 table
        table_chunks = [c for c in stored if c.is_table]
        assert len(table_chunks) >= 1

    def test_chunks_ordered_by_index(self, chunk_store):
        chunks = _make_chunks(1, 4)
        chunk_store.insert_chunks(1, chunks)
        stored = chunk_store.get_by_paper(1)
        indices = [c.chunk_index for c in stored]
        assert indices == sorted(indices)

    def test_different_papers_isolated(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 2))
        chunk_store.insert_chunks(2, _make_chunks(2, 3))
        assert len(chunk_store.get_by_paper(1)) == 2
        assert len(chunk_store.get_by_paper(2)) == 3


class TestHasFulltext:
    def test_false_when_empty(self, chunk_store):
        assert not chunk_store.has_fulltext(1)

    def test_true_after_insert(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 1))
        assert chunk_store.has_fulltext(1)

    def test_false_after_delete(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 2))
        chunk_store.delete_by_paper(1)
        assert not chunk_store.has_fulltext(1)


class TestChunkCount:
    def test_count_correct(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 5))
        assert chunk_store.chunk_count(1) == 5

    def test_count_zero_no_chunks(self, chunk_store):
        assert chunk_store.chunk_count(99) == 0

    def test_total_chunks_sums_all(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 3))
        chunk_store.insert_chunks(2, _make_chunks(2, 4))
        assert chunk_store.total_chunks() == 7


class TestDeleteByPaper:
    def test_delete_removes_chunks(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 3))
        deleted = chunk_store.delete_by_paper(1)
        assert deleted == 3
        assert chunk_store.get_by_paper(1) == []

    def test_delete_only_targets_paper(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 2))
        chunk_store.insert_chunks(2, _make_chunks(2, 3))
        chunk_store.delete_by_paper(1)
        assert chunk_store.chunk_count(2) == 3

    def test_delete_nonexistent_returns_zero(self, chunk_store):
        count = chunk_store.delete_by_paper(99999)
        assert count == 0


class TestPapersWithFulltext:
    def test_returns_paper_ids(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 1))
        chunk_store.insert_chunks(3, _make_chunks(3, 1))
        ids = chunk_store.papers_with_fulltext()
        assert 1 in ids
        assert 3 in ids

    def test_empty_when_no_chunks(self, chunk_store):
        assert chunk_store.papers_with_fulltext() == []

    def test_excludes_deleted_paper(self, chunk_store):
        chunk_store.insert_chunks(1, _make_chunks(1, 1))
        chunk_store.insert_chunks(2, _make_chunks(2, 1))
        chunk_store.delete_by_paper(1)
        ids = chunk_store.papers_with_fulltext()
        assert 1 not in ids
        assert 2 in ids
