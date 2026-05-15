# SmartPaper-Tagging

智能學術論文管理系統 — 從 Excel 匯入到 AI 問答，一站式管理你的文獻庫。

## 功能總覽

| 功能 | 說明 |
|---|---|
| **Excel / DOI / arXiv 匯入** | 批次匯入或一鍵貼入 DOI / arXiv ID |
| **AI 自動標籤** | Gemini 分析摘要，生成結構化標籤 |
| **PDF 全文解析** | 章節感知分割（Methodology > Results 優先） |
| **混合語意搜尋** | ChromaDB 向量 + BM25 關鍵字，CrossEncoder 重排 |
| **RAG 問答** | 多輪對話，對話記憶自動萃取，引用來源標注 |
| **跨論文比較** | 同時比較 2–6 篇論文的方法、結果、研究缺口 |
| **寫作引用導引** | 輸入大綱段落，推薦應引哪些論文及位置 |
| **知識圖譜** | 論文概念關係視覺化 |
| **文獻分析** | 自動生成文獻回顧比較表 |
| **標籤管理** | 重命名、合併、刪除標籤 |
| **APA / MLA 引用格式** | 一鍵複製引用格式 |
| **分類系統** | 語意 / 兩階段 RAG / LLM 三種分類方法 |

## 快速開始

### Windows

```bat
# 1. 安裝（一次性，自動下載 uv、建立虛擬環境、安裝依賴）
install.bat

# 2. 每次啟動（自動開設定精靈補填 API Key）
launch.bat
```

### Mac / Linux

```bash
chmod +x install.sh launch.sh
./install.sh   # 一次性安裝
./launch.sh    # 每次啟動
```

### Docker（Web 模式）

```bash
# 複製範例設定
cp .env.example .env
# 填入 GEMINI_API_KEY（或用環境變數傳入）

docker compose up -d
# 開啟 http://localhost:8550
```

## 手動安裝

```bash
# 建立虛擬環境
python -m venv .venv
source .venv/bin/activate      # Linux/Mac
# 或 .venv\Scripts\activate    # Windows

# 安裝依賴
pip install -r requirements.txt

# 設定 API Key
cp .env.example .env
# 編輯 .env 填入 GEMINI_API_KEY

# 啟動圖形介面
python main.py ui
```

## 環境設定

```env
# .env
GEMINI_API_KEY=你的 Gemini API Key   # 必填
CROSSREF_EMAIL=your@email.com        # 選填，加快 Crossref 速率
```

取得 Gemini API Key：[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

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

## 系統架構

```
smartpaper/
├── api/                    # 外部 API
│   ├── crossref.py         # Crossref — DOI / 摘要
│   ├── gemini.py           # Gemini — 標籤生成、RAG
│   ├── arxiv.py            # arXiv 快速匯入
│   └── semantic_scholar.py
├── database/               # 資料庫層
│   ├── sqlite_db.py        # SQLite — 論文 metadata
│   ├── vector_db.py        # ChromaDB — 向量搜尋
│   └── chunk_store.py      # PDF 全文 chunk 儲存
├── processing/             # 資料處理
│   ├── pdf_parser.py       # 章節感知 PDF 解析（importance weight）
│   ├── cleaner.py
│   └── tagger.py
├── services/               # 業務邏輯
│   ├── pipeline.py         # 主處理流程
│   ├── search.py           # 混合搜尋（向量 + BM25）
│   ├── reranker.py         # CrossEncoder 重排 + 章節加權
│   ├── qa_service.py       # RAG 問答（多輪對話）
│   ├── qa_skill.py         # 對話記憶萃取（Transformer）
│   ├── conversation_memory.py  # 時間衰減記憶系統
│   ├── paper_compare.py    # 跨論文比較
│   ├── writing_guide.py    # 寫作引用導引
│   ├── classifier.py       # 論文分類（三種方法）
│   ├── literature_analyzer.py  # 文獻回顧分析
│   ├── knowledge_graph.py  # 知識圖譜
│   ├── quick_import.py     # DOI / arXiv 快速匯入
│   └── ...
└── ui/                     # Flet 桌面介面
    ├── app.py              # 主應用（含模型預熱）
    └── views/
        ├── home_view.py
        ├── papers_view.py
        ├── search_view.py
        ├── classify_view.py
        ├── writing_guide_view.py
        ├── graph_view.py
        ├── literature_view.py
        └── qa_view.py
```

## 核心技術

- **語言**: Python 3.11
- **UI**: [Flet](https://flet.dev)（跨平台桌面 / Web）
- **LLM**: Google Gemini（`google-genai`）
- **向量搜尋**: ChromaDB + `allenai-specter` embeddings
- **關鍵字搜尋**: BM25（`rank-bm25`）
- **重排**: CrossEncoder（`cross-encoder/ms-marco-MiniLM-L-6-v2`）
- **對話記憶**: `paraphrase-multilingual-MiniLM-L12-v2`（中英文）
- **PDF 解析**: pdfplumber
- **資料庫**: SQLite

## License

MIT
