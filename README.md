# SmartPaper

智能學術論文管理系統 — 從匯入、搜尋、問答，到 AI 輔助寫作，一站式管理你的文獻庫。

## 功能總覽

| 功能 | 說明 |
|---|---|
| **Excel / DOI / arXiv 匯入** | 批次匯入或一鍵貼入 DOI / arXiv ID，自動補齊元資料 |
| **AI 自動標籤** | Gemini 分析摘要，生成結構化標籤 |
| **PDF 全文解析** | 章節感知分割，Methodology / Results 優先，pymupdf4llm + pdfplumber 雙引擎 |
| **混合語意搜尋** | ChromaDB 向量 + BM25 關鍵字，CrossEncoder 重排，支援標籤 / 年份篩選 |
| **RAG 問答** | Classic RAG 與 Function Calling 兩種模式，多輪對話，APA / MLA 引用一鍵複製，對話記錄 SQLite 持久化，匯出 Markdown |
| **論文推薦** | 本地相似論文 + Semantic Scholar / arXiv 外部推薦，一鍵加入文獻庫 |
| **引用導引**（寫作前） | 三步驟：候選論文搜尋 → AI 逐篇引用分析（含英文寫作範例）→ 缺口補強（arXiv 外部論文 + 綜述段落 + 加入文獻庫） |
| **文稿潤色**（寫作後） | 草稿評估（學術語氣 / 清晰度 / 引用充足度評分）→ 學術英文改寫 → 逐句批注 → 文庫引用推薦 → 現有引用替代建議 |
| **論文管理** | 虛擬化列表（百篇無卡頓）、批次選取 / 刪除 / 重標籤、Semantic Scholar 自動補齊元資料 |
| **分類系統** | 語意 / 兩階段 RAG / LLM 三種分類方法，背景執行含進度條 |
| **知識圖譜** | 互動式圖譜（在瀏覽器開啟）、年份柱狀圖點擊篩選、標籤共現 / 演進趨勢分析、聚焦模式（N 跳鄰居） |
| **文獻分析** | 自動生成文獻回顧比較表（方法 / 資料集 / 指標） |
| **設定頁面** | 管理 Gemini API Key（含連線測試）與模型選擇（即時生效） |

## 寫作輔助功能詳解

SmartPaper 的寫作功能分為兩種使用情境：

### ✏️ 引用導引（尚未開始寫作）

```
Step 1 — 搜尋候選論文
  輸入段落描述 → 向量搜尋 + CrossEncoder 重排 → 確認候選清單

Step 2 — AI 分析引用
  LLM 逐篇判斷是否引用、引用時機、核心概念
  → 每篇生成 60–100 字英文寫作範例

Step 3 — 缺口補強
  LLM 找出缺少的概念 → arXiv 外部論文搜尋（優先）
  → 所有引用論文合併為 Synthesized Literature Review（綜述段落）
  → 外部論文可一鍵加入文獻庫
```

### 🔬 文稿潤色（已有草稿）

```
Step 1 — 評估草稿
  Academic Tone / Clarity / Citation Adequacy 三維度評分（1–10）
  + 優點清單 + 問題清單 + 預期改善項目

Step 2 — 確認後開始潤色
  • Before / After 並排對照
  • 逐句批注（原文 → 改寫 + 理由）
  • 文庫引用推薦（根據文章主題自動搜尋）
  • 現有引用替代建議（偵測草稿中的引用，推薦文庫中更合適的論文）
```

## 快速開始

> 兩種安裝路線，依使用情境選擇其一。

### 路線 A — 開發者 / 已有 Python（建議）

適合：研究者自用、有 Python 環境的使用者。

#### 🪟 Windows

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

---

#### 🍎 macOS

**環境需求（macOS）：**

```bash
# 安裝 Python 3.11（若尚未安裝）
brew install python@3.11

# 安裝 tkinter 支援（啟動畫面需要）
brew install python-tk@3.11
```

**第一次使用：**

```bash
# 下載並解壓 ZIP 後，在終端機執行：
bash launch.sh
# → 自動建立虛擬環境、安裝套件、提示輸入 API Key、啟動程式
```

**之後每次啟動：**

```bash
bash launch.sh
```

---

### 路線 B — 獨立執行檔（不需安裝 Python）

