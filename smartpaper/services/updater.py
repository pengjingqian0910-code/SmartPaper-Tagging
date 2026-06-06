"""
GitHub Releases 自動更新服務

流程：
1. check_for_update()  — 查詢 GitHub API，比較版本
2. download_update()   — 下載 release zip 到 _update.zip
3. apply_pending_update() — 啟動時自動套用（在 setup_and_run.py 呼叫）

保留項目（不被覆蓋）：data/, .env, .setup_done, venv/, _update.zip
"""

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

GITHUB_OWNER = "pengjingqian0910-code"
GITHUB_REPO  = "SmartPaper-Tagging"
API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE  = PROJECT_ROOT / "version.txt"
UPDATE_ZIP    = PROJECT_ROOT / "_update.zip"
UPDATE_READY  = PROJECT_ROOT / "_update_ready"

# 更新時保留這些項目（使用者資料、設定、虛擬環境）
_PRESERVE = {
    "data", ".env", ".setup_done",
    "venv", ".venv",
    "_update.zip", "_update_ready",
    ".git", ".gitignore",
    "assets",         # 自訂圖示等
}


# ── 版本讀取 ────────────────────────────────────────────────────────────


def get_local_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


# ── 檢查更新 ────────────────────────────────────────────────────────────


def check_for_update() -> Optional[dict]:
    """
    查詢 GitHub 最新 release。
    若遠端版本 > 本地版本，回傳 release 資訊 dict；否則回傳 None。
    """
    try:
        req = urllib.request.Request(
            API_URL, headers={"User-Agent": "SmartPaper-Updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        remote_tag = data.get("tag_name", "")
        remote_ver = remote_tag.lstrip("v")
        local_ver  = get_local_version()

        if _version_gt(remote_ver, local_ver):
            return {
                "version":  remote_ver,
                "tag":      remote_tag,
                "url":      data.get("zipball_url", ""),
                "notes":    data.get("body", "（無說明）"),
                "html_url": data.get("html_url", ""),
            }
    except Exception:
        pass
    return None


# ── 下載更新 ────────────────────────────────────────────────────────────


def download_update(url: str, progress_callback=None) -> bool:
    """
    下載 release zipball 至 _update.zip，並建立 _update_ready 標記。
    progress_callback(pct: float) 每個 chunk 呼叫一次（0.0–1.0）。
    成功回傳 True。
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "SmartPaper-Updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            chunk_size = 65536
            with open(UPDATE_ZIP, "wb") as f:
                while True:
                    buf = resp.read(chunk_size)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if progress_callback and total:
                        progress_callback(downloaded / total)

        UPDATE_READY.write_text("ready", encoding="utf-8")
        return True

    except Exception:
        if UPDATE_ZIP.exists():
            UPDATE_ZIP.unlink()
        return False


# ── 套用更新（啟動時呼叫）──────────────────────────────────────────────


def apply_pending_update(progress_callback=None) -> bool:
    """
    若 _update_ready + _update.zip 存在，解壓並覆蓋專案檔案，
    然後重新執行 pip install -r requirements.txt 以安裝新依賴。

    progress_callback(stage: str) 在各階段被呼叫，供 UI 顯示進度。
    成功回傳 True；失敗回傳 False（不拋出例外，讓啟動流程繼續）。
    """
    if not UPDATE_READY.exists() or not UPDATE_ZIP.exists():
        return False

    def _cb(msg: str):
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    try:
        # ── 1. 解壓並覆蓋程式碼 ──────────────────────────────────────
        _cb("解壓更新檔…")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            with zipfile.ZipFile(UPDATE_ZIP) as zf:
                zf.extractall(tmp_path)

            extracted = [p for p in tmp_path.iterdir() if p.is_dir()]
            if not extracted:
                return False
            src = extracted[0]

            for item in src.iterdir():
                if item.name in _PRESERVE:
                    continue
                dst = PROJECT_ROOT / item.name
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)

        UPDATE_ZIP.unlink(missing_ok=True)
        UPDATE_READY.unlink(missing_ok=True)

        # ── 2. 重新安裝套件（新版可能有新或升版依賴）──────────────────
        _cb("更新 Python 套件…")
        req_file = PROJECT_ROOT / "requirements.txt"
        if req_file.exists():
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file),
                 "--disable-pip-version-check"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(PROJECT_ROOT),
            )
            if result.returncode != 0:
                # 記錄錯誤但不中止，讓程式繼續以舊套件啟動
                log_path = PROJECT_ROOT / "_update_pip_error.log"
                log_path.write_text(result.stdout + result.stderr, encoding="utf-8")

        # ── 3. 重設 .setup_done（讓 setup_and_run.py 比對版本號）─────
        # 讀取新版的 SETUP_VERSION（若 setup_and_run.py 更新了版本號）
        setup_script = PROJECT_ROOT / "setup_and_run.py"
        new_setup_ver = None
        if setup_script.exists():
            for line in setup_script.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("SETUP_VERSION"):
                    new_setup_ver = line.split("=", 1)[1].strip().strip('"\'')
                    break
        marker = PROJECT_ROOT / ".setup_done"
        if new_setup_ver:
            marker.write_text(new_setup_ver, encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)   # 讓精靈重新判斷

        _cb("完成")
        return True

    except Exception:
        return False


# ── 工具 ────────────────────────────────────────────────────────────────


def _version_gt(a: str, b: str) -> bool:
    """回傳 a > b（語意版本比較）"""
    try:
        return [int(x) for x in a.split(".")] > [int(x) for x in b.split(".")]
    except Exception:
        return False
