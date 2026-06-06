# SmartPaper

智能學術論文管理系統 — 從匯入、搜尋、問答，到 AI 輔助寫作，一站式管理你的文獻庫。

**版本：v1.0.0**　｜　Python 3.11 / 3.12　｜　Windows · macOS

---

## 功能總覽

| 功能 | 說明 |
|---|---|
| **多格式匯入** | Excel、DOI / arXiv 一鍵匯入、PDF 拖放、BibTeX / RIS / EndNote XML |
| **AI 自動標籤** | Gemini 分析摘要，生成結構化標籤，支援中英文 |
| **PDF 全文解析** | 章節感知分割，pymupdf4llm + pdfplumber 雙引擎，Small-to-Big chunking |
| **進階語意搜尋** | 向量 + BM25 混合，CrossEncoder 重排，查詢擴展（Gemini 生成變體），個人化排序 |
| **RAG 問答** | Classic RAG 與 Function Calling 兩種模式，多輪對話，APA / MLA 引用一鍵複製，SQLite 持久化，匯出 Markdown |
| **論文推薦** | 本地相似論文 + Semantic Scholar / arXiv 外部推薦，一鍵加入文獻庫 |
| **引用導引**（寫作前） | 三步驟：候選搜尋 → AI 逐篇分析（英文寫作範例）→ 缺口補強（arXiv 外部論文 + 綜述段落） |
| **文稿潤色**（寫作後） | 草稿評分 → 學術英文改寫 → 逐句批注 → 文庫引用推薦 → 現有引用替代建議 |
| **論文管理** | 虛擬化列表（百篇無卡頓）、篩選 / 語意搜尋雙模式、批次操作、Semantic Scholar 補齊元資料 |
| **論文分類** | 語意 / 兩階段 RAG / LLM 三種方法，背景執行含進度條 |
| **知識圖譜** | 互動式圖譜，年份柱狀圖點擊篩選，標籤共現 / 演進趨勢，聚焦模式（N 跳鄰居） |
| **文獻分析** | 自動生成文獻回顧比較表（方法 / 資料集 / 指標） |
| **自動更新** | 設定頁檢查 GitHub Release，一鍵下載並自動重新安裝套件 |

---

## 寫作輔助功能詳解

### 引用導引（尚未開始寫作）

```
Step 1 — 搜尋候選論文
  輸入段落描述 → 向量搜尋 + CrossEncoder 重排 → 確認候選清單

Step 2 — AI 分析引用
  LLM 逐篇判斷是否引用、引用時機、核心概念
  → 每篇生成 60–100 字英文寫作範例

Step 3 — 缺口補強
  LLM 找出缺少的概念 → arXiv 外部論文搜尋（優先）
  → 所有引用論文合併為 Synthesized Literature Review
  → 外部論文可一鍵加入文獻庫
```

### 文稿潤色（已有草稿）

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

---

## 快速開始

### 🪟 Windows

```bash
# 下載專案後，在資料夾內執行：
python setup_and_run.py
```

首次執行會自動：建立虛擬環境 → 安裝所有套件 → 輸入 Gemini API Key → 啟動程式。

之後每次啟動，雙擊桌面捷徑（或再次執行同一指令）即可。

---

### 🍎 macOS / Linux

```bash
# 安裝 Python 3.11（若尚未安裝）
brew install python@3.11 python-tk@3.11

# 下載專案後，在終端機執行：
bash launch.sh
```

首次執行會自動建立虛擬環境、安裝套件、提示輸入 API Key，之後每次執行同一指令即可。

---

### 取得免費 Gemini API Key

前往 [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) 免費取得，貼入安裝精靈或程式內「設定」頁面即可。

---

## 系統需求

