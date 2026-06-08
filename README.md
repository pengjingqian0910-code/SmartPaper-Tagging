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

## 常見問題排查

以下依照**使用者實際操作流程**逐步列出，每個步驟出問題時對應的症狀與解法。

---

### 步驟 1｜執行 `setup_and_run.py`（或 `launch.sh`）時出錯

#### ❌ 視窗一閃即逝，什麼都沒發生
Windows 環境下，用**滑鼠右鍵 → 以系統管理員身分執行**；或改用命令提示字元執行以看到錯誤訊息：
```cmd
cd C:\你的路徑\SmartPaper-Tagging
python setup_and_run.py
```

#### ❌ `'python' is not recognized`（Windows）
Python 未加入 PATH。重新安裝 Python，安裝時務必勾選 **「Add Python to PATH」**。  
確認方式：`python --version`，應顯示 3.11.x 或 3.12.x。

#### ❌ Python 版本錯誤（顯示 2.x 或 3.9 以下）
電腦可能有多個 Python 版本。改用明確版本呼叫：
```bash
python3.11 setup_and_run.py   # macOS/Linux
py -3.11 setup_and_run.py     # Windows，需要 Python Launcher
```

#### ❌ `Permission denied`（macOS / Linux）
```bash
chmod +x launch.sh
bash launch.sh
```

---

### 步驟 2｜建立虛擬環境（venv）失敗

#### ❌ `Error: [Errno 28] No space left on device`
磁碟空間不足。SmartPaper 含 ML 模型共需約 **3 GB**。清出空間後重試。

#### ❌ `The virtual environment was not created successfully` 或 `ensurepip`
部分 Linux 系統缺少 venv 模組：
```bash
sudo apt install python3.11-venv python3.11-dev
```

#### ❌ 防毒軟體（如 Windows Defender）彈出警告或阻擋
將 SmartPaper-Tagging 資料夾加入防毒軟體「排除清單」後重試。Python 腳本建立 venv 時會觸發部分防毒規則。

---

### 步驟 3｜安裝套件（pip install）失敗

#### ❌ `Connection timeout` / `Could not fetch URL`
網路連線或 PyPI 被封鎖，改用鏡像源：
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

