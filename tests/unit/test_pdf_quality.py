"""
Unit tests — PDF text quality assessment (smartpaper/processing/pdf_parser.py)
驗證 _assess_text_quality 對各種文字品質的判斷
"""
import pytest
from smartpaper.processing.pdf_parser import _assess_text_quality, ParseResult


class TestAssessTextQuality:
    def test_normal_english_text_no_warning(self):
        text = (
            "This paper presents a novel approach to academic paper recommendation "
            "using deep learning techniques. We evaluate our method on three benchmark "
            "datasets and demonstrate state-of-the-art performance."
        ) * 5
        score, warning = _assess_text_quality(text)
        assert score >= 0.5
        assert warning is None

    def test_empty_text_returns_zero(self):
        score, warning = _assess_text_quality("")
        assert score == 0.0
        assert warning is None

    def test_very_short_text_returns_zero(self):
        score, warning = _assess_text_quality("hi")
        assert score == 0.0

    def test_garbled_text_triggers_warning(self):
        # Simulate garbled/scanned PDF output: mostly non-letter characters
        garbled = "�" * 200 + "\x01\x02\x03" * 50 + "abc" * 10
        score, warning = _assess_text_quality(garbled)
        assert warning is not None
        assert "OCR" in warning or "quality" in warning.lower()

    def test_high_control_chars_triggers_warning(self):
        # High ratio of control characters (bytes < 32)
        ctrl_text = "\x01\x02\x03" * 100 + "hello world " * 5
        score, warning = _assess_text_quality(ctrl_text)
        assert warning is not None

    def test_replacement_chars_triggers_warning(self):
        # Unicode replacement character (common in bad PDF extraction)
        bad_text = "This is text with many replacement chars " + "�" * 100
        score, warning = _assess_text_quality(bad_text)
        assert warning is not None

    def test_reasonable_mixed_text_no_warning(self):
        # Academic text with numbers and punctuation but mostly letters
        text = (
            "3.1 Experimental Setup. We trained the model for 50 epochs "
            "with a learning rate of 1e-4. The dataset contains 10,000 samples "
            "across 5 categories. Table 2 shows the results."
        ) * 10
        score, warning = _assess_text_quality(text)
        assert score >= 0.4


class TestParseResultQualityFields:
    def test_quality_fields_exist(self):
        result = ParseResult()
        assert hasattr(result, "quality_warning")
        assert hasattr(result, "char_count")
        assert result.quality_warning is None
        assert result.char_count == 0

    def test_quality_warning_is_optional_string(self):
        result = ParseResult(quality_warning="⚠ Some warning")
        assert isinstance(result.quality_warning, str)

    def test_char_count_is_int(self):
        result = ParseResult(char_count=1500)
        assert result.char_count == 1500
