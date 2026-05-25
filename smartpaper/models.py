"""
資料模型定義
使用 Pydantic 進行資料驗證
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Paper(BaseModel):
    """論文資料模型"""

    id: Optional[int] = Field(default=None, description="資料庫 ID")
    title: str = Field(..., description="論文標題")
    abstract: Optional[str] = Field(default=None, description="論文摘要")
    doi: Optional[str] = Field(default=None, description="DOI 識別碼")
    tags: list[str] = Field(default_factory=list, description="分類標籤")
    source: Optional[str] = Field(default=None, description="資料來源 (crossref, arxiv, manual)")
    authors: list[str] = Field(default_factory=list, description="作者清單")
    venue: Optional[str] = Field(default=None, description="期刊/會議名稱")
    year: Optional[int] = Field(default=None, description="發表年份")
    citation_count: Optional[int] = Field(default=None, description="被引用次數（Semantic Scholar）")
    created_at: datetime = Field(default_factory=datetime.now, description="建立時間")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新時間")
    # 個人化欄位
    read_status: str = Field(default="unread", description="閱讀狀態：unread / reading / read")
    starred: bool = Field(default=False, description="是否加星號")
    personal_note: str = Field(default="", description="個人筆記")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SearchResult(BaseModel):
    """搜尋結果模型"""

    paper: Paper
    score: float = Field(..., description="相似度分數 (0-1)")


class CrossrefResponse(BaseModel):
    """Crossref API 回應模型"""

    title: str
    doi: Optional[str] = None
    abstract: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    published_date: Optional[str] = None
    journal: Optional[str] = None


class TaggingResult(BaseModel):
    """AI 標籤結果模型"""

    tags: list[str] = Field(..., description="生成的標籤清單")
    confidence: Optional[float] = Field(default=None, description="信心度 (如果 LLM 提供)")


class ProcessingStatus(BaseModel):
    """處理狀態模型"""

    total: int = Field(..., description="總數")
    processed: int = Field(default=0, description="已處理數量")
    success: int = Field(default=0, description="成功數量")
    failed: int = Field(default=0, description="失敗數量")
    errors: list[str] = Field(default_factory=list, description="錯誤訊息清單")

    @property
    def progress(self) -> float:
        """計算進度百分比"""
        return (self.processed / self.total * 100) if self.total > 0 else 0
