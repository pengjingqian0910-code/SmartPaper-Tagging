"""
Integration tests — smartpaper/services/pdf_ingestion.py
Mock PDF parser + VectorDB，驗證全文匯入服務
"""
import pytest
from unittest.mock import MagicMock, patch
from smartpaper.services.pdf_ingestion import PDFIngestionService, IngestionResult
from smartpaper.processing.pdf_parser import ParseResult, ParsedChunk


def _make_parsed_chunk(idx: int, section: str = "Introduction") -> ParsedChunk:
    return ParsedChunk(
        section=section,
        text=f"This is chunk {idx} with sufficient text content for embedding.",
        chunk_index=idx,
        page_num=idx + 1,
        is_table=False,
    )


def _make_parse_result(n_chunks: int = 3, error: str = None) -> ParseResult:
    chunks = [_make_parsed_chunk(i) for i in range(n_chunks)]
    return ParseResult(
        chunks=chunks,
        total_pages=5,
        sections_found=["Introduction", "Methods", "Results"],
        table_count=0,
        error=error,
    )


def _build_service(db, chunk_store=None, mock_vdb=None):
    if mock_vdb is None:
        mock_vdb = MagicMock()
        mock_vdb.add_chunk = MagicMock()
        mock_vdb.delete_chunks_by_paper = MagicMock()
        mock_vdb.has_fulltext = MagicMock(return_value=False)
    if chunk_store is None:
        from smartpaper.database.chunk_store import ChunkStore
        import tempfile, pathlib
        chunk_store = ChunkStore(db_path=pathlib.Path(tempfile.mkdtemp()) / "chunks.db")

    svc = PDFIngestionService(sqlite_db=db, vector_db=mock_vdb, chunk_store=chunk_store)
    return svc, mock_vdb


class TestIngestionSuccess:
    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_ingest_returns_result(self, mock_parse, db, sample_paper):
        mock_parse.return_value = _make_parse_result(3)
        pid = db.insert(sample_paper)
        svc, _ = _build_service(db)
        result = svc.ingest("dummy.pdf", pid)
        assert isinstance(result, IngestionResult)
        assert result.success

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_total_chunks_correct(self, mock_parse, db, sample_paper):
        mock_parse.return_value = _make_parse_result(5)
        pid = db.insert(sample_paper)
        svc, _ = _build_service(db)
        result = svc.ingest("dummy.pdf", pid)
        assert result.total_chunks == 5

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_chunks_stored_in_sqlite(self, mock_parse, db, sample_paper, chunk_store):
        mock_vdb = MagicMock()
        mock_vdb.add_chunk = MagicMock()
        mock_vdb.delete_chunks_by_paper = MagicMock()
        mock_parse.return_value = _make_parse_result(4)
        pid = db.insert(sample_paper)
        svc = PDFIngestionService(sqlite_db=db, vector_db=mock_vdb, chunk_store=chunk_store)
        svc.ingest("dummy.pdf", pid)
        assert chunk_store.chunk_count(pid) == 4

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_chunks_vectorized(self, mock_parse, db, sample_paper):
        mock_parse.return_value = _make_parse_result(3)
        pid = db.insert(sample_paper)
        svc, mock_vdb = _build_service(db)
        svc.ingest("dummy.pdf", pid)
        assert mock_vdb.add_chunk.call_count == 3

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_sections_recorded(self, mock_parse, db, sample_paper):
        mock_parse.return_value = _make_parse_result(2)
        pid = db.insert(sample_paper)
        svc, _ = _build_service(db)
        result = svc.ingest("dummy.pdf", pid)
        assert isinstance(result.sections, list)
        assert len(result.sections) > 0

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_total_pages_recorded(self, mock_parse, db, sample_paper):
        mock_parse.return_value = _make_parse_result(2)
        pid = db.insert(sample_paper)
        svc, _ = _build_service(db)
        result = svc.ingest("dummy.pdf", pid)
        assert result.total_pages == 5


