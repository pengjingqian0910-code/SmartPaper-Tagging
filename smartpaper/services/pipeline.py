"""
處理流程模組
整合完整的論文處理工作流程
"""

import time
from pathlib import Path
from typing import Optional, Callable

from ..api.crossref import CrossrefAPI
from ..api.arxiv import ArxivAPI
from ..api.gemini import GeminiTagger
from ..database.sqlite_db import SQLiteDB
from ..database.vector_db import VectorDB
from ..models import Paper, ProcessingStatus
from ..processing.cleaner import clean_html, normalize_text
from ..processing.tagger import AutoTagger
from .ingestion import XLSXIngestion


class Pipeline:
    """論文處理流程類"""

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        vector_db: Optional[VectorDB] = None,
        crossref_api: Optional[CrossrefAPI] = None,
        auto_tagger: Optional[AutoTagger] = None,
    ):
        """
        初始化處理流程

        Args:
            sqlite_db: SQLite 資料庫實例
            vector_db: 向量資料庫實例
            crossref_api: Crossref API 實例
            auto_tagger: 自動標籤器實例
        """
        self.sqlite_db = sqlite_db or SQLiteDB()
        self.vector_db = vector_db or VectorDB()
        self.crossref_api = crossref_api or CrossrefAPI()
        self.arxiv_api = ArxivAPI()
        self.auto_tagger = auto_tagger  # 可以延遲初始化

    def process_xlsx(
        self,
        file_path: str | Path,
        title_column: str = "A",
        skip_existing: bool = True,
        generate_tags: bool = True,
        custom_categories: Optional[list[str]] = None,
        progress_callback: Optional[Callable[[ProcessingStatus], None]] = None,
        api_delay: float = 0.5,
    ) -> ProcessingStatus:
        """
        處理 XLSX 檔案

        Args:
            file_path: XLSX 檔案路徑
            title_column: 標題欄位
            skip_existing: 是否跳過已存在的論文
            generate_tags: 是否自動生成標籤
            custom_categories: 自定義標籤類別
            progress_callback: 進度回調函數
            api_delay: API 請求間隔 (秒)

        Returns:
            處理狀態
        """
        # 初始化 AutoTagger (如果需要)
        if generate_tags and self.auto_tagger is None:
            self.auto_tagger = AutoTagger(custom_categories=custom_categories)

        # 讀取 XLSX
        with XLSXIngestion(file_path) as ingestion:
            titles = ingestion.read_titles(title_column=title_column)

        status = ProcessingStatus(total=len(titles))

        for title in titles:
            try:
                # 檢查是否已存在
                if skip_existing and self.sqlite_db.exists(title=title):
                    status.processed += 1
                    if progress_callback:
                        progress_callback(status)
                    continue

                # 從 Crossref 獲取資訊
                crossref_result = self.crossref_api.search_by_title(title)

                paper = Paper(
                    title=title,
                    source="crossref" if crossref_result else "manual",
                )

                if crossref_result:
                    paper.doi = crossref_result.doi
                    paper.abstract = crossref_result.abstract
                    paper.venue = crossref_result.journal
                    paper.authors = crossref_result.authors or []
                    if crossref_result.published_date:
                        try:
                            paper.year = int(crossref_result.published_date.split("-")[0])
                        except (ValueError, IndexError):
                            pass

                # Crossref 沒取到摘要，嘗試 Arxiv
                if not paper.abstract:
                    arxiv_result = self.arxiv_api.search_by_title(title)
                    if arxiv_result and arxiv_result.get("abstract"):
                        paper.abstract = arxiv_result["abstract"]

                # 生成標籤
                if generate_tags and paper.abstract:
                    tags = self.auto_tagger.tag_paper(
                        paper,
                        custom_categories=custom_categories,
                    )
                    paper.tags = tags

                # 存入資料庫
                paper_id = self.sqlite_db.insert(paper)
                paper.id = paper_id

                # 存入向量資料庫
                if paper.abstract:
                    self.vector_db.add(
                        paper_id=paper_id,
                        abstract=paper.abstract,
                        metadata={"title": paper.title, "tags": ",".join(paper.tags)},
                    )

                status.success += 1

            except Exception as e:
                status.failed += 1
                status.errors.append(f"[{title}] {str(e)}")

            status.processed += 1

            if progress_callback:
                progress_callback(status)

            # API 延遲
            if api_delay > 0:
                time.sleep(api_delay)

        return status

    def process_papers_list(
        self,
        papers: list[dict],
        skip_existing: bool = True,
        generate_tags: bool = True,
        fetch_missing: bool = True,
        custom_categories: Optional[list[str]] = None,
        progress_callback: Optional[Callable[[ProcessingStatus], None]] = None,
        api_delay: float = 0.5,
    ) -> ProcessingStatus:
        """
        處理已解析好的論文 dict 清單（含欄位對應後的資料）。

        papers 每個 dict 可含：title（必要）、abstract、doi、tags。
        - 若已有 abstract，跳過 Crossref 查詢。
        - 若無 abstract 且 fetch_missing=True，嘗試用 Crossref 補齊。
        """
        if generate_tags and self.auto_tagger is None:
            self.auto_tagger = AutoTagger(custom_categories=custom_categories)

        status = ProcessingStatus(total=len(papers))

        for paper_data in papers:
            try:
                title = paper_data["title"]

                if skip_existing and self.sqlite_db.exists(title=title):
                    status.processed += 1
                    if progress_callback:
                        progress_callback(status)
                    continue

                paper = Paper(title=title, source="file")

                # 使用檔案裡已有的欄位
                if paper_data.get("doi"):
                    paper.doi = paper_data["doi"]
                if paper_data.get("abstract"):
                    paper.abstract = paper_data["abstract"]
                if paper_data.get("tags"):
                    paper.tags = paper_data["tags"]

                # 若缺少 abstract，嘗試用 Crossref 補齊
                if not paper.abstract and fetch_missing:
                    crossref_result = self.crossref_api.search_by_title(title)
                    if crossref_result:
                        paper.source = "crossref"
                        if not paper.doi:
                            paper.doi = crossref_result.doi
                        paper.abstract = crossref_result.abstract
                        if not paper.venue:
                            paper.venue = crossref_result.journal
                        if not paper.authors:
                            paper.authors = crossref_result.authors or []
                        if not paper.year and crossref_result.published_date:
                            try:
                                paper.year = int(crossref_result.published_date.split("-")[0])
                            except (ValueError, IndexError):
                                pass
                    if api_delay > 0:
                        time.sleep(api_delay)

                # Crossref 仍然沒有摘要，嘗試 Arxiv
                if not paper.abstract and fetch_missing:
                    arxiv_result = self.arxiv_api.search_by_title(title)
                    if arxiv_result and arxiv_result.get("abstract"):
                        paper.abstract = arxiv_result["abstract"]

                # 生成標籤（若檔案未提供且有 abstract）
                if generate_tags and not paper.tags and paper.abstract:
                    paper.tags = self.auto_tagger.tag_paper(paper, custom_categories=custom_categories)

                paper_id = self.sqlite_db.insert(paper)
                paper.id = paper_id

                if paper.abstract:
                    self.vector_db.add(
                        paper_id=paper_id,
                        abstract=paper.abstract,
                        metadata={"title": paper.title, "tags": ",".join(paper.tags)},
                    )

                status.success += 1

            except Exception as e:
                status.failed += 1
                status.errors.append(f"[{paper_data.get('title', '?')}] {str(e)}")

            status.processed += 1
            if progress_callback:
                progress_callback(status)

        return status

    def process_single(
        self,
        title: str,
        generate_tags: bool = True,
        custom_categories: Optional[list[str]] = None,
    ) -> Optional[Paper]:
        """
        處理單篇論文

        Args:
            title: 論文標題
            generate_tags: 是否生成標籤
            custom_categories: 自定義標籤類別

        Returns:
            處理後的 Paper 或 None
        """
        # 初始化 AutoTagger (如果需要)
        if generate_tags and self.auto_tagger is None:
            self.auto_tagger = AutoTagger(custom_categories=custom_categories)

        # 檢查是否已存在
        existing = self.sqlite_db.get_by_title(title)
        if existing:
            return existing

        # 從 Crossref 獲取資訊
        crossref_result = self.crossref_api.search_by_title(title)

        paper = Paper(
            title=title,
            source="crossref" if crossref_result else "manual",
        )

        if crossref_result:
            paper.doi = crossref_result.doi
            paper.abstract = crossref_result.abstract
            paper.venue = crossref_result.journal
            paper.authors = crossref_result.authors or []
            if crossref_result.published_date:
                try:
                    paper.year = int(crossref_result.published_date.split("-")[0])
                except (ValueError, IndexError):
                    pass

        # 生成標籤
        if generate_tags and paper.abstract and self.auto_tagger:
            tags = self.auto_tagger.tag_paper(paper, custom_categories=custom_categories)
            paper.tags = tags

        # 存入資料庫
        paper_id = self.sqlite_db.insert(paper)
        paper.id = paper_id

        # 存入向量資料庫
        if paper.abstract:
            self.vector_db.add(
                paper_id=paper_id,
                abstract=paper.abstract,
                metadata={"title": paper.title, "tags": ",".join(paper.tags)},
            )

        return paper

    def update_metadata_from_list(
        self,
        papers: list[dict],
        progress_callback: Optional[Callable[[ProcessingStatus], None]] = None,
    ) -> ProcessingStatus:
        """
        針對已存在的論文，補齊 authors / venue / year / abstract（只補空缺，不覆蓋已有資料）。
        """
        status = ProcessingStatus(total=len(papers))
        for paper_data in papers:
            try:
                title = paper_data.get("title", "")
                existing = self.sqlite_db.get_by_title(title)
                if existing:
                    changed = False
                    if paper_data.get("authors") and not existing.authors:
                        existing.authors = paper_data["authors"]
                        changed = True
                    if paper_data.get("venue") and not existing.venue:
                        existing.venue = paper_data["venue"]
                        changed = True
                    if paper_data.get("year") and not existing.year:
                        existing.year = paper_data["year"]
                        changed = True
                    if paper_data.get("abstract") and not existing.abstract:
                        existing.abstract = paper_data["abstract"]
                        changed = True
                    if changed:
                        self.sqlite_db.update(existing)
                    status.success += 1
            except Exception as e:
                status.failed += 1
                status.errors.append(str(e))
            status.processed += 1
            if progress_callback:
                progress_callback(status)
        return status

    def update_tags(
        self,
        paper_id: int,
        regenerate: bool = False,
        custom_categories: Optional[list[str]] = None,
    ) -> Optional[Paper]:
        """
        更新論文標籤

        Args:
            paper_id: 論文 ID
            regenerate: 是否重新生成標籤
            custom_categories: 自定義標籤類別

        Returns:
            更新後的 Paper 或 None
        """
        paper = self.sqlite_db.get_by_id(paper_id)
        if not paper:
            return None

        if regenerate and paper.abstract:
            if self.auto_tagger is None:
                self.auto_tagger = AutoTagger(custom_categories=custom_categories)

            new_tags = self.auto_tagger.tag_paper(
                paper, custom_categories=custom_categories
            )
            paper.tags = new_tags

            self.sqlite_db.update(paper)

            # 更新向量資料庫的 metadata
            self.vector_db.add(
                paper_id=paper_id,
                abstract=paper.abstract,
                metadata={"title": paper.title, "tags": ",".join(paper.tags)},
            )

        return paper

    def delete_paper(self, paper_id: int) -> bool:
        """
        刪除論文

        Args:
            paper_id: 論文 ID

        Returns:
            是否刪除成功
        """
        # 從 SQLite 刪除
        success = self.sqlite_db.delete(paper_id)

        # 從向量資料庫刪除
        if success:
            self.vector_db.delete(paper_id)

        return success

    def export_to_xlsx(
        self,
        output_path: str | Path,
        papers: Optional[list[Paper]] = None,
    ) -> None:
        """
        匯出論文到 XLSX

        Args:
            output_path: 輸出檔案路徑
            papers: 要匯出的論文清單 (None 則匯出全部)
        """
        from openpyxl import Workbook

        if papers is None:
            papers = self.sqlite_db.get_all(limit=10000)

        wb = Workbook()
        ws = wb.active
        ws.title = "Papers"

        # 表頭
        headers = ["ID", "Title", "DOI", "Abstract", "Tags", "Source", "Created At"]
        ws.append(headers)

        # 資料
        for paper in papers:
            ws.append([
                paper.id,
                paper.title,
                paper.doi,
                paper.abstract,
                ", ".join(paper.tags),
                paper.source,
                paper.created_at.isoformat() if paper.created_at else "",
            ])

        wb.save(output_path)

    def get_statistics(self) -> dict:
        """
        取得系統統計資訊

        Returns:
            統計資訊字典
        """
        total_papers = self.sqlite_db.count()
        total_vectors = self.vector_db.count()
        all_tags = self.sqlite_db.get_all_tags()

        # 計算有摘要的論文數
        papers = self.sqlite_db.get_all(limit=total_papers)
        with_abstract = sum(1 for p in papers if p.abstract)
        with_tags = sum(1 for p in papers if p.tags)

        return {
            "total_papers": total_papers,
            "with_abstract": with_abstract,
            "with_tags": with_tags,
            "total_vectors": total_vectors,
            "unique_tags": len(all_tags),
            "tags": all_tags[:20],  # 前 20 個標籤
        }
