"""
資料清洗模組
清除 HTML 標籤、正規化文字
"""

import re
import unicodedata
from typing import Optional

from bs4 import BeautifulSoup


def clean_html(text: str) -> str:
    """
    清除 HTML 標籤

    Args:
        text: 包含 HTML 標籤的文字

    Returns:
        純文字內容
    """
    if not text:
        return ""

    # 使用 BeautifulSoup 解析並提取純文字
    soup = BeautifulSoup(text, "lxml")

    # 移除 script 和 style 標籤的內容
    for element in soup(["script", "style"]):
        element.decompose()

    # 取得純文字
    clean_text = soup.get_text(separator=" ", strip=True)

    # 移除多餘空白
    clean_text = re.sub(r"\s+", " ", clean_text).strip()

    return clean_text


def normalize_text(text: str) -> str:
    """
    正規化文字
    - Unicode 正規化
    - 移除特殊字元
    - 統一空白字元

    Args:
        text: 原始文字

    Returns:
        正規化後的文字
    """
    if not text:
        return ""

    # Unicode 正規化 (NFC 格式)
    text = unicodedata.normalize("NFC", text)

    # 移除控制字元
    text = "".join(char for char in text if unicodedata.category(char) != "Cc")

    # 統一引號
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")

    # 統一破折號
    text = text.replace("–", "-").replace("—", "-")

    # 移除多餘空白
    text = re.sub(r"\s+", " ", text).strip()

    return text


def extract_abstract_section(text: str) -> Optional[str]:
    """
    從全文中提取摘要段落
    (適用於某些 API 回傳完整文章的情況)

    Args:
        text: 完整文字

    Returns:
        摘要段落或 None
    """
    if not text:
        return None

    # 常見的摘要標記
    abstract_markers = [
        r"abstract[:\s]*",
        r"summary[:\s]*",
        r"摘要[：:\s]*",
    ]

    text_lower = text.lower()

    for marker in abstract_markers:
        match = re.search(marker, text_lower, re.IGNORECASE)
        if match:
            start = match.end()
            # 找到下一個章節標題或結束
            end_markers = [
                r"\n\s*(?:introduction|keywords|1\.|背景|關鍵詞)",
                r"\n\n",
            ]
            end = len(text)
            for end_marker in end_markers:
                end_match = re.search(end_marker, text[start:], re.IGNORECASE)
                if end_match:
                    end = start + end_match.start()
                    break

            abstract = text[start:end].strip()
            if len(abstract) > 50:  # 確保摘要有足夠內容
                return normalize_text(abstract)

    return None


def truncate_text(text: str, max_length: int = 5000) -> str:
    """
    截斷過長文字 (保留完整句子)

    Args:
        text: 原始文字
        max_length: 最大長度

    Returns:
        截斷後的文字
    """
    if not text or len(text) <= max_length:
        return text

    # 在最大長度附近找句號結尾
    truncated = text[:max_length]
    last_period = max(
        truncated.rfind("."),
        truncated.rfind("。"),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )

    if last_period > max_length * 0.8:  # 如果句號在 80% 位置之後
        return truncated[: last_period + 1]

    return truncated + "..."


def clean_paper_title(title: str) -> str:
    """
    清洗論文標題

    Args:
        title: 原始標題

    Returns:
        清洗後的標題
    """
    if not title:
        return ""

    # 移除 HTML
    title = clean_html(title)

    # 正規化
    title = normalize_text(title)

    # 移除常見的前綴/後綴
    prefixes_to_remove = [
        r"^\[.*?\]\s*",  # [PDF], [arXiv] 等
        r"^(?:re|fw|fwd):\s*",  # 郵件前綴
    ]

    for pattern in prefixes_to_remove:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE)

    return title.strip()
