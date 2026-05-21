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


ENV_FILE = PROJECT_ROOT / ".env"

# 可選 Gemini 模型清單（(model_id, 顯示名稱, 說明)）
GEMINI_MODEL_OPTIONS = [
    ("gemini-2.5-flash",         "Gemini 2.5 Flash（預設）",   "最快最便宜，日常問答首選"),
    ("gemini-2.5-pro",           "Gemini 2.5 Pro",              "推理更強，適合複雜分析"),
    ("gemini-2.0-flash",         "Gemini 2.0 Flash",            "上一代 Flash，穩定可靠"),
    ("gemini-1.5-flash",         "Gemini 1.5 Flash",            "舊版輕量模型"),
    ("gemini-1.5-pro",           "Gemini 1.5 Pro",              "舊版高效能模型"),
]


def _update_env(key: str, value: str):
    """在 .env 更新或新增一個 KEY=VALUE 行。"""
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_gemini_api_key(new_key: str):
    global GEMINI_API_KEY
    GEMINI_API_KEY = new_key
    _update_env("GEMINI_API_KEY", new_key)


def set_gemini_model(new_model: str):
    global GEMINI_MODEL
    GEMINI_MODEL = new_model
    _update_env("GEMINI_MODEL", new_model)


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
