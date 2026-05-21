# SmartPaper-Tagging 專案筆記

> 此檔案供 Claude Code 讀取，記錄專案架構與開發進度。

## 專案概述

智能學術論文標籤管理系統，用於：
- 從 Excel 匯入論文標題
- 自動取得論文元資料（Crossref API）
- AI 自動生成標籤（Google Gemini）
- 語意搜尋（ChromaDB 向量資料庫）
- 論文分類與 RAG 總結
- 問論文（Classic RAG + Function Calling，含 Session SQLite 持久化）
- 寫作引用導引（三步驟，外部論文優先，生成完整學術寫作範例）

## 技術架構

```
smartpaper/
├── config.py               # 全域設定（API Key、模型選擇、_update_env）
├── models.py               # 資料模型（Paper、TaggingResult…）
├── api/
│   ├── gemini.py           # Gemini LLM（標籤、問答；model_name 動態讀 config）
│   ├── crossref.py         # Crossref — DOI / 摘要查詢
│   ├── arxiv.py            # arXiv — 快速匯入 + 外部論文建議
│   └── semantic_scholar.py # 論文推薦 + 引用關係 + get_paper_by_doi + search_papers
├── database/
│   ├── sqlite_db.py        # SQLite — 論文 metadata + chat_sessions/chat_messages 表
│   ├── vector_db.py        # ChromaDB — 向量搜尋（singleton embedding）
│   └── chunk_store.py      # PDF 全文 chunk 儲存
├── processing/
│   ├── pdf_parser.py       # PDF 解析（pymupdf4llm + pdfplumber fallback）
│   ├── cleaner.py          # HTML 清理、文字正規化
│   └── tagger.py           # 標籤邏輯
├── services/
│   ├── pipeline.py         # 主處理流程（含 Semantic Scholar 引用抓取）
│   ├── search.py           # 混合搜尋（向量 + BM25 + LRU query 快取）
│   ├── reranker.py         # CrossEncoder 重排
│   ├── qa_service.py       # Classic RAG 問答（多輪對話 + 追問建議）
│   ├── qa_service_fc.py    # Function Calling 問答（手動 FC loop）
│   ├── qa_skill.py         # 對話技能萃取
│   ├── conversation_memory.py  # 時間衰減對話記憶
│   ├── writing_guide.py    # 寫作引用導引（外部論文優先 + 完整範例段落）
│   ├── classifier.py       # 論文分類（semantic / two_stage / llm）
│   ├── literature_analyzer.py  # 文獻回顧分析
│   ├── knowledge_graph.py  # 知識圖譜
│   ├── citation.py         # 引用關係管理
│   ├── ingestion.py        # Excel 讀取
│   ├── pdf_ingestion.py    # PDF 全文匯入
│   ├── pdf_import_service.py   # 從 PDF 建立新論文
│   ├── quick_import.py     # DOI / arXiv 快速匯入
│   └── api_server.py       # 本地 API server（bookmarklet 用）
└── ui/
    ├── app.py              # 主應用程式（側邊欄導航，設定齒輪在底部）
    ├── theme.py            # 顏色 / 字體常數
    └── views/
        ├── home_view.py
        ├── papers_view.py       # 論文管理：虛擬化 ListView + 批次操作
        ├── search_view.py
        ├── classify_view.py     # 分類：背景 Thread + ProgressBar
        ├── writing_guide_view.py
        ├── graph_view.py        # 知識圖譜：WebView 內嵌 + 年份互動
        ├── literature_view.py
        ├── qa_view.py           # 問論文：Session SQLite 持久化 + Markdown 匯出
        └── settings_view.py     # API Key（含連線測試）與模型設定
```

## 資料庫

### SQLite (`data/papers.db`)
- 自動初始化，無需手動設定
- 表格：
  - `papers` (id, title, abstract, doi, tags, authors, venue, year, citation_count, source, created_at, updated_at)
  - `chat_sessions` (session_id TEXT PK, title, created_at, updated_at)
  - `chat_messages` (id, session_id FK, role, content, intent_tag, is_cached, sources, created_at)

### ChromaDB (`data/chroma/`)
- 自動初始化，無需手動設定
- 用於語意搜尋，儲存論文摘要的向量嵌入

## 環境設定

必要的 `.env` 設定：
```
GEMINI_API_KEY=你的_API_KEY    # 必要 - 用於標籤生成和 RAG 總結
CROSSREF_EMAIL=your@email.com  # 選填 - 提升 Crossref API 速率
```

## CLI 指令

```bash
python main.py process <file.xlsx>    # 處理 Excel 檔案
python main.py search <query> -s      # 語意搜尋
python main.py list                   # 列出論文
python main.py tags                   # 列出所有標籤
python main.py stats                  # 統計資訊
python main.py export -o out.xlsx     # 匯出
python main.py classify <topics...>   # 論文分類
python main.py suggest-topics         # 建議分類主題
python main.py write-guide '引言' '方法' '實驗'  # 寫作引用導引
python main.py ui                     # 啟動圖形介面
```

