"""
開發用熱重載啟動器
用法：python dev.py
偵測到 .py 檔案變更時自動重啟 UI
按 Ctrl+C 停止
"""

import subprocess
import sys
import time
import os
from pathlib import Path

WATCH_DIR = Path(__file__).parent / "smartpaper"
POLL_INTERVAL = 1.5  # 秒


def get_mtimes(watch_dir: Path) -> dict[str, float]:
    mtimes = {}
    for f in watch_dir.rglob("*.py"):
        try:
            mtimes[str(f)] = f.stat().st_mtime
        except OSError:
            pass
    return mtimes


def start_app() -> subprocess.Popen:
    print("\n🚀 啟動 UI...", flush=True)
    return subprocess.Popen(
        [sys.executable, "main.py", "ui"],
        cwd=Path(__file__).parent,
    )


def main():
    print("👀 監控 smartpaper/ 資料夾，檔案變更時自動重啟")
    print("   按 Ctrl+C 停止\n")

    proc = start_app()
    mtimes = get_mtimes(WATCH_DIR)

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            # 檢查是否有 .py 檔案變更
            new_mtimes = get_mtimes(WATCH_DIR)
            changed = [
                f for f, t in new_mtimes.items()
                if t != mtimes.get(f, 0)
            ]
            new_files = [f for f in new_mtimes if f not in mtimes]
            changed += new_files

            if changed:
                rel = [Path(f).relative_to(Path(__file__).parent) for f in changed]
                print(f"\n📝 偵測到變更：{', '.join(str(r) for r in rel)}")
                mtimes = new_mtimes

                # 殺掉舊程序
                if proc.poll() is None:
                    print("🔄 重啟中...", flush=True)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()

                proc = start_app()

            elif proc.poll() is not None:
                # 程序意外結束，自動重啟
                print(f"\n⚠️  程序結束（exit={proc.returncode}），3 秒後重啟...")
                time.sleep(3)
                proc = start_app()
                mtimes = get_mtimes(WATCH_DIR)

    except KeyboardInterrupt:
        print("\n\n🛑 停止")
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
