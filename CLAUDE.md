# SmartPaper-Tagging 專案筆記

> 此檔案供 Claude Code 讀取，記錄專案架構與開發進度。

## 專案概述

智能學術論文標籤管理系統，用於：
- 從 Excel 匯入論文標題
- 自動取得論文元資料（Crossref API）
- AI 自動生成標籤（Google Gemini）
- 語意搜尋（ChromaDB 向量資料庫）
- 論文分類與 RAG 總結

## 技術架構

```
smartpaper/
├── api/                    # 外部 API
│   ├── crossref.py         # Crossref API - 取得論文 DOI、摘要
│   └── gemini.py           # Gemini API - 自動生成標籤
├── database/               # 資料庫層
│   ├── sqlite_db.py        # SQLite - 論文元資料存儲
│   └── vector_db.py        # ChromaDB - 向量搜尋
├── processing/             # 資料處理
│   ├── cleaner.py          # HTML 清理、文字正規化
│   └── tagger.py           # 標籤邏輯
├── services/               # 業務邏輯
│   ├── ingestion.py        # Excel 讀取
│   ├── pipeline.py         # 主處理流程
│   ├── search.py           # 搜尋服務
│   └── classifier.py       # 論文分類服務 (新增)
└── ui/                     # Flet 桌面介面
    ├── app.py              # 主應用程式
    └── views/
        ├── home_view.py    # 首頁 - 檔案上傳
        ├── papers_view.py  # 論文管理
        ├── search_view.py  # 搜尋介面
        └── classify_view.py # 分類介面 (新增)
```

## 資料庫

### SQLite (`data/papers.db`)
- 自動初始化，無需手動設定
- 表格：`papers` (id, title, abstract, doi, tags, source, created_at, updated_at)

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
python main.py classify <topics...>   # 論文分類 (新增)
python main.py suggest-topics         # 建議分類主題 (新增)
python main.py ui                     # 啟動圖形介面
```

## 新增功能：論文分類系統

### 功能說明
讓用戶輸入主題關鍵字（如 "Machine Learning", "Healthcare"），系統會分類論文並生成總結。

### 三種分類方法

| 方法 | 說明 | 速度 | 準確度 |
|------|------|------|--------|
| `semantic` | 直接用 ChromaDB 語意搜尋摘要 | 最快 | 普通 |
| `two_stage` | **先搜標題，再用 LLM 分析摘要** ★推薦 | 中等 | 高 |
| `llm` | 每篇論文都用 LLM 判斷 | 最慢 | 最高 |

### 兩階段 RAG 流程（two_stage）

```
1. 搜尋標題 → 用關鍵字/標籤/語意搜尋找候選論文
2. 取得摘要 → 從 SQLite 取得這些論文的摘要
3. LLM 分析 → 用 Gemini 分析摘要，判斷是否真的屬於該主題
4. 生成總結 → 用 RAG 為每個主題生成總結
```

### 相關檔案
- `smartpaper/services/classifier.py` - 分類服務
  - `classify_by_topics()` - 語意搜尋分類
  - `classify_two_stage()` - 兩階段 RAG 分類 ★
  - `classify_with_llm()` - 純 LLM 分類
  - `_check_paper_relevance()` - LLM 判斷論文相關性
  - `generate_topic_summary()` - RAG 生成總結
- `smartpaper/ui/views/classify_view.py` - 分類介面
- `main.py` - CLI 指令 `classify` 和 `suggest-topics`

### 使用方式
```bash
# CLI - 兩階段 RAG（預設，推薦）
python main.py classify "Machine Learning" "Healthcare" "NLP"

# CLI - 指定分類方法
python main.py classify "Deep Learning" -m semantic    # 快速
python main.py classify "Deep Learning" -m two_stage   # 推薦
python main.py classify "Deep Learning" -m llm         # 最精確

# CLI - 顯示論文與主題的關聯摘要
python main.py classify "共享經濟" --show-details

