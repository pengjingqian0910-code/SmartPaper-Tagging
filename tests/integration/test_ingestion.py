"""
Integration tests — smartpaper/services/ingestion.py
使用暫存 xlsx 驗證欄位偵測與資料讀取
"""
import pytest
import csv
import openpyxl
from pathlib import Path
from smartpaper.services.ingestion import XLSXIngestion


class TestGetHeaders:
    def test_returns_header_list(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            headers = ing.get_headers()
        assert isinstance(headers, list)
        assert len(headers) == 4  # Title, Abstract, DOI, Tags

    def test_header_names_correct(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            headers = ing.get_headers()
        names = [name for _, name in headers]
        assert "Title" in names
        assert "Abstract" in names
        assert "DOI" in names

    def test_headers_include_indices(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            headers = ing.get_headers()
        # 每個 header 是 (int, str) tuple
        for idx, name in headers:
            assert isinstance(idx, int)
            assert isinstance(name, str)


class TestDetectColumns:
    def test_detects_title_column(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
        assert "title" in detected

    def test_detects_abstract_column(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
        assert "abstract" in detected

    def test_detects_doi_column(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
        assert "doi" in detected

    def test_returns_dict(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
        assert isinstance(detected, dict)


class TestReadPapersByIndex:
    def test_reads_all_rows(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            headers = ing.get_headers()
            detected = ing.detect_columns()
            papers = ing.read_papers_by_index(
                title_col=detected["title"],
                abstract_col=detected.get("abstract", -1),
                doi_col=detected.get("doi", -1),
            )
        assert len(papers) == 2  # 2 data rows in fixture

    def test_title_extracted(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
            papers = ing.read_papers_by_index(title_col=detected["title"])
        titles = [p["title"] for p in papers]
        assert any("Attention" in t for t in titles)

    def test_abstract_extracted(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
            papers = ing.read_papers_by_index(
                title_col=detected["title"],
                abstract_col=detected.get("abstract", -1),
            )
        abstracts = [p.get("abstract", "") for p in papers]
        assert any(a for a in abstracts)

    def test_doi_extracted(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            detected = ing.detect_columns()
            papers = ing.read_papers_by_index(
                title_col=detected["title"],
                doi_col=detected.get("doi", -1),
            )
        dois = [p.get("doi", "") for p in papers]
        assert any(d for d in dois)

    def test_empty_rows_skipped(self, tmp_path):
        """空行不應出現在結果中"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Title"])
        ws.append(["Paper One"])
        ws.append([""])         # 空行
        ws.append(["Paper Two"])
        path = tmp_path / "sparse.xlsx"
        wb.save(path)
        with XLSXIngestion(path) as ing:
            papers = ing.read_papers_by_index(title_col=0)
        titles = [p["title"] for p in papers if p.get("title")]
        assert "Paper One" in titles
        assert "Paper Two" in titles


class TestGetRowCount:
    def test_row_count_correct(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            count = ing.get_row_count()
        assert count == 2


class TestCsvSupport:
    def test_reads_csv_file(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Title", "Abstract"])
            writer.writerow(["CSV Paper One", "Abstract one"])
            writer.writerow(["CSV Paper Two", "Abstract two"])

        with XLSXIngestion(csv_path) as ing:
            headers = ing.get_headers()
            papers = ing.read_papers_by_index(title_col=0, abstract_col=1)

        assert len(papers) == 2
        titles = [p["title"] for p in papers]
        assert "CSV Paper One" in titles


class TestContextManager:
    def test_context_manager_closes_without_error(self, sample_xlsx):
        with XLSXIngestion(sample_xlsx) as ing:
            _ = ing.get_headers()
        # 應正常退出，不拋出例外

    def test_explicit_close(self, sample_xlsx):
        ing = XLSXIngestion(sample_xlsx)
        _ = ing.get_headers()
        ing.close()  # 不應拋出例外
