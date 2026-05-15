"""
Google Gemini API 模組
使用 LLM 自動生成論文標籤
"""

import json
import re
from typing import Optional, TYPE_CHECKING
from google import genai

from ..config import GEMINI_API_KEY, GEMINI_MODEL, DEFAULT_TAG_CATEGORIES
from ..models import TaggingResult

if TYPE_CHECKING:
    from ..skills import SkillConfig


class GeminiTagger:
    """Gemini LLM 標籤生成類"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model or GEMINI_MODEL

        if not self.api_key:
            raise ValueError(
                "Gemini API Key 未設定。請在 .env 檔案中設定 GEMINI_API_KEY。"
            )

        self.client = genai.Client(api_key=self.api_key)

    def generate_tags(
        self,
        abstract: str,
        title: Optional[str] = None,
        custom_categories: Optional[list[str]] = None,
        num_tags: int = 5,
        skill: Optional["SkillConfig"] = None,
    ) -> TaggingResult:
        """
        根據摘要生成標籤

        Args:
            abstract: 論文摘要
            title: 論文標題 (可選，提供更多上下文)
            custom_categories: 自定義標籤類別 (可選)
            num_tags: 要生成的標籤數量
            skill: 專家角色設定（可選）

        Returns:
            TaggingResult 包含標籤清單
        """
        if not abstract or not abstract.strip():
            return TaggingResult(tags=[])

        # 決定標籤類別來源：skill > custom_categories > 預設
        if skill is not None:
            categories = skill.tag_categories
        else:
            categories = custom_categories or DEFAULT_TAG_CATEGORIES

        category_hint = ""
        if categories:
            category_hint = f"\n可參考以下標籤類別（但不限於此）：{', '.join(categories)}"

        title_context = ""
        if title:
            title_context = f"\n論文標題：{title}"

        # 若有 skill，使用其 system_prompt 作為角色前綴
        role_prefix = skill.system_prompt + "\n\n" if skill is not None else ""

        prompt = f"""{role_prefix}請根據以下論文摘要，生成 {num_tags} 個最相關的分類標籤。
{title_context}
論文摘要：{abstract}
{category_hint}

要求：
1. 標籤應簡潔明瞭，1-3 個詞
2. 標籤應反映論文的主要研究領域、方法或應用
3. 優先使用英文標籤
4. 請以 JSON 格式回傳

回傳格式：
{{"tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]}}

請只回傳 JSON，不要有其他文字。"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            response_text = response.text.strip()

            # 嘗試解析 JSON
            tags = self._parse_tags_response(response_text)

            return TaggingResult(tags=tags[:num_tags])

        except Exception as e:
            print(f"Gemini API 請求失敗: {e}")
            return TaggingResult(tags=[])

    def _parse_tags_response(self, response_text: str) -> list[str]:
        """
        解析 LLM 回應中的標籤

        Args:
            response_text: LLM 回應文字

        Returns:
            標籤清單
        """
        # 嘗試直接解析 JSON
        try:
            # 移除可能的 markdown 程式碼區塊
            clean_text = response_text
            if "```json" in clean_text:
                clean_text = clean_text.split("```json")[1].split("```")[0]
            elif "```" in clean_text:
                clean_text = clean_text.split("```")[1].split("```")[0]

            clean_text = clean_text.strip()
            data = json.loads(clean_text)

            if isinstance(data, dict) and "tags" in data:
                return data["tags"]
            elif isinstance(data, list):
                return data

        except json.JSONDecodeError:
            pass

        # 如果 JSON 解析失敗，嘗試用正則表達式提取
        # 匹配 ["tag1", "tag2", ...] 格式
        pattern = r'\[([^\]]+)\]'
        match = re.search(pattern, response_text)
        if match:
            tags_str = match.group(1)
            # 提取引號內的文字
            tags = re.findall(r'"([^"]+)"', tags_str)
            if tags:
                return tags

        # 最後嘗試：按逗號或換行分割
        lines = response_text.replace(",", "\n").split("\n")
        tags = []
        for line in lines:
            line = line.strip().strip('"').strip("'").strip("-").strip()
            if line and len(line) < 50:  # 排除太長的行
                tags.append(line)

        return tags[:10]  # 最多回傳 10 個

    def batch_generate_tags(
        self,
        papers: list[dict],
        custom_categories: Optional[list[str]] = None,
    ) -> list[TaggingResult]:
        """
        批次生成標籤

        Args:
            papers: 論文清單，每個元素應包含 'abstract' 和可選的 'title'
            custom_categories: 自定義標籤類別

        Returns:
            TaggingResult 清單
        """
        results = []

        for paper in papers:
            abstract = paper.get("abstract", "")
            title = paper.get("title")

            result = self.generate_tags(
                abstract=abstract,
                title=title,
                custom_categories=custom_categories,
            )
            results.append(result)

        return results