# CLI - 根據標籤排序
python main.py sort-tags                    # 按標籤數量排序
python main.py sort-tags -s tag_alpha       # 按標籤字母排序
python main.py sort-tags -g                 # 按標籤分組顯示
python main.py sort-tags -t "Machine Learning"  # 只顯示特定標籤

# CLI - 匯出分類報告到 Excel
python main.py export-classify "Machine Learning" "Healthcare" -o report.xlsx

# UI
python main.py ui  # 點選「分類」頁籤，選擇分類方法
```

### 功能 1：論文與主題關聯摘要

當使用兩階段分類（two_stage）時，每篇論文會生成一段說明，解釋這篇論文與該主題的關聯性。

例如，論文被分類到「共享經濟」主題時：
```
論文：Platform Business Models in the Sharing Economy
關聯摘要：這篇論文探討共享經濟平台的商業模式，分析了 Uber、Airbnb 等平台
        如何透過數位科技連結供需雙方，並討論其對傳統產業的影響。
```

### 功能 2：按標籤排序分組

可以用多種方式檢視論文的標籤分佈：
- 按標籤數量排序（找出標籤最多/最少的論文）
- 按標籤字母排序
- 按標籤分組顯示（看每個標籤下有哪些論文）

## 開發注意事項

1. **不是 RAG 問答系統**：目前 LLM 只用於標籤生成和分類總結，沒有開放式問答
2. **不是 MCP/Skills 架構**：流程是固定的，LLM 不會自己決定要呼叫哪些工具
3. **Flet 框架**：UI 用 Flet（純 Python），不是 React + Flask

## 新增功能：寫作引用導引

### 功能說明
用戶輸入論文大綱（各段落標題/描述），系統為每個段落推薦應引用哪些論文及其核心概念，並說明應放在段落哪個位置。

### 核心流程

```
1. 用戶輸入大綱段落（如「引言：背景介紹」「方法：模型架構」）
2. 對每個段落進行語意搜尋（ChromaDB）
3. CrossEncoder re-ranking 篩選最相關論文
4. LLM（Gemini）一次分析所有候選，返回：
   - 是否引用
   - 引用時機（30字）
   - 引用概念（25字）
   - 段落位置（開頭/中間/結尾）
5. 可匯出 Markdown 格式
```

### 相關檔案
- `smartpaper/services/writing_guide.py` - 核心服務
  - `WritingGuideService` - 主服務類
  - `generate_section_guide()` - 單段落分析
  - `generate_outline_guide()` - 整份大綱分析
  - `export_guide_to_markdown()` - 匯出 Markdown
- `smartpaper/ui/views/writing_guide_view.py` - UI（第5個 tab）
- `main.py` - CLI 指令 `write-guide`

### 使用方式
```bash
# CLI
python main.py write-guide '引言：深度學習在醫療影像的應用背景' '相關工作：現有方法與局限' '方法：提出的模型架構'

# CLI - 指定候選論文數量並匯出
python main.py write-guide '引言' '方法' '實驗' -n 12 -o guide.md

# UI
python main.py ui  # 點選「寫作導引」tab
```

### 輸出格式範例
```
段落：引言：深度學習在醫療影像的應用背景
寫作建議：應涵蓋深度學習的發展脈絡、醫療影像的挑戰...

→ 論文：Attention U-Net: Learning Where to Look...
  引用時機：說明 U-Net 變體如何改進分割性能
  引用概念：Attention gate 機制用於聚焦關鍵區域
  段落位置：中間論述
```

## 待辦 / 可擴展方向

- [ ] 加入 RAG 問答功能（讓用戶用自然語言問問題）
- [ ] 加入 MCP/Skills（讓 LLM 自己決定要執行哪些操作）
- [ ] 改用 React + Flask 架構（如果需要 Web 版本）
- [ ] 批次匯入多個 Excel 檔案
- [ ] 論文推薦功能
