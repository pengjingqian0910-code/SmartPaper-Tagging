# SmartPaper

智能學術論文管理系統 — 從匯入到 AI 問答，一站式管理你的文獻庫。

## 功能

| 功能 | 說明 |
|---|---|
| **Excel / DOI / arXiv 匯入** | 批次匯入或一鍵貼入 DOI / arXiv ID |
| **AI 自動標籤** | Gemini 分析摘要，生成結構化標籤 |
| **PDF 全文解析** | 章節感知分割，Methodology / Results 優先 |
| **混合語意搜尋** | ChromaDB 向量 + BM25 關鍵字，CrossEncoder 重排 |
| **RAG 問答** | Classic RAG 與 Function Calling 兩種模式，多輪對話，APA / MLA 引用一鍵複製 |
| **論文推薦** | 本地相似論文 + Semantic Scholar / arXiv 外部推薦，一鍵加入文獻庫 |
| **寫作引用導引** | 輸入大綱，推薦引用論文、段落位置與寫作範例 |
| **分類系統** | 語意 / 兩階段 RAG / LLM 三種分類方法 |
| **知識圖譜** | 論文概念關係視覺化 |
| **文獻分析** | 自動生成文獻回顧比較表 |
| **設定頁面** | 管理 Gemini API Key 與模型選擇（即時生效） |

## 快速開始（Windows）

**第一次使用：**

```bash
# 1. 建立桌面捷徑（只需執行一次）
python create_shortcut.py

# 2. 雙擊桌面的 SmartPaper 圖示
#    → 首次點擊會自動建立虛擬環境、安裝套件、設定 API Key
#    → 之後每次點擊直接開啟程式
```

**或直接從命令列啟動：**

```bash
python setup_and_run.py   # 含首次設定精靈
python main.py ui          # 直接啟動（需已安裝依賴）
```

## 環境需求

- Python 3.11+
- Gemini API Key（免費）：[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

API Key 可在程式內「設定」頁面隨時更換。

## CLI 指令

```bash
python main.py ui                            # 啟動圖形介面
python main.py process papers.xlsx           # 處理 Excel 檔案
python main.py search "deep learning" -s     # 語意搜尋
python main.py classify "NLP" "Healthcare"   # 論文分類
python main.py write-guide '引言' '方法' '實驗'  # 寫作引用導引
python main.py list                          # 列出論文
python main.py tags                          # 列出標籤
python main.py export -o out.xlsx            # 匯出
python main.py stats                         # 統計資訊
```

## 架構

```
SmartPaper-Tagging/
├── main.py                  # CLI 入口
├── setup_and_run.py         # 首次設定精靈（venv + 套件 + API Key）
├── launcher.py              # 啟動動畫
├── create_shortcut.py       # 建立 Windows 桌面捷徑
├── scripts/                 # 開發 / 工具腳本
│   ├── dev.py               # 熱重載開發啟動器
│   ├── eval_rag.py          # RAG 評估腳本
│   ├── make_icon.py         # 圖示產生器
│   └── generate_report.py  # 文件報告產生器
└── smartpaper/
    ├── config.py            # 全域設定（API Key、模型選擇）
    ├── models.py            # 資料模型（Paper、TaggingResult…）
    ├── api/
    │   ├── gemini.py        # Gemini LLM（標籤、問答、分類）
    │   ├── crossref.py      # Crossref — DOI / 摘要查詢
    │   ├── arxiv.py         # arXiv — 快速匯入 + 外部論文建議
    │   └── semantic_scholar.py  # 論文推薦 + 引用關係
    ├── database/
    │   ├── sqlite_db.py     # SQLite — 論文 metadata
    │   ├── vector_db.py     # ChromaDB — 向量搜尋
    │   └── chunk_store.py   # PDF 全文 chunk 儲存
    ├── processing/
    │   ├── pdf_parser.py    # PDF 解析（pymupdf4llm + pdfplumber fallback）
    │   ├── cleaner.py       # HTML 清理、文字正規化
    │   └── tagger.py        # 標籤邏輯
    ├── services/
    │   ├── pipeline.py      # 主處理流程（含 Semantic Scholar 引用抓取）
    │   ├── search.py        # 混合搜尋（向量 + BM25 + LRU 快取）
    │   ├── reranker.py      # CrossEncoder 重排
    │   ├── qa_service.py    # Classic RAG 問答
    │   ├── qa_service_fc.py # Function Calling 問答
    │   ├── writing_guide.py # 寫作引用導引
    │   ├── classifier.py    # 論文分類（三種方法）
    │   ├── literature_analyzer.py  # 文獻回顧分析
    │   ├── knowledge_graph.py      # 知識圖譜
    │   ├── citation.py      # 引用關係管理
    │   ├── ingestion.py     # Excel 讀取
    │   ├── pdf_ingestion.py # PDF 全文匯入
    │   ├── pdf_import_service.py   # 從 PDF 建立新論文
    │   ├── quick_import.py  # DOI / arXiv 快速匯入
    │   ├── conversation_memory.py  # 時間衰減對話記憶
    │   └── qa_skill.py      # 對話技能萃取
    └── ui/
        ├── app.py           # 主應用程式（側邊欄導航）
        ├── theme.py         # 顏色 / 字體常數
        └── views/
            ├── home_view.py
            ├── papers_view.py       # 論文管理 + 推薦相似論文
            ├── search_view.py
            ├── classify_view.py
            ├── writing_guide_view.py
            ├── graph_view.py
            ├── literature_view.py
            ├── qa_view.py           # 問論文（含 Function Calling 模式）
            └── settings_view.py     # API Key 與模型設定
```

## 技術棧

| 類別 | 技術 |
|---|---|
| UI | [Flet](https://flet.dev)（Python 桌面框架） |
| LLM | Google Gemini（`google-genai`），可在設定頁切換模型 |
| 向量搜尋 | ChromaDB + `allenai-specter` embeddings |
| 關鍵字搜尋 | BM25（`rank-bm25`） |
| 重排 | CrossEncoder（`cross-encoder/ms-marco-MiniLM-L-6-v2`） |
| PDF 解析 | pymupdf4llm（主）+ pdfplumber（fallback） |
| 資料庫 | SQLite + ChromaDB |
| 外部文獻 | Semantic Scholar API、arXiv API（免費，無需 Key） |

## License

MIT
