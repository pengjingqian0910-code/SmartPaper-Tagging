"""
PDF 直接匯入服務
從 PDF 自動萃取論文 Metadata → 建立 Paper 紀錄 → 全文向量化
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..api.gemini import GeminiTagger
from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper
from ..processing.pdf_parser import parse_pdf
from .pdf_ingestion import PDFIngestionService


@dataclass
class ExtractedMeta:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    abstract: str = ""
    doi: str = ""
    tags: list[str] = field(default_factory=list)
    raw_text_preview: str = ""  # 供 UI 顯示前幾段


@dataclass
class PDFImportResult:
    success: bool = False
    paper_id: Optional[int] = None
    total_chunks: int = 0
    meta: Optional[ExtractedMeta] = None
    error: Optional[str] = None


class PDFImportService:
    """
    從 PDF 直接建立論文：
    1. parse_pdf() 萃取原始文字
    2. Gemini LLM 解析標題、作者、年份、期刊、摘要、DOI
    3. GeminiTagger 生成標籤
    4. SQLiteDB.insert() 建立 Paper 紀錄
    5. PDFIngestionService.ingest() 全文向量化
    """

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
    ):
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self._ingestor = PDFIngestionService(
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
        )

    # ── 公開方法 ──────────────────────────────────────────────────────

    def extract_meta(
        self,
        pdf_path: str | Path,
        progress_callback=None,
    ) -> ExtractedMeta:
        """
        只萃取 Metadata，不寫入資料庫。
        供 UI 顯示預覽讓使用者確認後再匯入。
        """
        def _prog(msg):
            if progress_callback:
                progress_callback(msg)

        _prog("解析 PDF 文字...")
        parse_result = parse_pdf(pdf_path)
        if parse_result.error:
            return ExtractedMeta(title="（解析失敗）", abstract=parse_result.error)

        # 取前 3 頁（或前 ~4000 字元）作為 LLM 輸入
        preamble = self._preamble_text(parse_result.chunks, max_chars=4000)

        _prog("LLM 萃取論文 Metadata...")
        meta = self._llm_extract_meta(preamble)
        meta.raw_text_preview = preamble[:600]

        if meta.abstract and GEMINI_API_KEY:
            _prog("LLM 生成標籤...")
            try:
                tagger = GeminiTagger()
                result = tagger.generate_tags(meta.abstract, title=meta.title, num_tags=6)
                meta.tags = result.tags
            except Exception as e:
                print(f"[PDFImport] 標籤生成失敗: {e}")

        _prog("完成預覽萃取")
        return meta

    def import_from_pdf(
        self,
        pdf_path: str | Path,
        meta: ExtractedMeta,
        progress_callback=None,
    ) -> PDFImportResult:
        """
        使用（使用者確認過的）meta 建立 Paper 紀錄，並全文向量化。
        """
        def _prog(msg):
            if progress_callback:
                progress_callback(msg)

        if not meta.title.strip():
            return PDFImportResult(success=False, error="論文標題不能為空")

        # 重複性檢查
        if self.sqlite_db.exists(title=meta.title, doi=meta.doi or None):
            return PDFImportResult(
                success=False,
                error=f"論文已存在（標題或 DOI 相同）：{meta.title[:60]}",
            )

        paper = Paper(
            title=meta.title.strip(),
            abstract=meta.abstract.strip() if meta.abstract else None,
            doi=meta.doi.strip() if meta.doi else None,
            authors=meta.authors,
            year=meta.year,
            venue=meta.venue.strip() if meta.venue else None,
            tags=meta.tags,
            source="pdf_import",
        )

        _prog("寫入論文紀錄到資料庫...")
        paper_id = self.sqlite_db.insert(paper)

        _prog("全文向量化中...")
        ingest_result = self._ingestor.ingest(
            pdf_path,
            paper_id,
            replace_existing=True,
            progress_callback=progress_callback,
        )

        if not ingest_result.success:
            # 全文解析失敗也沒關係，至少 metadata 已存
            return PDFImportResult(
                success=True,
                paper_id=paper_id,
                total_chunks=0,
                meta=meta,
                error=f"Metadata 已儲存，但全文向量化失敗：{ingest_result.error}",
            )

        return PDFImportResult(
            success=True,
            paper_id=paper_id,
            total_chunks=ingest_result.total_chunks,
            meta=meta,
        )

    # ── 私有方法 ──────────────────────────────────────────────────────

    def _preamble_text(self, chunks, max_chars: int = 4000) -> str:
        """取前幾個 chunk 的文字（頁面前段）作為 LLM 輸入"""
        texts = []
        total = 0
        for c in chunks:
            page = getattr(c, "page_num", 99)
            if page is not None and page > 4:
                break
            texts.append(c.text)
            total += len(c.text)
            if total >= max_chars:
                break
        return "\n\n".join(texts)[:max_chars]

    def _llm_extract_meta(self, preamble_text: str) -> ExtractedMeta:
        """呼叫 Gemini 解析論文 Metadata"""
        if not GEMINI_API_KEY:
            return ExtractedMeta(
                title="（未設定 GEMINI_API_KEY，無法自動萃取）",
                raw_text_preview=preamble_text[:600],
            )

        from google import genai as _genai
        client = _genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""你是論文 Metadata 萃取專家。
請從以下論文首頁文字中，萃取結構化資訊，並以 JSON 格式回傳。

論文文字（前幾頁）：
---
{preamble_text}
---

請回傳以下 JSON（若某欄位無法確定請留空字串或 null）：
{{
  "title": "論文完整標題",
  "authors": ["作者1", "作者2"],
  "year": 2024,
  "venue": "期刊或會議名稱（縮寫即可）",
  "abstract": "論文摘要完整內容",
  "doi": "10.xxxx/xxxx 或空字串"
}}

注意：
- title 必填，不要缺漏
- abstract 若文字中有就完整複製，若沒找到就輸出空字串
- year 為整數（如 2023），找不到就 null
- authors 是列表，每個元素是一位作者姓名
- 只回傳 JSON，不要有其他說明文字"""

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = response.text.strip()
            # 剝除 markdown code block
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            year = data.get("year")
            if isinstance(year, str):
                m = re.search(r"\d{4}", year)
                year = int(m.group()) if m else None
            elif isinstance(year, int):
                pass
            else:
                year = None

            return ExtractedMeta(
                title=str(data.get("title", "") or "").strip(),
                authors=[str(a).strip() for a in (data.get("authors") or []) if a],
                year=year,
                venue=str(data.get("venue", "") or "").strip(),
                abstract=str(data.get("abstract", "") or "").strip(),
                doi=str(data.get("doi", "") or "").strip(),
            )
        except Exception as e:
            print(f"[PDFImport] LLM 萃取失敗: {e}")
            return ExtractedMeta(raw_text_preview=preamble_text[:600])