#### ❌ `error: Microsoft Visual C++ 14.0 or greater is required`（Windows）
前往 [visualstudio.microsoft.com/visual-cpp-build-tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 安裝「C++ 建置工具」工作負載，完成後重新執行 `setup_and_run.py`。

#### ❌ `ModuleNotFoundError: No module named '_tkinter'`（macOS）
```bash
brew install python-tk@3.11
```

#### ❌ 安裝到一半中斷，再次執行仍然卡住
刪除虛擬環境資料夾後重新建立：
```bash
rm -rf .venv        # macOS/Linux
rmdir /s /q .venv   # Windows cmd
python setup_and_run.py
```

---

### 步驟 4｜輸入 Gemini API Key

#### ❌ 不知道去哪裡取得
前往 [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) 免費申請，登入 Google 帳號後點擊「建立 API 金鑰」即可。

#### ❌ 貼入後提示「Key 無效」
- 確認複製時沒有多餘空白或換行
- 確認是 **Google AI Studio** 的 Key（不是 Google Cloud API Key）

#### ❌ 安裝精靈結束後想修改 Key
編輯專案根目錄的 `.env` 檔（用記事本或任何文字編輯器開啟）：
```
GEMINI_API_KEY=貼上你的新Key
```
或進入程式後前往「設定」頁修改。

> ⚠️ `.env` 格式注意：等號兩側**不要加空格**，Key 不要用引號包住。

---

### 步驟 5｜建立桌面捷徑後，日後點擊無反應

#### ❌ 雙擊捷徑沒反應，或提示「找不到目標」
專案資料夾被移動過，捷徑路徑失效。重新執行一次：
```bash
python setup_and_run.py
```
安裝精靈會重新建立正確路徑的捷徑。

#### ❌ Windows：捷徑閃一下就關掉
右鍵捷徑 → 屬性 → 目標，確認路徑格式正確，例如：
```
C:\...\SmartPaper-Tagging\.venv\Scripts\python.exe C:\...\SmartPaper-Tagging\main.py ui
```

---

### 步驟 6｜程式啟動，但停在載入畫面很久（首次）

**這是正常現象。** 首次啟動需從 HuggingFace 下載 ML 模型（約 500 MB）：
- `allenai-specter`（向量嵌入）
- `cross-encoder/ms-marco-MiniLM-L-6-v2`（搜尋重排）

耐心等待 5–20 分鐘（視網速而定）。下載完成後，後續啟動約 10–30 秒。

#### ❌ 超過 30 分鐘仍在載入，或出現 `ConnectionError`
`huggingface.co` 可能被封鎖（中國大陸常見）。在 `.env` 中加入：
```
HF_ENDPOINT=https://hf-mirror.com
```
存檔後重新啟動。

---

### 步驟 7｜視窗開啟後顯示異常

#### ❌ 視窗全黑或白色，沒有任何內容
Flet 渲染引擎問題，嘗試關閉硬體加速：
```bash
# Windows
set LIBGL_ALWAYS_SOFTWARE=1 && python main.py ui

# macOS / Linux
LIBGL_ALWAYS_SOFTWARE=1 python main.py ui
```

#### ❌ `Address already in use`（Port 衝突）
上次程式沒有正常關閉，本地 Port 仍被占用。**重新開機**後再試；或在工作管理員結束所有 `python` 程序。

#### ❌ macOS：「無法開啟，因為開發者身分無法驗證」
```bash
xattr -rd com.apple.quarantine /path/to/SmartPaper-Tagging
```
或前往「系統設定 → 隱私權與安全性」，點擊「仍要開啟」。

---

### 步驟 8｜程式開啟後，AI 功能沒有回應

#### ❌ 標籤生成、問答都沒有輸出
前往「設定」頁，點擊「測試連線」：
- 🟢 綠色勾 → API Key 正常，請改在 GitHub 回報問題
- 🔴 紅色叉 → API Key 有問題，重新貼入後再測試

#### ❌ 測試連線顯示 `429 Resource exhausted`
免費方案每分鐘有請求次數限制。等待 1 分鐘後再試，或至 Google AI Studio 升級方案。

#### ❌ 測試連線顯示 `Connection failed`
網路防火牆封鎖了 `generativelanguage.googleapis.com`。企業或學校環境需申請開放此網域，或使用個人熱點測試。

---

### 步驟 9｜使用功能時遇到問題

#### 搜尋沒有結果
1. 文獻庫為空 → 先至首頁匯入論文
2. 刪除 `data/bm25_cache.pkl` 重新啟動（BM25 索引重建）
3. 刪除 `data/chroma/` 資料夾重新啟動（向量庫重建）

#### ChromaDB 錯誤（SQLite 版本過舊）
```
RuntimeError: Your system has an unsupported version of sqlite3
```
常見於 Ubuntu 20.04 等舊版 Linux：
```bash
pip install pysqlite3-binary
```
然後在 `smartpaper/database/vector_db.py` 最上方加入這兩行：
```python
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
```

#### PDF 全文匯入失敗

| 症狀 | 原因 | 解決方式 |
|---|---|---|
| 「PDF 無法提取文字（共 0 字元）」 | 掃描版 PDF（純圖片） | 先用 Adobe Acrobat 或 tesseract OCR 處理後再上傳 |
| 「PDF 開啟失敗」 | 檔案有密碼保護 | 先解除密碼保護 |
| 解析結果亂碼 | 特殊字型嵌入問題 | `pip install pymupdf` 後重試，會自動啟用備用解析引擎 |
| 上傳成功但無法搜尋到全文內容 | 向量化未完成 | 在論文詳細頁點擊「重新匯入 PDF」 |

---

### 仍然無法解決？

請在 GitHub Issues 回報，並附上以下資訊，方便快速定位問題：

1. **作業系統**：Windows 11 / macOS 14.x / Ubuntu 22.04…
2. **Python 版本**：`python --version` 的輸出
3. **卡在哪個步驟**：對照上方步驟 1–9
4. **完整錯誤訊息**：請複製貼上文字，勿截圖

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
