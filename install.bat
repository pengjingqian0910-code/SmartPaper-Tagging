@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title SmartPaper-Tagging 安裝程式

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║      SmartPaper-Tagging 安裝程式         ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ── 1. 確認 Python ───────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [錯誤] 找不到 Python，請先安裝 Python 3.11+
    echo        https://www.python.org/downloads/
    pause & exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [✓] Python %PY_VER% 已安裝

:: ── 2. 安裝 / 更新 uv ─────────────────────────────────────────────────
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] 正在安裝 uv 套件管理器...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    :: 重新整理 PATH（uv 安裝到 %USERPROFILE%\.local\bin）
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if !errorlevel! neq 0 (
        echo [錯誤] uv 安裝失敗，改用 pip 安裝...
        goto :use_pip
    )
)
echo [✓] uv 已就緒

:: ── 3. 建立虛擬環境（.venv）──────────────────────────────────────────
if not exist ".venv" (
    echo [*] 建立 Python 3.11 虛擬環境...
    uv venv .venv --python 3.11
    if !errorlevel! neq 0 (
        echo [警告] Python 3.11 不可用，使用系統預設版本
        uv venv .venv
    )
) else (
    echo [✓] 虛擬環境已存在
)

:: ── 4. 安裝依賴套件 ──────────────────────────────────────────────────
echo [*] 安裝依賴套件（使用 uv，速度約 pip 的 10 倍）...
uv pip install -r requirements.txt --python .venv\Scripts\python.exe
if %errorlevel% neq 0 (
    echo [錯誤] 套件安裝失敗
    pause & exit /b 1
)
echo [✓] 所有套件安裝完成

:: ── 5. 預下載 ML 模型 ───────────────────────────────────────────────
echo [*] 預先下載 ML 模型（首次需要網路，約 500MB）...
.venv\Scripts\python.exe -c "
import sys
print('  下載 CrossEncoder...', flush=True)
try:
    from sentence_transformers import CrossEncoder
    CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    print('  [✓] CrossEncoder 完成', flush=True)
except Exception as e:
    print(f'  [!] CrossEncoder 失敗: {e}', flush=True)

print('  下載對話記憶模型...', flush=True)
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    print('  [✓] 對話記憶模型完成', flush=True)
except Exception as e:
    print(f'  [!] 對話記憶模型失敗: {e}', flush=True)

print('  下載語意搜尋模型...', flush=True)
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer('allenai-specter')
    print('  [✓] 語意搜尋模型完成', flush=True)
except Exception as e:
    print(f'  [!] 語意搜尋模型失敗 (非必要): {e}', flush=True)
"

:: ── 6. 建立資料目錄 ──────────────────────────────────────────────────
if not exist "data" mkdir data
echo [✓] 資料目錄就緒

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║           安裝完成！                     ║
echo  ║                                          ║
echo  ║  執行 launch.bat 啟動 SmartPaper         ║
echo  ╚══════════════════════════════════════════╝
echo.
pause
exit /b 0

:use_pip
echo [*] 使用 pip 安裝依賴套件...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [錯誤] pip 安裝失敗
    pause & exit /b 1
)
echo [✓] pip 安裝完成
goto :after_install
