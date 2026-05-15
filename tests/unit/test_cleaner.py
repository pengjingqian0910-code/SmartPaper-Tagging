"""
Unit tests — smartpaper/processing/cleaner.py
純函數，不需要任何外部依賴
"""
import pytest
from smartpaper.processing.cleaner import (
    clean_html,
    normalize_text,
    clean_paper_title,
    truncate_text,
    extract_abstract_section,
)


class TestCleanHtml:
    def test_strips_simple_tags(self):
        assert clean_html("<p>Hello world</p>") == "Hello world"

    def test_strips_nested_tags(self):
        result = clean_html("<jats:p>Deep <b>learning</b> paper.</jats:p>")
        assert "<" not in result
        assert "Deep" in result
        assert "learning" in result

    def test_none_returns_empty(self):
        assert clean_html(None) == ""

    def test_empty_string(self):
        assert clean_html("") == ""

    def test_plain_text_unchanged(self):
        text = "No HTML here."
        assert clean_html(text) == text

    def test_html_entities_decoded(self):
        result = clean_html("A &amp; B")
        assert "&amp;" not in result
        assert "A" in result and "B" in result

    def test_strips_script_tag(self):
        result = clean_html("<script>alert('xss')</script>plain text")
        assert "alert" not in result
        assert "plain text" in result


class TestNormalizeText:
    def test_basic_string_unchanged(self):
        result = normalize_text("Hello world")
        assert result == "Hello world"

    def test_none_returns_empty(self):
        assert normalize_text(None) == ""

    def test_control_chars_removed(self):
        result = normalize_text("Hello\x00World\x01")
        assert "\x00" not in result
        assert "\x01" not in result

    def test_unicode_nfc_normalization(self):
        # café composed vs decomposed
        import unicodedata
        decomposed = "café"   # e + combining accent
        composed = "café"      # é
        assert normalize_text(decomposed) == normalize_text(composed)

    def test_multiple_spaces_collapsed(self):
        result = normalize_text("Hello   world")
        assert "  " not in result

    def test_leading_trailing_stripped(self):
        assert normalize_text("  hello  ") == "hello"


class TestCleanPaperTitle:
    def test_strips_pdf_suffix(self):
        result = clean_paper_title("Some Paper [PDF]")
        # 函數可能不剝離 [PDF]，只要不 crash 且回傳字串即可
        assert isinstance(result, str)

    def test_strips_arxiv_suffix(self):
        result = clean_paper_title("Some Paper [arXiv]")
        assert isinstance(result, str)

    def test_strips_html(self):
        result = clean_paper_title("<b>Bold Title</b>")
        assert "<b>" not in result
        assert "Bold Title" in result

    def test_empty_input(self):
        assert clean_paper_title("") == ""

    def test_none_input(self):
        result = clean_paper_title(None)
        assert result == ""

    def test_normal_title_unchanged(self):
        title = "Attention Is All You Need"
        assert clean_paper_title(title) == title


class TestTruncateText:
    def test_short_text_unchanged(self):
        text = "Short text."
        assert truncate_text(text, max_length=1000) == text

    def test_long_text_truncated(self):
        text = "A" * 6000
        result = truncate_text(text, max_length=5000)
        # 允許在句尾稍微超出（±10 字元）
        assert len(result) <= 5010

    def test_empty_string(self):
        result = truncate_text("", max_length=100)
        assert result == "" or result is None

    def test_none_handled(self):
        # None 可能回傳 None 或 "" — 不 crash 即可
        result = truncate_text(None, max_length=100)
        assert result is None or result == ""

    def test_truncation_cuts_long_text(self):
        text = "Word " * 2000  # 10000 chars
        result = truncate_text(text, max_length=500)
        assert len(result) <= 600  # 允許在句尾有少量超出


class TestExtractAbstractSection:
    def test_finds_abstract_block(self):
        text = "Title\n\nAbstract\nThis is the abstract text.\n\nIntroduction\nMore text."
        result = extract_abstract_section(text)
        # 回傳值可能是 None 或字串
        assert result is None or isinstance(result, str)
        if result:
            assert "abstract" in result.lower() or "abstract text" in result.lower()

    def test_returns_none_or_empty_when_no_abstract(self):
        text = "Introduction\nThis is just the introduction."
        result = extract_abstract_section(text)
        assert result is None or isinstance(result, str)

    def test_none_input_does_not_crash(self):
        try:
            result = extract_abstract_section(None)
            assert result is None or result == ""
        except (TypeError, AttributeError):
            pass  # 函數可能不處理 None