| | Windows | macOS |
|---|---|---|
| Python | 3.11 或 3.12 | 3.11 或 3.12 |
| 下載 | [python.org](https://www.python.org/downloads/) | `brew install python@3.11 python-tk@3.11` |
| 首次 ML 模型下載 | 約 500 MB，需要網路 | 同左 |
| 磁碟空間 | 約 3 GB（含模型） | 同左 |

---

## 搜尋策略說明

SmartPaper 的搜尋採用四層強化策略，在一般工具的向量搜尋之上大幅提升準確率：

| 策略 | 說明 |
|---|---|
| A — 查詢擴展 | Gemini 自動生成 2 個互補查詢變體，結果以 RRF 融合 |
| B — Small-to-Big | 小句子粒度索引（精準匹配），回傳父段落給 LLM（完整脈絡）|
| C — 標籤引用擴展 | 從前幾名結果的標籤反向找到未被覆蓋的相關論文 |
| D — 個人化排序 | 已加星號的論文 +12%、已讀的論文 +4% 分數加成 |

---

## CLI 指令

```bash
python main.py ui                              # 啟動圖形介面
python main.py process papers.xlsx            # 處理 Excel 檔案
python main.py search "deep learning" -s      # 語意搜尋
python main.py classify "NLP" "Healthcare"    # 論文分類
python main.py write-guide '引言' '方法' '實驗'   # 寫作引用導引
python main.py list                           # 列出論文
python main.py tags                           # 列出標籤
python main.py export -o out.xlsx             # 匯出
python main.py stats                          # 統計資訊
```

---

## 專案架構

```
SmartPaper-Tagging/
├── main.py                    # CLI 入口
├── setup_and_run.py           # 首次設定精靈（venv + 套件 + API Key）
├── launcher.py                # 啟動動畫
├── create_shortcut.py         # 建立 Windows 桌面捷徑
├── launch.sh                  # macOS / Linux 啟動腳本
├── build_windows.bat          # Windows 打包成 .exe
└── smartpaper/
    ├── config.py              # 全域設定（API Key、模型選擇）
    ├── models.py              # 資料模型（Paper、TaggingResult…）
    ├── api/
    │   ├── gemini.py          # Gemini LLM（標籤、問答、分類）
    │   ├── crossref.py        # Crossref — DOI / 摘要查詢
    │   ├── arxiv.py           # arXiv — 匯入 + 推薦（含 rate limit 全局退避）
    │   └── semantic_scholar.py    # 論文推薦 + 引用關係
    ├── database/
    │   ├── sqlite_db.py       # SQLite — 論文 metadata + 對話 Session
    │   ├── vector_db.py       # ChromaDB — 向量搜尋
    │   └── chunk_store.py     # PDF 全文 chunk（Small-to-Big 兩層）
    ├── processing/
    │   ├── pdf_parser.py      # PDF 解析（pymupdf4llm + pdfplumber）
    │   ├── cleaner.py         # HTML 清理、文字正規化
    │   └── tagger.py          # 標籤邏輯
    ├── services/
    │   ├── pipeline.py        # 主處理流程
    │   ├── search.py          # 混合搜尋（A+B+C+D 四策略）
    │   ├── query_expander.py  # 查詢擴展（Gemini 生成變體）
    │   ├── reranker.py        # CrossEncoder 重排
    │   ├── reference_parser.py    # BibTeX / RIS / EndNote XML 解析
    │   ├── qa_service.py      # Classic RAG 問答（串流 + 追問建議）
    │   ├── qa_service_fc.py   # Function Calling 問答
    │   ├── writing_guide.py   # 引用導引（三步驟 + 英文範例 + 綜述）
    │   ├── classifier.py      # 論文分類（三種方法）
    │   ├── literature_analyzer.py # 文獻回顧分析
    │   ├── knowledge_graph.py # 知識圖譜
    │   ├── updater.py         # GitHub Release 自動更新
    │   ├── ingestion.py       # Excel 讀取
    │   ├── pdf_ingestion.py   # PDF 全文匯入（含 Small chunk 切分）
    │   ├── pdf_import_service.py  # 從 PDF 建立新論文
    │   ├── quick_import.py    # DOI / arXiv 快速匯入
    │   └── conversation_memory.py # 時間衰減對話記憶
    └── ui/
        ├── app.py             # 主應用程式（深色側邊欄 + Splash 啟動畫面）
        ├── theme.py           # 顏色 / 字體 / 動畫常數
        └── views/
            ├── home_view.py         # 首頁（匯入 + 儀表板 + arXiv 推薦）
            ├── papers_view.py       # 論文管理（篩選 / 語意搜尋雙模式）
            ├── classify_view.py     # 論文分類
            ├── writing_guide_view.py    # 引用導引 + 文稿潤色
            ├── graph_view.py        # 知識圖譜
            ├── literature_view.py   # 文獻回顧
            ├── qa_view.py           # 問論文
            ├── timeline_view.py     # 時間線
            └── settings_view.py     # 設定（API Key + 模型 + 更新）
```

---

## 技術棧

| 類別 | 技術 |
|---|---|
| UI | [Flet](https://flet.dev) 0.82（Python 桌面框架） |
| LLM | Google Gemini（`google-genai` 1.x），可在設定頁切換模型 |
| 向量搜尋 | ChromaDB 1.x + `allenai-specter` embeddings |
| 關鍵字搜尋 | BM25（`rank-bm25`） |
| 重排 | CrossEncoder（`cross-encoder/ms-marco-MiniLM-L-6-v2`） |
| PDF 解析 | pymupdf4llm（主）+ pdfplumber（fallback） |
| 資料庫 | SQLite（論文 + 對話記錄）+ ChromaDB（向量） |
| 外部文獻 | Semantic Scholar API、arXiv API（免費，無需 Key） |

---

## 自動更新

開啟程式後進入「設定」頁面，點擊「檢查更新」。若有新版本，會顯示版本號與更新說明，確認後自動下載並於下次啟動時套用（含重新安裝套件）。

---

## 未來方向

| 優先度 | 方向 | 說明 |
|---|---|---|
| 🔴 高 | 可靠性 | 加入測試套件；更完整的 API 錯誤處理 |
| 🟡 中 | PDF 解析品質 | 掃描版 / 複雜排版 PDF 的解析成功率 |
| 🟢 低 | Web 版本 | Flask + React 架構，支援多人共用與遠端存取 |
| 🟢 低 | 更多 LLM | 擴充至 OpenAI / Claude / 本地 Ollama |

---

## License

MIT
