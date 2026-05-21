"""
SmartPaper 啟動器
立即顯示啟動動畫，同時在背景啟動主程式。
用法：python launcher.py  （create_shortcut.py 會自動指向此檔案）
"""

import math
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PYTHON      = Path(sys.executable)
PYTHONW     = PYTHON.parent / "pythonw.exe"
ICON_ICO    = PROJECT_DIR / "assets" / "icon.ico"

# 啟動畫面尺寸
W, H = 420, 280

# 品牌色
BG_TOP    = "#4C1D95"
BG_BOT    = "#4338CA"
ACCENT    = "#FBBF24"
WHITE     = "#FFFFFF"
SUBTEXT   = "#C4B5FD"


class SplashScreen:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)          # 無標題列
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0)       # 開始透明，淡入用
        self._center()
        if ICON_ICO.exists():
            try:
                self.root.iconbitmap(str(ICON_ICO))
            except Exception:
                pass

        self.canvas = tk.Canvas(self.root, width=W, height=H,
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        self._draw_background()
        self._draw_logo()
        self._draw_title()
        self._dot_ids = self._draw_dots()

        self._angle   = 0
        self._alpha   = 0.0
        self._done    = False
        self._fading_out = False

    # ── 佈局 ─────────────────────────────────────────────────────────────

    def _center(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - W) // 2
        y  = (sh - H) // 2
        self.root.geometry(f"{W}x{H}+{x}+{y}")

    def _draw_background(self):
        # 漸層（用多條橫線模擬）
        for i in range(H):
            t   = i / H
            r   = int(0x4C + (0x43 - 0x4C) * t)
            g   = int(0x1D + (0x38 - 0x1D) * t)
            b   = int(0x95 + (0xCA - 0x95) * t)
            col = f"#{r:02x}{g:02x}{b:02x}"
            self.canvas.create_line(0, i, W, i, fill=col)

        # 圓角邊框（用白色半透明框模擬）
        self.canvas.create_rectangle(1, 1, W - 1, H - 1,
                                     outline="#7C3AED", width=2)

        # 右下角裝飾圓
        self.canvas.create_oval(W - 80, H - 80, W + 40, H + 40,
                                fill="#5B21B6", outline="")
        self.canvas.create_oval(-40, -40, 80, 80,
                                fill="#3730A3", outline="")

    def _draw_logo(self):
        """用 canvas 畫簡化版 icon（論文 + 機器人）"""
        cx, cy = 70, 130

        # 論文本體
        paper = [
            (cx - 22, cy - 35),
            (cx + 12, cy - 35),
            (cx + 22, cy - 25),
            (cx + 22, cy + 35),
            (cx - 22, cy + 35),
        ]
        self.canvas.create_polygon(paper, fill=WHITE, outline="#C4B5FD", width=1)
        # 折角
        self.canvas.create_polygon(
            [(cx + 12, cy - 35), (cx + 22, cy - 25), (cx + 12, cy - 25)],
            fill="#DDD6FE", outline=""
        )
        # 文字橫線
        for dy in [-8, 2, 12]:
            self.canvas.create_line(cx - 14, cy + dy, cx + 14, cy + dy,
                                    fill="#A78BFA", width=2)

        # 機器人臉（圓角矩形用多邊形近似）
        rx, ry = cx + 10, cy - 5
        self.canvas.create_rectangle(rx - 18, ry - 14, rx + 18, ry + 14,
                                     fill="#FDE68A", outline=ACCENT, width=2)
        # 眼睛
        for ex in [rx - 7, rx + 7]:
            self.canvas.create_oval(ex - 4, ry - 5, ex + 4, ry + 3,
                                    fill="#4338CA", outline="")
        # 笑臉弧
        self.canvas.create_arc(rx - 8, ry + 2, rx + 8, ry + 12,
                               start=200, extent=140,
                               style=tk.ARC, outline="#F97316", width=2)
        # 天線
        self.canvas.create_line(rx, ry - 14, rx, ry - 24, fill=ACCENT, width=2)
        self.canvas.create_oval(rx - 4, ry - 28, rx + 4, ry - 20,
                                fill="#FCD34D", outline="")

        # 星星
        def star(scx, scy, sr, col=ACCENT):
            pts = []
            for i in range(8):
                angle = math.pi / 4 * i - math.pi / 2
                r = sr if i % 2 == 0 else sr * 0.4
                pts += [scx + r * math.cos(angle), scy + r * math.sin(angle)]
            self.canvas.create_polygon(pts, fill=col, outline="")

        star(cx - 30, cy - 50, 6,  "#FCD34D")
        star(cx + 38, cy - 48, 5,  "#FDE68A")
        star(cx + 35, cy + 42, 4,  "#FCD34D")

    def _draw_title(self):
        # 主標題
        self.canvas.create_text(240, 90, text="SmartPaper",
                                font=("Helvetica", 28, "bold"),
                                fill=WHITE, anchor="w")
        # 副標題
        self.canvas.create_text(240, 122, text="智能學術論文管理系統",
                                font=("Helvetica", 12),
                                fill=SUBTEXT, anchor="w")
        # 分隔線
        self.canvas.create_line(240, 140, W - 30, 140,
                                fill="#6D28D9", width=1)
        # 提示文字（預留位置）
        self._status_id = self.canvas.create_text(
            240, 158, text="正在啟動...",
            font=("Helvetica", 10), fill=SUBTEXT, anchor="w",
        )

    def _draw_dots(self) -> list:
        """三個跑馬燈圓點，回傳 id 清單以便動畫更新位置。"""
        ids = []
        for _ in range(3):
            oid = self.canvas.create_oval(0, 0, 1, 1, fill=ACCENT, outline="")
            ids.append(oid)
        return ids

    # ── 動畫 ─────────────────────────────────────────────────────────────

    def _animate(self):
        if self._done:
            return

        # 淡入（前 300ms）
        if not self._fading_out and self._alpha < 1.0:
            self._alpha = min(1.0, self._alpha + 0.08)
            self.root.attributes("-alpha", self._alpha)

        # 淡出
        if self._fading_out:
            self._alpha = max(0.0, self._alpha - 0.08)
            self.root.attributes("-alpha", self._alpha)
            if self._alpha <= 0:
                self._done = True
                self.root.destroy()
                return

        # 跑馬燈圓點
        cx_base, cy_dot = 240, 195
        r_orbit = 36
        for i, oid in enumerate(self._dot_ids):
            phase = self._angle + i * (2 * math.pi / 3)
            dx = cx_base + r_orbit * math.cos(phase)
            dy = cy_dot  + 8      * math.sin(phase)
            size = 5 + 3 * math.sin(phase)
            self.canvas.coords(oid, dx - size, dy - size, dx + size, dy + size)
            brightness = int(180 + 75 * math.sin(phase))
            col = f"#{brightness:02x}{int(brightness*0.85):02x}00"
            self.canvas.itemconfig(oid, fill=col)

        self._angle += 0.12
        self.root.after(30, self._animate)

    def set_status(self, text: str):
        try:
            self.canvas.itemconfig(self._status_id, text=text)
        except Exception:
            pass

    def fade_out(self):
        self._fading_out = True

    # ── 主流程 ────────────────────────────────────────────────────────────

    def run(self):
        self._animate()

        def _launch():
            runner = str(PYTHONW) if PYTHONW.exists() else str(PYTHON)
            main_py = str(PROJECT_DIR / "main.py")
            try:
                self.root.after(0, lambda: self.set_status("載入服務模組..."))
                proc = subprocess.Popen(
                    [runner, main_py, "ui"],
                    cwd=str(PROJECT_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # 給 Flet 約 6 秒啟動視窗
                self.root.after(0, lambda: self.set_status("初始化資料庫..."))
                proc.wait(timeout=3)           # 若 3 秒內結束代表失敗
                # 正常不應到這裡（Flet 會持續跑）
            except subprocess.TimeoutExpired:
                # Flet 還在跑，表示成功
                self.root.after(2000, lambda: self.set_status("啟動完成！"))
                self.root.after(2800, self.fade_out)
            except Exception as e:
                self.root.after(0, lambda: self.set_status(f"啟動失敗：{e}"))
                self.root.after(3000, self.fade_out)

        threading.Thread(target=_launch, daemon=True).start()
        self.root.mainloop()


if __name__ == "__main__":
    SplashScreen().run()
