@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title SmartPaper-Tagging

:: ── 確認虛擬環境存在 ────────────────────────────────────────────────
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [!] 找不到虛擬環境，請先執行 install.bat
    pause & exit /b 1
)

:: ── 首次設定：.env 不存在時啟動精靈 ────────────────────────────────
if not exist ".env" (
    echo [*] 首次使用，啟動設定精靈...
    "%PYTHON%" smartpaper_setup.py
    if not exist ".env" (
        echo [錯誤] 設定未完成，請重新執行 launch.bat
        pause & exit /b 1
    )
)

:: ── 檢查 GEMINI_API_KEY 是否有值 ────────────────────────────────────
for /f "tokens=1,* delims==" %%a in (.env) do (
    if "%%a"=="GEMINI_API_KEY" set "GEMINI_KEY=%%b"
)
if "!GEMINI_KEY!"=="" (
    echo [!] .env 中未設定 GEMINI_API_KEY，啟動設定精靈...
    "%PYTHON%" smartpaper_setup.py
)

:: ── 啟動主程式 ──────────────────────────────────────────────────────
"%PYTHON%" main.py ui
