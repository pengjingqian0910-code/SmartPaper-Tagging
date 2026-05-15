"""
快速匯入服務：貼上 DOI 或 arXiv ID/URL 直接建立論文
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from ..api.crossref import CrossrefAPI
from ..api.gemini import GeminiTagger
from ..config import GEMINI_API_KEY
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper


class QuickImportService:
    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self._crossref = CrossrefAPI()

    # ── 公開方法 ──────────────────────────────────────────────────────

    def detect_type(self, text: str) -> str:
        """回傳 'doi' | 'arxiv' | 'unknown'"""
        text = text.strip()
        if re.search(r'arxiv', text, re.I) or re.search(r'^\d{4}\.\d{4,5}', text):
            return "arxiv"
        if re.search(r'(^10\.|doi\.org/|doi:\s*10\.)', text, re.I):
            return "doi"
        return "unknown"

    def import_from_text(
        self,
        text: str,
        progress_callback=None,
    ) -> tuple[Optional[Paper], str]:
        """自動偵測格式並匯入，回傳 (Paper, error_msg)"""
        kind = self.detect_type(text.strip())
        if kind == "doi":
            return self.import_by_doi(text, progress_callback)
        elif kind == "arxiv":
            return self.import_by_arxiv(text, progress_callback)
        return None, "無法識別格式，請輸入 DOI（如 10.1145/xxx）或 arXiv ID/URL"

    def import_by_doi(
        self,
        raw: str,
        progress_callback=None,
    ) -> tuple[Optional[Paper], str]:
        def prog(msg):
            if progress_callback:
                progress_callback(msg)

        # 清理 DOI
        doi = re.sub(r'https?://doi\.org/', '', raw, flags=re.I).strip()
        doi = re.sub(r'^doi:\s*', '', doi, flags=re.I).strip()

        prog(f"查詢 Crossref: {doi}...")
        cr = self._crossref.get_by_doi(doi)
        if not cr:
            prog("Crossref 找不到，嘗試標題搜尋...")
            cr = self._crossref.search_by_title(doi)
        if not cr:
            return None, f"Crossref 找不到此 DOI：{doi}"

        if self.sqlite_db.exists(doi=doi, title=cr.title):
            return None, f"論文已存在：{cr.title[:60]}"

        year = _parse_year(cr.published_date)
        paper = Paper(
            title=cr.title,
            abstract=cr.abstract,
            doi=doi,
            authors=cr.authors,
            venue=cr.journal,
            year=year,
            source="crossref",
            tags=[],
        )
        paper = self._enrich_tags(paper, prog)
        return self._save_paper(paper, prog)

    def import_by_arxiv(
        self,
        raw: str,
        progress_callback=None,
    ) -> tuple[Optional[Paper], str]:
        def prog(msg):
            if progress_callback:
                progress_callback(msg)

        m = re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', raw)
        if not m:
            return None, f"無法識別 arXiv ID：{raw}"
        arxiv_id = m.group(1)

        prog(f"查詢 arXiv API: {arxiv_id}...")
        try:
            resp = requests.get(
                f"https://export.arxiv.org/api/query?id_list={arxiv_id}",
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as e:
            return None, f"arXiv 連線失敗：{e}"

        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        root = ET.fromstring(resp.text)
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None, f"arXiv 找不到：{arxiv_id}"

        def _text(tag):
            el = entry.find(tag, ns)
            return el.text.strip() if el is not None and el.text else ""

        title = re.sub(r"\s+", " ", _text("atom:title"))
        abstract = _text("atom:summary")
        published = _text("atom:published")
        year = _parse_year(published)

        authors = [
            a.find("atom:name", ns).text.strip()
            for a in entry.findall("atom:author", ns)
            if a.find("atom:name", ns) is not None
        ]

        journal_ref = _text("arxiv:journal_ref")
        venue = journal_ref if journal_ref else "arXiv"
        doi_arxiv = _text("arxiv:doi") or f"10.48550/arXiv.{arxiv_id}"

        if not title:
            return None, "arXiv 回傳無標題"
        if self.sqlite_db.exists(title=title):
            return None, f"論文已存在：{title[:60]}"

        paper = Paper(
            title=title,
            abstract=abstract,
            doi=doi_arxiv,
            authors=authors,
            venue=venue,
            year=year,
            source="arxiv",
            tags=[],
        )
        paper = self._enrich_tags(paper, prog)
        return self._save_paper(paper, prog)

    # ── 私有方法 ──────────────────────────────────────────────────────

    def _enrich_tags(self, paper: Paper, prog) -> Paper:
        if paper.abstract and GEMINI_API_KEY:
            prog("AI 生成標籤...")
            try:
                tagger = GeminiTagger()
                result = tagger.generate_tags(paper.abstract, title=paper.title, num_tags=6)
                paper.tags = result.tags
            except Exception:
                pass
        return paper

    def _save_paper(self, paper: Paper, prog) -> tuple[Paper, str]:
        prog("寫入資料庫...")
        paper_id = self.sqlite_db.insert(paper)
        paper.id = paper_id

        if paper.abstract:
            prog("向量化摘要...")
            try:
                self.vector_db.add_paper(paper_id, paper.abstract, {
                    "title": paper.title,
                    "tags": ",".join(paper.tags),
                })
            except Exception as e:
                print(f"[QuickImport] 向量化失敗: {e}")

        return paper, ""


def _parse_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    m = re.search(r"\d{4}", date_str)
    return int(m.group()) if m else None
