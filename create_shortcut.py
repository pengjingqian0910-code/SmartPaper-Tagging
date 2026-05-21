"""
建立 SmartPaper 桌面捷徑
執行一次即可：python create_shortcut.py
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PYTHON_EXE  = Path(sys.executable)
PYTHONW_EXE = PYTHON_EXE.parent / "pythonw.exe"   # 無主控台視窗
MAIN_PY     = PROJECT_DIR / "main.py"
DESKTOP     = Path.home() / "Desktop"
SHORTCUT    = DESKTOP / "SmartPaper.lnk"
ICON_PATH   = PROJECT_DIR / "assets" / "icon.ico"


def _icon_arg() -> str:
    if ICON_PATH.exists():
        return str(ICON_PATH)
    # 使用 Python 自帶的圖示作為備用
    py_icon = PYTHON_EXE.parent / "DLLs" / "py.ico"
    if py_icon.exists():
        return str(py_icon)
    return str(PYTHON_EXE)


def create_shortcut():
    runner = str(PYTHONW_EXE) if PYTHONW_EXE.exists() else str(PYTHON_EXE)
    icon   = _icon_arg()

    ps_script = f"""
$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut('{SHORTCUT}')
$lnk.TargetPath       = '{runner}'
$lnk.Arguments        = '"{MAIN_PY}" ui'
$lnk.WorkingDirectory = '{PROJECT_DIR}'
$lnk.WindowStyle      = 1
$lnk.IconLocation     = '{icon}'
$lnk.Description      = 'SmartPaper Tagging - 智能學術論文管理'
$lnk.Save()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[FAIL] Could not create shortcut: {result.stderr.strip()}")
        sys.exit(1)

    print(f"[OK] Desktop shortcut created: {SHORTCUT}")
    print(f"     Runs: {runner} \"{MAIN_PY}\" ui")
    print(f"     CWD:  {PROJECT_DIR}")


if __name__ == "__main__":
    create_shortcut()
