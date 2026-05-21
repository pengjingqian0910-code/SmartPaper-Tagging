"""
SmartPaper 安裝 + 啟動入口
- 第一次執行：建立虛擬環境、安裝套件、設定 Gemini API Key
- 之後執行：直接用 venv 啟動程式
桌面捷徑應指向此檔案（使用系統 Python）
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

PROJECT_DIR  = Path(__file__).resolve().parent
VENV_DIR     = PROJECT_DIR / ".venv"
VENV_PYTHON  = VENV_DIR / "Scripts" / "python.exe"
MARKER_FILE  = PROJECT_DIR / ".setup_done"
ENV_FILE     = PROJECT_DIR / ".env"
REQ_FILE     = PROJECT_DIR / "requirements.txt"

# 品牌色
BG       = "#1E1B4B"
PANEL    = "#2D2A6E"
ACCENT   = "#7C3AED"
ACCENT2  = "#FBBF24"
WHITE    = "#F1F5F9"
SUBTEXT  = "#A5B4FC"
SUCCESS  = "#34D399"
ERROR    = "#F87171"


# ─── 工具函式 ─────────────────────────────────────────────────────────────────

def is_setup_done() -> bool:
    return MARKER_FILE.exists() and VENV_PYTHON.exists()


def launch_app():
    """用 venv Python 啟動 launcher.py（帶啟動動畫）。"""
    subprocess.Popen(
        [str(VENV_PYTHON), str(PROJECT_DIR / "launcher.py")],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_env_key() -> str:
    """從 .env 讀取現有的 GEMINI_API_KEY（若有）。"""
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip()
    return ""


def write_env_key(key: str):
    """寫入或更新 .env 的 GEMINI_API_KEY。"""
    template = (
        "# SmartPaper 環境變數\n"
        f"GEMINI_API_KEY={key}\n"
        "# CROSSREF_EMAIL=your@email.com\n"
    )
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        new_lines = []
        replaced = False
        for line in lines:
            if line.strip().startswith("GEMINI_API_KEY=") and not line.startswith("#"):
                new_lines.append(f"GEMINI_API_KEY={key}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"GEMINI_API_KEY={key}")
        ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        ENV_FILE.write_text(template, encoding="utf-8")


# ─── 設定精靈 UI ──────────────────────────────────────────────────────────────

class SetupWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SmartPaper — 初次設定")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self._center(520, 480)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._log_queue: queue.Queue = queue.Queue()
        self._setup_ok  = False
        self._cancelled = False

        self._build_ui()

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build_ui(self):
        # ── 頂部標題區 ──────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=ACCENT, height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="SmartPaper  初次設定",
                 font=("Helvetica", 16, "bold"),
                 bg=ACCENT, fg=WHITE).place(relx=0.5, rely=0.5, anchor="center")

        body = tk.Frame(self.root, bg=BG, padx=28, pady=18)
        body.pack(fill="both", expand=True)

        # ── 步驟指示 ────────────────────────────────────────────────────
        steps_frame = tk.Frame(body, bg=BG)
        steps_frame.pack(fill="x", pady=(0, 12))
        self._step_labels = []
        for i, txt in enumerate(["① 建立虛擬環境", "② 安裝套件", "③ 設定 API Key"]):
            lbl = tk.Label(steps_frame, text=txt, font=("Helvetica", 10),
                           bg=BG, fg=SUBTEXT)
            lbl.pack(side="left", expand=True)
            self._step_labels.append(lbl)

        # ── 進度條 ──────────────────────────────────────────────────────
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Purple.Horizontal.TProgressbar",
                         troughcolor=PANEL, background=ACCENT,
                         bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        self._progress = ttk.Progressbar(
            body, style="Purple.Horizontal.TProgressbar",
            orient="horizontal", length=460, mode="indeterminate",
        )
        self._progress.pack(fill="x", pady=(0, 8))

        # ── 安裝 log ────────────────────────────────────────────────────
        log_frame = tk.Frame(body, bg=PANEL, bd=0)
        log_frame.pack(fill="both", expand=True, pady=(0, 12))
        self._log = tk.Text(log_frame, height=8, bg=PANEL, fg=SUBTEXT,
                            font=("Courier New", 9), relief="flat",
                            state="disabled", wrap="word",
                            insertbackground=WHITE)
        scroll = tk.Scrollbar(log_frame, command=self._log.yview,
                              bg=PANEL, troughcolor=PANEL)
        self._log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        # ── Gemini API Key 輸入 ─────────────────────────────────────────
        key_frame = tk.Frame(body, bg=BG)
        key_frame.pack(fill="x", pady=(0, 14))
        tk.Label(key_frame, text="Gemini API Key",
                 font=("Helvetica", 11, "bold"),
                 bg=BG, fg=WHITE).pack(anchor="w")
        tk.Label(key_frame,
                 text="請前往 https://makersuite.google.com/app/apikey 取得免費金鑰",
                 font=("Helvetica", 9), bg=BG, fg=SUBTEXT).pack(anchor="w")
        self._key_var = tk.StringVar(value=read_env_key())
        key_entry = tk.Entry(key_frame, textvariable=self._key_var,
                             font=("Courier New", 10),
                             bg=PANEL, fg=ACCENT2, insertbackground=WHITE,
                             relief="flat", bd=6, show="*")
        key_entry.pack(fill="x", pady=4)
        show_var = tk.BooleanVar(value=False)
        def _toggle_show():
            key_entry.config(show="" if show_var.get() else "*")
        tk.Checkbutton(key_frame, text="顯示金鑰",
                       variable=show_var, command=_toggle_show,
                       bg=BG, fg=SUBTEXT, activebackground=BG,
                       selectcolor=PANEL, font=("Helvetica", 9)).pack(anchor="w")

        # ── 底部按鈕 ────────────────────────────────────────────────────
        btn_frame = tk.Frame(body, bg=BG)
        btn_frame.pack(fill="x")
        self._start_btn = tk.Button(
            btn_frame, text="開始安裝並啟動",
            font=("Helvetica", 11, "bold"),
            bg=ACCENT, fg=WHITE, relief="flat", padx=20, pady=8,
            cursor="hand2", activebackground="#6D28D9", activeforeground=WHITE,
            command=self._start_setup,
        )
        self._start_btn.pack(side="right")
        self._status_lbl = tk.Label(btn_frame, text="", font=("Helvetica", 10),
                                    bg=BG, fg=SUBTEXT)
        self._status_lbl.pack(side="left")

    # ── 步驟高亮 ─────────────────────────────────────────────────────────────

    def _highlight_step(self, idx: int):
        for i, lbl in enumerate(self._step_labels):
            if i < idx:
                lbl.config(fg=SUCCESS)
            elif i == idx:
                lbl.config(fg=ACCENT2, font=("Helvetica", 10, "bold"))
            else:
                lbl.config(fg=SUBTEXT, font=("Helvetica", 10))

    # ── Log 輸出 ─────────────────────────────────────────────────────────────

    def _append_log(self, text: str, color: str = SUBTEXT):
        self._log.config(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _set_status(self, text: str, color: str = SUBTEXT):
        self._status_lbl.config(text=text, fg=color)

    # ── 主要安裝流程 ─────────────────────────────────────────────────────────

    def _start_setup(self):
        key = self._key_var.get().strip()
        if not key:
            messagebox.showerror("缺少 API Key", "請先輸入 Gemini API Key 再繼續。")
            return
        self._start_btn.config(state="disabled")
        self._progress.start(12)
        threading.Thread(target=self._run_setup, args=(key,), daemon=True).start()
        self.root.after(100, self._poll_log)

    def _run_setup(self, api_key: str):
        try:
            # Step 1 — 建立虛擬環境
            self._ui(lambda: self._highlight_step(0))
            self._ui(lambda: self._set_status("建立虛擬環境..."))
            self._log_q(">>> 建立虛擬環境 (.venv)")
            result = subprocess.run(
                [sys.executable, "-m", "venv", str(VENV_DIR)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"venv 建立失敗：{result.stderr}")
            self._log_q("    完成 ✓")

            # Step 2 — 安裝套件
            self._ui(lambda: self._highlight_step(1))
            self._ui(lambda: self._set_status("安裝套件中（可能需要 2–5 分鐘）..."))
            self._log_q(f"\n>>> pip install -r requirements.txt")
            pip = VENV_DIR / "Scripts" / "pip.exe"
            proc = subprocess.Popen(
                [str(pip), "install", "-r", str(REQ_FILE),
                 "--disable-pip-version-check"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                cwd=str(PROJECT_DIR),
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log_q(f"    {line}")
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError("套件安裝失敗，請查看上方錯誤訊息。")
            self._log_q("    安裝完成 ✓")

            # Step 3 — 寫入 API Key
            self._ui(lambda: self._highlight_step(2))
            self._ui(lambda: self._set_status("儲存設定..."))
            self._log_q(f"\n>>> 寫入 Gemini API Key 到 .env")
            write_env_key(api_key)
            self._log_q("    完成 ✓")

            # 建立完成標記
            MARKER_FILE.write_text("setup_done\n", encoding="utf-8")
            self._setup_ok = True

            self._ui(lambda: self._progress.stop())
            self._ui(lambda: self._progress.config(mode="determinate",
                                                    value=100,
                                                    maximum=100))
            self._ui(lambda: self._set_status("設定完成！即將啟動程式...", SUCCESS))
            self._ui(lambda: self._highlight_step(3))
            self._log_q("\n>>> 啟動 SmartPaper...")

            import time; time.sleep(1.2)
            launch_app()
            import time; time.sleep(0.8)
            self._ui(self.root.destroy)

        except Exception as exc:
            self._log_q(f"\n[錯誤] {exc}")
            self._ui(lambda: self._progress.stop())
            self._ui(lambda: self._set_status(f"發生錯誤，請查看上方訊息。", ERROR))
            self._ui(lambda: self._start_btn.config(state="normal"))

    def _log_q(self, text: str):
        self._log_queue.put(text)

    def _ui(self, fn):
        self.root.after(0, fn)

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        if not self._cancelled:
            self.root.after(80, self._poll_log)

    def _on_close(self):
        self._cancelled = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    if is_setup_done():
        # 後續執行：直接啟動
        launch_app()
    else:
        # 第一次：顯示安裝精靈
        SetupWizard().run()


if __name__ == "__main__":
    main()
