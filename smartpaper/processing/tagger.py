"""
自動標籤模組
整合 LLM 進行智能標籤生成
"""

from typing import Optional

from ..api.gemini import GeminiTagger
from ..models import TaggingResult, Paper


class AutoTagger:
    """自動標籤生成類"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        custom_categories: Optional[list[str]] = None,
    ):
        """
        初始化自動標籤器

        Args:
            api_key: Gemini API Key (可選，預設從配置讀取)
            custom_categories: 自定義標籤類別
        """
        self.gemini = GeminiTagger(api_key=api_key)
        self.custom_categories = custom_categories

    def tag_paper(
        self,
        paper: Paper,
        num_tags: int = 5,
        custom_categories: Optional[list[str]] = None,
    ) -> list[str]:
        """
        為單篇論文生成標籤

        Args:
            paper: Paper 物件
            num_tags: 要生成的標籤數量
            custom_categories: 自定義標籤類別 (覆蓋初始化設定)

        Returns:
            標籤清單
        """
        if not paper.abstract:
            return []

        categories = custom_categories or self.custom_categories

        result = self.gemini.generate_tags(
            abstract=paper.abstract,
            title=paper.title,
            custom_categories=categories,
            num_tags=num_tags,
        )

        return result.tags

    def tag_from_abstract(
        self,
        abstract: str,
        title: Optional[str] = None,
        num_tags: int = 5,
        custom_categories: Optional[list[str]] = None,
    ) -> TaggingResult:
        """
        直接從摘要生成標籤

        Args:
            abstract: 論文摘要
            title: 論文標題 (可選)
            num_tags: 要生成的標籤數量
            custom_categories: 自定義標籤類別

        Returns:
            TaggingResult 物件
        """
        categories = custom_categories or self.custom_categories

        return self.gemini.generate_tags(
            abstract=abstract,
            title=title,
            custom_categories=categories,
            num_tags=num_tags,
        )

    def merge_tags(
        self,
        existing_tags: list[str],
        new_tags: list[str],
        max_tags: int = 10,
    ) -> list[str]:
        """
        合併現有標籤和新標籤

        Args:
            existing_tags: 現有標籤清單
            new_tags: 新標籤清單
            max_tags: 最大標籤數量

        Returns:
            合併後的標籤清單 (去重)
        """
        # 使用 dict 保持順序同時去重 (大小寫不敏感)
        seen = {}
        result = []

        for tag in existing_tags + new_tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen[tag_lower] = True
                result.append(tag)

        return result[:max_tags]

    def suggest_categories(self, abstracts: list[str]) -> list[str]:
        """
        根據一批摘要建議標籤類別
        (可用於初次設定系統時)

        Args:
            abstracts: 摘要清單

        Returns:
            建議的標籤類別
        """
        if not abstracts:
            return []

        # 取前 5 篇摘要做為樣本
        sample = abstracts[:5]
        sample_text = "\n\n".join(sample)

        prompt = f"""分析以下學術論文摘要樣本，建議 10 個適合的標籤類別。

摘要樣本：
{sample_text}

要求：
1. 類別應涵蓋這些論文的主要研究領域
2. 類別應足夠通用，能適用於相似領域的其他論文
3. 每個類別 1-3 個詞
4. 使用英文

請以 JSON 格式回傳：
{{"categories": ["Category1", "Category2", ...]}}"""

        try:
            result = self.gemini.model.generate_content(prompt)
            response_text = result.text.strip()

            # 解析回應
            import json
            import re

            # 清理 markdown
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            data = json.loads(response_text.strip())
            if isinstance(data, dict) and "categories" in data:
                return data["categories"]

        except Exception as e:
            print(f"建議類別生成失敗: {e}")

        return []
