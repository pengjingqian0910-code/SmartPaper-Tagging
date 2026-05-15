#!/usr/bin/env bash
set -euo pipefail

PYTHON=".venv/bin/python"

# ── 確認虛擬環境存在 ────────────────────────────────────────────────
if [ ! -f "$PYTHON" ]; then
    echo "[!] 找不到虛擬環境，請先執行 ./install.sh"
    exit 1
fi

# ── 首次設定：.env 不存在時啟動精靈 ────────────────────────────────
if [ ! -f ".env" ]; then
    echo "[*] 首次使用，啟動設定精靈..."
    "$PYTHON" smartpaper_setup.py
    if [ ! -f ".env" ]; then
        echo "[錯誤] 設定未完成，請重新執行 ./launch.sh"
        exit 1
    fi
fi

# ── 檢查 GEMINI_API_KEY 是否有值 ────────────────────────────────────
GEMINI_KEY=$(grep -E '^GEMINI_API_KEY=' .env | cut -d'=' -f2- || true)
if [ -z "$GEMINI_KEY" ]; then
    echo "[!] .env 中未設定 GEMINI_API_KEY，啟動設定精靈..."
    "$PYTHON" smartpaper_setup.py
fi

# ── 啟動主程式 ──────────────────────────────────────────────────────
exec "$PYTHON" main.py ui