適合：分發給不熟悉 Python 的實驗室成員或使用者。

> ⚠ 打包產物約 1–3 GB，建議用 Google Drive / OneDrive 分享，不適合 email。

**打包（由開發者執行一次）：**

1. 先完成路線 A，確認 `.venv` 已建立
2. 雙擊 `build_windows.bat`（約 5–10 分鐘）
3. 產出 `dist\SmartPaper\` 資料夾，壓縮後分享給使用者

**使用者收到 ZIP 後：**

```
1. 解壓 dist\SmartPaper\ 資料夾到任意位置
2. 在資料夾內建立 .env 檔案（可複製 .env.example），填入：
       GEMINI_API_KEY=你的金鑰
3. 雙擊 SmartPaper.exe
   → 第一次啟動會自動下載 ML 模型（約 500 MB，需要網路）
   → 之後每次雙擊直接開啟
```

取得免費 Gemini API Key：[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

---

## 環境需求

| | Windows | macOS |
|---|---|---|
| Python | 3.11+（[python.org](https://www.python.org/downloads/)） | 3.11+（`brew install python@3.11`） |
| tkinter | 內建 | `brew install python-tk@3.11` |
| Gemini API Key | 免費取得：[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) | 同左 |

API Key 可在程式內「設定」頁面隨時更換，並可即時測試連線。

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
└── smartpaper/
    ├── config.py            # 全域設定（API Key、模型選擇）
    ├── models.py            # 資料模型（Paper、TaggingResult…）
    ├── api/
    │   ├── gemini.py        # Gemini LLM（標籤、問答、分類）
    │   ├── crossref.py      # Crossref — DOI / 摘要查詢
    │   ├── arxiv.py         # arXiv — 快速匯入 + 外部論文建議（含 rate limit 處理）
    │   └── semantic_scholar.py  # 論文推薦 + 引用關係 + 單篇查詢
    ├── database/
    │   ├── sqlite_db.py     # SQLite — 論文 metadata + 對話 Session 持久化
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
    │   ├── writing_guide.py # 引用導引（三步驟 + 英文範例 + 綜述段落）
    │   ├── text_polish.py   # 文稿潤色（評估 + 改寫 + 批注 + 引用建議）
    │   ├── classifier.py    # 論文分類（三種方法）
    │   ├── literature_analyzer.py  # 文獻回顧分析
    │   ├── knowledge_graph.py      # 知識圖譜（瀏覽器互動）
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
            ├── papers_view.py       # 論文管理（虛擬化列表 + 批次操作）
            ├── search_view.py
            ├── classify_view.py     # 分類（背景執行 + 進度條）
            ├── writing_guide_view.py  # 引用導引 + 文稿潤色（雙 Tab）
            ├── graph_view.py        # 知識圖譜（瀏覽器 + 年份互動）
            ├── literature_view.py
            ├── qa_view.py           # 問論文（Session 持久化 + Markdown 匯出）
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
| 資料庫 | SQLite（論文 metadata + 對話記錄）+ ChromaDB（向量） |
| 外部文獻 | Semantic Scholar API、arXiv API（免費，無需 Key） |

## 現況與未來方向

SmartPaper 目前是**功能完整的研究級個人工具**，適合個人研究者或小型實驗室日常使用。

**已完成的核心能力：**
- 完整的文獻管理流程（匯入 → 標籤 → 搜尋 → 問答）
- 雙路檢索架構（向量 + BM25 + 重排）在同類工具中屬於進階水準
- 寫作輔助（引用導引 + 文稿潤色）是目前市面上整合度較高的設計

**如果要繼續精進，優先順序建議：**

| 優先度 | 方向 | 說明 |
|---|---|---|
| 🔴 高 | 可靠性 | 加入測試套件；更完整的 API 錯誤處理與重試邏輯 |
| 🟡 中 | PDF 解析品質 | 對掃描版 / 複雜排版 PDF 的解析成功率仍有進步空間 |
| 🟡 中 | 安裝體驗 | 提供 Windows/macOS 單一執行檔，降低非工程師的使用門檻 |
| 🟢 低 | Web 版本 | 改用 Flask + React 架構以支援多人共用與遠端存取 |
| 🟢 低 | 更多 LLM 支援 | 擴充至 OpenAI / Claude / 本地 Ollama |

## License

MIT
