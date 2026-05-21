#!/bin/bash
# SmartPaper — macOS / Linux 啟動腳本
# 用法：bash launch.sh
#   第一次執行：自動建立虛擬環境並安裝套件
#   之後執行：直接啟動程式

set -e
cd "$(dirname "$0")"

VENV=".venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"
MARKER=".setup_done"

# ── 首次安裝 ────────────────────────────────────────────────────────────
if [ ! -f "$MARKER" ] || [ ! -f "$PYTHON" ]; then
    echo "=== SmartPaper 初次設定 ==="

    # 建立虛擬環境
    echo ">>> 建立虛擬環境 (.venv)..."
    python3 -m venv "$VENV"
    echo "    完成"

    # 安裝套件
    echo ">>> 安裝套件（可能需要 2-5 分鐘）..."
    "$PIP" install -r requirements.txt --disable-pip-version-check
    echo "    完成"

    # 提示輸入 API Key
    echo ""
    echo "請前往 https://aistudio.google.com/app/apikey 取得免費的 Gemini API Key"
    read -rp "請輸入你的 Gemini API Key: " API_KEY
    if [ -n "$API_KEY" ]; then
        if [ -f ".env" ]; then
            # 更新現有 .env
            grep -v "^GEMINI_API_KEY=" .env > .env.tmp && mv .env.tmp .env
        fi
        echo "GEMINI_API_KEY=$API_KEY" >> .env
        echo "    API Key 已儲存至 .env"
    fi

    # 套用等待中的更新（若有）
    if [ -f "_update_ready" ] && [ -f "_update.zip" ]; then
        echo ">>> 套用更新中..."
        "$PYTHON" -c "
from smartpaper.services.updater import apply_pending_update
apply_pending_update()
print('    更新完成')
"
    fi

    touch "$MARKER"
    echo ""
    echo "=== 設定完成，即將啟動 SmartPaper ==="
fi

# ── 啟動程式 ────────────────────────────────────────────────────────────
"$PYTHON" launcher.py