class TestIngestionFailures:
    def test_paper_not_found_returns_error(self, db):
        svc, _ = _build_service(db)
        result = svc.ingest("dummy.pdf", paper_id=99999)
        assert not result.success
        assert result.error is not None

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_parse_error_propagates(self, mock_parse, db, sample_paper):
        mock_parse.return_value = ParseResult(
            chunks=[], total_pages=0, sections_found=[], table_count=0,
            error="Scanned PDF — no text layer"
        )
        pid = db.insert(sample_paper)
        svc, _ = _build_service(db)
        result = svc.ingest("scanned.pdf", pid)
        assert not result.success
        assert "no text" in result.error.lower() or result.error

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_empty_chunks_not_success(self, mock_parse, db, sample_paper):
        mock_parse.return_value = ParseResult(
            chunks=[], total_pages=2, sections_found=[], table_count=0, error=None
        )
        pid = db.insert(sample_paper)
        svc, _ = _build_service(db)
        result = svc.ingest("empty.pdf", pid)
        assert not result.success


class TestReplaceExisting:
    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_replace_deletes_old_chunks(self, mock_parse, db, sample_paper, chunk_store):
        mock_vdb = MagicMock()
        mock_vdb.add_chunk = MagicMock()
        mock_vdb.delete_chunks_by_paper = MagicMock()
        mock_parse.return_value = _make_parse_result(2)
        pid = db.insert(sample_paper)
        svc = PDFIngestionService(sqlite_db=db, vector_db=mock_vdb, chunk_store=chunk_store)
        svc.ingest("v1.pdf", pid)
        mock_parse.return_value = _make_parse_result(3)
        svc.ingest("v2.pdf", pid, replace_existing=True)
        assert chunk_store.chunk_count(pid) == 3  # 替換後是新的數量

    @patch("smartpaper.services.pdf_ingestion.parse_pdf")
    def test_skip_when_not_replace(self, mock_parse, db, sample_paper, chunk_store):
        mock_vdb = MagicMock()
        mock_vdb.add_chunk = MagicMock()
        mock_vdb.delete_chunks_by_paper = MagicMock()
        mock_parse.return_value = _make_parse_result(2)
        pid = db.insert(sample_paper)
        svc = PDFIngestionService(sqlite_db=db, vector_db=mock_vdb, chunk_store=chunk_store)
        svc.ingest("v1.pdf", pid)
        mock_parse.return_value = _make_parse_result(5)
        svc.ingest("v2.pdf", pid, replace_existing=False)
        # 不替換，chunk 數量維持原本
        assert chunk_store.chunk_count(pid) == 2


class TestDeleteFulltext:
    def test_delete_removes_all(self, db, sample_paper, chunk_store):
        mock_vdb = MagicMock()
        mock_vdb.delete_chunks_by_paper = MagicMock()
        pid = db.insert(sample_paper)
        chunk_store.insert_chunks(pid, [
            {"section": "Intro", "chunk_text": "text", "chunk_index": 0, "page_num": 1, "is_table": False}
        ])
        svc = PDFIngestionService(sqlite_db=db, vector_db=mock_vdb, chunk_store=chunk_store)
        deleted = svc.delete_fulltext(pid)
        assert deleted == 1
        mock_vdb.delete_chunks_by_paper.assert_called_once_with(pid)

    def test_has_fulltext_after_ingest(self, db, sample_paper, chunk_store):
        mock_vdb = MagicMock()
        mock_vdb.add_chunk = MagicMock()
        mock_vdb.delete_chunks_by_paper = MagicMock()
        pid = db.insert(sample_paper)
        with patch("smartpaper.services.pdf_ingestion.parse_pdf") as mock_parse:
            mock_parse.return_value = _make_parse_result(1)
            svc = PDFIngestionService(sqlite_db=db, vector_db=mock_vdb, chunk_store=chunk_store)
            svc.ingest("dummy.pdf", pid)
        assert svc.has_fulltext(pid)
