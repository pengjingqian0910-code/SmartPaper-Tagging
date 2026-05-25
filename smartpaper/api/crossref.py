"""
Crossref API 模組
根據論文標題查詢 DOI 和摘要
"""

import time
from typing import Optional
import requests

from ..config import CROSSREF_API_URL, CROSSREF_EMAIL
from ..models import CrossrefResponse
from ..processing.cleaner import clean_html
from ._retry import make_session, rate_limited_get


class CrossrefAPI:
    """Crossref API 查詢類"""

    def __init__(self, email: Optional[str] = None):
        self.base_url = CROSSREF_API_URL
        self.email = email or CROSSREF_EMAIL

        ua = "SmartPaper-Tagging/0.1.0 (Academic Paper Management Tool)"
        if self.email:
            ua += f" (mailto:{self.email})"
        self.session = make_session(user_agent=ua)

    def search_by_title(
        self,
        title: str,
        rows: int = 1,
        timeout: int = 30,
    ) -> Optional[CrossrefResponse]:
        """
        根據標題搜尋論文

        Args:
            title: 論文標題
            rows: 回傳結果數量
            timeout: 請求超時秒數

        Returns:
            CrossrefResponse 或 None
        """
        params = {
            "query.title": title,
            "rows": rows,
            "select": "DOI,title,abstract,author,published,container-title",
        }

        try:
            response = rate_limited_get(
                self.session, self.base_url, params,
                timeout=timeout, service_name="Crossref",
            )
            if response is None:
                return None
            response.raise_for_status()

            data = response.json()
            items = data.get("message", {}).get("items", [])

            if not items:
                return None

            # 取第一筆最相關的結果
            item = items[0]

            # 解析作者
            authors = []
            for author in item.get("author", []):
                name_parts = []
                if author.get("given"):
                    name_parts.append(author["given"])
                if author.get("family"):
                    name_parts.append(author["family"])
                if name_parts:
                    authors.append(" ".join(name_parts))

            # 解析標題 (Crossref 回傳的是 list)
            result_title = item.get("title", [title])
            if isinstance(result_title, list):
                result_title = result_title[0] if result_title else title

            # 解析摘要 (可能包含 HTML)
            abstract = item.get("abstract")
            if abstract:
                abstract = clean_html(abstract)

            # 解析發布日期
            published = item.get("published", {})
            date_parts = published.get("date-parts", [[]])[0]
            published_date = None
            if date_parts:
                published_date = "-".join(str(p) for p in date_parts)

            # 解析期刊名稱
            journal = item.get("container-title", [])
            if isinstance(journal, list):
                journal = journal[0] if journal else None

            return CrossrefResponse(
                title=result_title,
                doi=item.get("DOI"),
                abstract=abstract,
                authors=authors,
                published_date=published_date,
                journal=journal,
            )

        except requests.RequestException as e:
            print(f"Crossref API 請求失敗: {e}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            print(f"Crossref API 回應解析失敗: {e}")
            return None

    def search_batch(
        self,
        titles: list[str],
        delay: float = 0.5,
    ) -> list[tuple[str, Optional[CrossrefResponse]]]:
        """
        批次搜尋多個標題

        Args:
            titles: 標題清單
            delay: 每次請求間隔秒數 (避免速率限制)

        Returns:
            (原始標題, CrossrefResponse) 的清單
        """
        results = []

        for title in titles:
            result = self.search_by_title(title)
            results.append((title, result))

            # 延遲避免速率限制
            if delay > 0:
                time.sleep(delay)

        return results

    def get_by_doi(self, doi: str, timeout: int = 30) -> Optional[CrossrefResponse]:
        """
        根據 DOI 取得論文資訊

        Args:
            doi: DOI 識別碼
            timeout: 請求超時秒數

        Returns:
            CrossrefResponse 或 None
        """
        url = f"{self.base_url}/{doi}"

        try:
            response = rate_limited_get(
                self.session, url, {},
                timeout=timeout, service_name="Crossref",
            )
            if response is None:
                return None
            response.raise_for_status()

            data = response.json()
            item = data.get("message", {})

            if not item:
                return None

            # 解析作者
            authors = []
            for author in item.get("author", []):
                name_parts = []
                if author.get("given"):
                    name_parts.append(author["given"])
                if author.get("family"):
                    name_parts.append(author["family"])
                if name_parts:
                    authors.append(" ".join(name_parts))

            # 解析標題
            title = item.get("title", ["Unknown"])
            if isinstance(title, list):
                title = title[0] if title else "Unknown"

            # 解析摘要
            abstract = item.get("abstract")
            if abstract:
                abstract = clean_html(abstract)

            # 解析發布日期
            published = item.get("published", {})
            date_parts = published.get("date-parts", [[]])[0]
            published_date = None
            if date_parts:
                published_date = "-".join(str(p) for p in date_parts)

            # 解析期刊名稱
            journal = item.get("container-title", [])
            if isinstance(journal, list):
                journal = journal[0] if journal else None

            return CrossrefResponse(
                title=title,
                doi=doi,
                abstract=abstract,
                authors=authors,
                published_date=published_date,
                journal=journal,
            )

        except requests.RequestException as e:
            print(f"Crossref API 請求失敗: {e}")
            return None