## 各頁面功能摘要

### P1 首頁（home_view.py）
- Excel 匯入（含進度條）、DOI/arXiv 快速匯入
- 論文統計儀表板
- arXiv 外部論文建議（依文獻庫標籤）

### P2 論文管理（papers_view.py）
- **虛擬化 ListView**：`ft.ListView(expand=True, item_extent=120)`，百篇論文無卡頓
- **批次操作**：全選 Tristate Checkbox、批次刪除、批次重標籤
- 論文詳細資料 Dialog（可展開摘要、編輯標籤、刪除、查看 PDF 狀態）
- Semantic Scholar 自動補齊元資料（作者/年份/期刊/引用數）

### P3 語意搜尋（search_view.py）
- 混合搜尋（向量 + BM25），CrossEncoder 重排
- 支援 filter by tag、filter by year

### P4 論文分類（classify_view.py）
- 三種分類方法（semantic / two_stage / llm）
- **背景 Thread 執行**，`ProgressBar` 顯示進度（0→1）

### P5 寫作引用導引（writing_guide_view.py）
三步驟流程：
1. **搜尋候選論文**：向量搜尋 + CrossEncoder 重排，使用者確認候選清單
2. **AI 分析引用**：LLM 判斷每篇是否引用、引用時機、概念、段落位置
3. **缺口補強**：
   - **外部論文優先**：arXiv 關鍵字搜尋（最直接相關），SS 推薦補充
   - **完整寫作範例**：LLM 基於外部論文摘要生成 80-150 字、3-4 句學術段落
   - 文獻庫對應論文作為次要資訊
   - 「加入文獻庫」按鈕在論文標題列內嵌

### P6 知識圖譜（graph_view.py）
- **內嵌 WebView**：生成 pyvis HTML 後直接在 App 內預覽，可選「另開瀏覽器」
- **年份柱狀圖互動**：點擊柱體/數字/年份標籤均觸發篩選，顯示該年論文清單
- 聚焦模式（N 跳鄰居圖譜）、標籤分析（共現 / 演進趨勢）、去重、匯出 BibTeX / RIS

### P7 文獻回顧（literature_view.py）
- 自動生成比較表（方法 / 資料集 / 指標）

### P8 問論文（qa_view.py）
- Classic RAG（串流）與 Function Calling 兩種模式
- 多 Session 管理（最多 5 個），標籤欄位
- **SQLite 持久化**：每筆問答自動寫入 `chat_messages`，Session 標題自動更新
- **匯出 Markdown**：點擊下載按鈕，生成完整對話記錄（含引用來源）
- 追問建議 Chip、APA / MLA 引用一鍵複製

### P9 設定（settings_view.py）
- Gemini API Key 輸入 + **連線測試**（Ping Gemini，綠色勾 / 紅色叉）
- 模型選擇（即時生效）

## 論文分類系統

### 三種分類方法

| 方法 | 說明 | 速度 | 準確度 |
|------|------|------|--------|
| `semantic` | 直接用 ChromaDB 語意搜尋摘要 | 最快 | 普通 |
| `two_stage` | **先搜標題，再用 LLM 分析摘要** ★推薦 | 中等 | 高 |
| `llm` | 每篇論文都用 LLM 判斷 | 最慢 | 最高 |

## 寫作引用導引（Step 3 設計）

```
缺口補強流程：
1. LLM 找出 3-5 個 missing concepts（概念缺口）
2. 對每個概念：
   a. arXiv 直接關鍵字搜尋（主力，摘要完整）
   b. SS 推薦補充（需有本地 DOI）
   c. 向量搜尋文獻庫對應論文
3. 將外部論文摘要送入 LLM → 生成 80-150 字完整學術段落
4. UI 展示：外部論文（含加入文獻庫）→ 寫作範例 → 文獻庫對應
```

## 開發注意事項

1. **Flet 框架**：UI 用 Flet（純 Python），不是 React + Flask
2. **虛擬化列表**：`ft.ListView(item_extent=120)` 要求 item 高度固定，expandable card 需改用 Dialog 展開
3. **Thread 安全**：`page.update()` 在背景 Thread 中直接呼叫即可，無需 `run_task`
4. **Stack 點擊區域**：Stack 中後加入的控件在上層，若不設 on_click 會吞掉點擊事件
5. **SQLite 年份型別**：`p.year` 從 DB 讀回應為 int，比較前仍建議 `int()` 強制轉換

## 待辦 / 可擴展方向

- [ ] 加入 MCP/Skills（讓 LLM 自己決定要執行哪些操作）
- [ ] 改用 React + Flask 架構（如果需要 Web 版本）
- [ ] 批次匯入多個 Excel 檔案
- [ ] home_view PDF 匯入進度條（`_pdf_progress_bar`）
- [ ] settings_view 儲存按鈕在驗證失敗後 disable
