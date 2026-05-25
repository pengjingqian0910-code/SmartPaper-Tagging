@echo off
setlocal EnableDelayedExpansion
title SmartPaper — Windows Build

echo.
echo  =========================================
echo   SmartPaper  Windows Build Script
echo  =========================================
echo.

REM ── 確認虛擬環境存在 ──────────────────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo         Run setup_and_run.py first to create it.
    pause & exit /b 1
)

call .venv\Scripts\activate.bat

REM ── 安裝 build 工具 ───────────────────────────────────────────────
echo [1/4] Installing build tools...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause & exit /b 1
)

REM ── 嘗試 flet pack（建議路徑）────────────────────────────────────
echo [2/4] Trying flet pack ...
flet pack app_entry.py ^
    --name SmartPaper ^
    --add-data "smartpaper;smartpaper" ^
    --add-data ".env.example;." ^
    2>nul

if not errorlevel 1 (
    echo [3/4] flet pack succeeded.
    goto :copy_data
)

REM ── Fallback：PyInstaller 直接打包 ───────────────────────────────
echo [2/4] flet pack failed, falling back to PyInstaller...
pyinstaller ^
    --name SmartPaper ^
    --onedir ^
    --windowed ^
    --add-data "smartpaper;smartpaper" ^
    --hidden-import chromadb ^
    --hidden-import chromadb.db.impl ^
    --hidden-import chromadb.db.impl.sqlite ^
    --hidden-import chromadb.segment ^
    --hidden-import chromadb.segment.impl ^
    --hidden-import chromadb.segment.impl.manager ^
    --hidden-import chromadb.segment.impl.manager.local ^
    --hidden-import sentence_transformers ^
    --hidden-import rank_bm25 ^
    --hidden-import google.genai ^
    --hidden-import pdfplumber ^
    --hidden-import pymupdf4llm ^
    --hidden-import flet ^
    --hidden-import flet_core ^
    --collect-all chromadb ^
    --collect-all sentence_transformers ^
    --collect-all flet ^
    --noconfirm ^
    app_entry.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed. See above for details.
    pause & exit /b 1
)

:copy_data
echo [3/4] Copying data directory template...
REM Create an empty data/ folder so the app can initialize on first run
if not exist "dist\SmartPaper\data" mkdir "dist\SmartPaper\data"

REM Copy .env.example so users know where to put their API key
if exist ".env.example" copy ".env.example" "dist\SmartPaper\.env.example" >nul

echo [4/4] Build complete!
echo.
echo  Output folder : dist\SmartPaper\
echo  Executable    : dist\SmartPaper\SmartPaper.exe
echo.
echo  NOTES:
echo    - Distribute the entire dist\SmartPaper\ folder (not just the .exe)
echo    - Users must create a .env file with their GEMINI_API_KEY before first run
echo    - ML models (~500 MB) are downloaded automatically on first launch
echo    - Estimated package size: 1-3 GB depending on ML libraries
echo.
pause
