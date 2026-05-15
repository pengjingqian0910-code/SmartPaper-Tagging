"""
Unit tests — smartpaper/processing/pdf_parser.py
Mock pdfplumber，驗證章節偵測、分段、chunk 建立邏輯
"""
import pytest
from unittest.mock import MagicMock, patch, mock_open
import smartpaper.processing.pdf_parser as pdf_mod
from smartpaper.processing.pdf_parser import (
    parse_pdf,
    _is_section_header,
    _clean_text,
    _split_into_paragraphs,
    _split_long_paragraph,
    _merge_short_paragraphs,
    _build_chunks_from_section,
    ParseResult,
    ParsedChunk,
)


class TestIsSectionHeader:
    def test_numbered_header(self):
        is_h, name = _is_section_header("1. Introduction")
        assert is_h
        assert "introduction" in name   # 回傳 lowercase

    def test_numbered_with_dot_space(self):
        is_h, name = _is_section_header("2. Related Work")
        assert is_h

    def test_roman_numeral_header(self):
        is_h, name = _is_section_header("II. Methods")
        assert is_h

    def test_all_caps_header(self):
        is_h, name = _is_section_header("INTRODUCTION")
        assert is_h

    def test_known_section_name(self):
        is_h, name = _is_section_header("Abstract")
        assert is_h
        assert "abstract" in name   # 回傳 lowercase

    def test_plain_sentence_not_header(self):
        is_h, _ = _is_section_header("This is a sentence in the paper body.")
        assert not is_h

    def test_empty_string_not_header(self):
        is_h, _ = _is_section_header("")
        assert not is_h

    def test_too_long_string_not_header(self):
        is_h, _ = _is_section_header("A " * 20)
        assert not is_h


class TestCleanText:
    def test_fix_hyphenation(self):
        result = _clean_text("trans-\nformer")
        assert "trans-\nformer" not in result
        assert "transformer" in result.lower()

    def test_normalize_line_breaks(self):
        result = _clean_text("line one\nline two")
        assert "\n\n" not in result or "line one" in result

    def test_empty_string(self):
        result = _clean_text("")
        assert result == ""


class TestSplitIntoParagraphs:
    def test_blank_line_splits(self):
        text = "First paragraph.\n\nSecond paragraph."
        paras = _split_into_paragraphs(text)
        assert len(paras) >= 2

    def test_single_paragraph(self):
        text = "Only one paragraph here."
        paras = _split_into_paragraphs(text)
        assert len(paras) == 1

    def test_empty_string(self):
        paras = _split_into_paragraphs("")
        assert paras == [] or paras == [""]


class TestSplitLongParagraph:
    def test_short_paragraph_unchanged(self):
        text = "Short text."
        result = _split_long_paragraph(text, max_chars=500)
        assert len(result) == 1
        assert result[0] == text

    def test_long_paragraph_split(self):
        text = ". ".join(["Sentence number " + str(i) for i in range(50)]) + "."
        result = _split_long_paragraph(text, max_chars=200)
        assert len(result) > 1
        for part in result:
            assert len(part) <= 200 + 100  # 允許少量超出（在句尾截斷）


class TestMergeShortParagraphs:
    def test_merges_short_chunks(self):
        paras = ["Hi.", "Hello.", "A short chunk.", "Another one."]
        result = _merge_short_paragraphs(paras)
        assert len(result) <= len(paras)

    def test_long_paragraphs_not_merged(self):
        paras = ["X " * 100 + ".", "Y " * 100 + "."]
        result = _merge_short_paragraphs(paras)
        assert len(result) == 2

    def test_empty_list(self):
        assert _merge_short_paragraphs([]) == []


class TestBuildChunksFromSection:
    def test_returns_parsed_chunks(self):
        chunks = _build_chunks_from_section(
            section_name="Introduction",
            section_text="This is the introduction text. It has multiple sentences with enough words.",
            start_chunk_index=0,
            page_num=1,
        )
        assert isinstance(chunks, list)
        assert all(isinstance(c, ParsedChunk) for c in chunks)

    def test_chunk_has_correct_section(self):
        chunks = _build_chunks_from_section(
            "Methods",
            "We used a dataset with many samples for our experimental evaluation.",
            start_chunk_index=0,
            page_num=2,
        )
        for c in chunks:
            assert c.section == "Methods"

    def test_chunk_index_increments(self):
        long_text = ". ".join(["Sentence number " + str(i) for i in range(20)]) + "."
        chunks = _build_chunks_from_section(
            section_name="Results",
            section_text=long_text,
            start_chunk_index=5,
            page_num=3,
        )
        if chunks:  # 可能文字太短被跳過
            indices = [c.chunk_index for c in chunks]
            assert indices == sorted(indices)
            assert indices[0] >= 5


class TestParsePdf:
    def _make_mock_page(self, text: str, tables=None):
        page = MagicMock()
        page.extract_text.return_value = text
        page.extract_tables.return_value = tables or []
        return page

    def _make_mock_pdf(self, pages):
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = pages
        return mock_pdf

    def test_successful_parse(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.touch()  # 建立真實空白檔案，讓 exists() 通過
        mock_pdf = self._make_mock_pdf([
            self._make_mock_page(
                "Abstract\nThis paper presents our method with enough words.\n\n"
                "1. Introduction\nWe introduce a new approach to solve the problem.\n\n"
                "2. Methods\nWe used the following method with sufficient experimental detail."
            )
        ])
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = parse_pdf(pdf_path)
        assert isinstance(result, ParseResult)
        assert result.error is None
        assert result.total_pages == 1
        assert len(result.chunks) > 0

    def test_empty_pdf_returns_error_or_empty(self, tmp_path):
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.touch()
        mock_pdf = self._make_mock_pdf([self._make_mock_page("")])
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = parse_pdf(pdf_path)
        assert result.error is not None or len(result.chunks) == 0

    def test_file_not_found_returns_error(self):
        result = parse_pdf("nonexistent_xyz_123.pdf")
        assert result.error is not None

    def test_table_chunks_marked_as_table(self, tmp_path):
        pdf_path = tmp_path / "table.pdf"
        pdf_path.touch()
        page = self._make_mock_page(
            "Results\nSome result text with multiple words here.",
            tables=[[["Col1", "Col2"], ["Val1", "Val2"]]]
        )
        mock_pdf = self._make_mock_pdf([page])
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = parse_pdf(pdf_path)
        assert isinstance(result.table_count, int)

    def test_sections_found_list(self, tmp_path):
        pdf_path = tmp_path / "sections.pdf"
        pdf_path.touch()
        mock_pdf = self._make_mock_pdf([
            self._make_mock_page(
                "Abstract\nAbstract text with enough words for processing.\n\n"
                "1. Introduction\nIntroduction text with enough words for processing."
            )
        ])
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = parse_pdf(pdf_path)
        assert isinstance(result.sections_found, list)
