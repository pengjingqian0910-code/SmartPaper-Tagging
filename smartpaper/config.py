"""
配置管理模組
載入環境變數並提供全域配置
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 載入 .env 檔案
load_dotenv()

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent

# 資料目錄
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite 資料庫路徑
SQLITE_DB_PATH = DATA_DIR / "papers.db"

# ChromaDB 配置
CHROMA_PERSIST_DIR = DATA_DIR / "chroma"
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "papers_specter")

# 向量嵌入模型（切換模型需重新建立 collection）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "allenai/specter")

# Gemini API 配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Crossref API 配置
CROSSREF_API_URL = "https://api.crossref.org/works"
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL")  # 提供郵箱可提升速率限制

# 預設標籤類別 (可選)
DEFAULT_TAG_CATEGORIES = [
    "Machine Learning",
    "Deep Learning",
    "Natural Language Processing",
    "Computer Vision",
    "Data Mining",
    "Healthcare",
    "Finance",
    "Education",
    "Security",
    "IoT",
]


def validate_config() -> list[str]:
    """
    驗證必要配置是否已設定

    Returns:
        缺失配置的清單
    """
    errors = []

    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY 未設定。請在 .env 檔案中設定你的 Gemini API Key。")

    return errors
