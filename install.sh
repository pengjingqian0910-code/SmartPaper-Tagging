#!/usr/bin/env bash
set -euo pipefail

echo ""
echo " ╔══════════════════════════════════════════╗"
echo " ║      SmartPaper-Tagging 安裝程式         ║"
echo " ╚══════════════════════════════════════════╝"
echo ""

# ── 1. 確認 Python ───────────────────────────────────────────────────
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "[錯誤] 找不到 Python，請先安裝 Python 3.11+"
    echo "       https://www.python.org/downloads/"
    exit 1
fi

PY=$(command -v python3 || command -v python)
PY_VER=$($PY --version 2>&1 | awk '{print $2}')
echo "[✓] Python $PY_VER 已安裝"

# ── 2. 安裝 / 更新 uv ─────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "[*] 正在安裝 uv 套件管理器..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if command -v uv &>/dev/null; then
    echo "[✓] uv 已就緒"
    USE_UV=1
else
    echo "[警告] uv 安裝失敗，改用 pip"
    USE_UV=0
fi

# ── 3. 建立虛擬環境（.venv）──────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "[*] 建立虛擬環境..."
    if [ "$USE_UV" = "1" ]; then
        uv venv .venv --python 3.11 2>/dev/null || uv venv .venv
    else
        $PY -m venv .venv
    fi
else
    echo "[✓] 虛擬環境已存在"
fi

# ── 4. 安裝依賴套件 ──────────────────────────────────────────────────
echo "[*] 安裝依賴套件..."
if [ "$USE_UV" = "1" ]; then
    uv pip install -r requirements.txt --python .venv/bin/python
else
    .venv/bin/pip install -r requirements.txt
fi
echo "[✓] 所有套件安裝完成"

# ── 5. 預下載 ML 模型 ───────────────────────────────────────────────
echo "[*] 預先下載 ML 模型（首次需要網路，約 500MB）..."
.venv/bin/python - <<'PYEOF'
print("  下載 CrossEncoder...", flush=True)
try:
    from sentence_transformers import CrossEncoder
    CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    print("  [✓] CrossEncoder 完成", flush=True)
except Exception as e:
    print(f"  [!] CrossEncoder 失敗: {e}", flush=True)

print("  下載對話記憶模型...", flush=True)
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    print("  [✓] 對話記憶模型完成", flush=True)
except Exception as e:
    print(f"  [!] 對話記憶模型失敗: {e}", flush=True)

print("  下載語意搜尋模型...", flush=True)
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("allenai-specter")
    print("  [✓] 語意搜尋模型完成", flush=True)
except Exception as e:
    print(f"  [!] 語意搜尋模型失敗 (非必要): {e}", flush=True)
PYEOF

# ── 6. 建立資料目錄 ──────────────────────────────────────────────────
mkdir -p data
echo "[✓] 資料目錄就緒"

# ── 7. 設定可執行權限 ────────────────────────────────────────────────
chmod +x launch.sh 2>/dev/null || true

echo ""
echo " ╔══════════════════════════════════════════╗"
echo " ║           安裝完成！                     ║"
echo " ║                                          ║"
echo " ║  執行 ./launch.sh 啟動 SmartPaper        ║"
echo " ╚══════════════════════════════════════════╝"
echo ""
