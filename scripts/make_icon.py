"""
產生 SmartPaper 應用程式圖示 (assets/icon.ico)
執行：python make_icon.py
"""

import math
import os
from pathlib import Path
from PIL import Image, ImageDraw

ASSETS = Path(__file__).parent / "assets"
ASSETS.mkdir(exist_ok=True)
OUT_ICO = ASSETS / "icon.ico"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # ── 背景圓角矩形（紫色漸層用兩層色塊模擬）──────────────────────
    pad = int(s * 0.04)
    r   = int(s * 0.22)
    bg_top    = (108, 43, 217)   # #6C2BD9
    bg_bottom = (79,  70, 229)   # #4F46E5
    # 上半
    d.rounded_rectangle([pad, pad, s - pad, s // 2 + pad], radius=r, fill=bg_top)
    # 下半
    d.rounded_rectangle([pad, s // 2 - pad, s - pad, s - pad], radius=r, fill=bg_bottom)
    # 整體再蓋一次讓邊角乾淨
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=r,
                         fill=None, outline=(255, 255, 255, 40), width=max(1, s // 64))

    # ── 論文（白色矩形，右下角折角）───────────────────────────────
    px  = int(s * 0.28)
    py  = int(s * 0.18)
    pw  = int(s * 0.36)
    ph  = int(s * 0.44)
    fold = int(s * 0.10)
    paper_color  = (255, 255, 255)
    fold_color   = (220, 215, 255)

    # 主體（折角裁掉右上）
    poly = [
        (px,          py),
        (px + pw - fold, py),
        (px + pw,     py + fold),
        (px + pw,     py + ph),
        (px,          py + ph),
    ]
    d.polygon(poly, fill=paper_color)

    # 折角三角
    d.polygon([
        (px + pw - fold, py),
        (px + pw,        py + fold),
        (px + pw - fold, py + fold),
    ], fill=fold_color)

    # 文字橫線（三條）
    lx1 = px + int(s * 0.05)
    lx2 = px + pw - int(s * 0.06)
    ly  = [py + int(ph * 0.38), py + int(ph * 0.54), py + int(ph * 0.70)]
    lw  = max(1, s // 48)
    line_color = (180, 170, 230)
    for ly_i in ly:
        d.line([(lx1, ly_i), (lx2, ly_i)], fill=line_color, width=lw)

    # ── 機器人頭（圓角矩形，蓋在論文上方偏右）───────────────────────
    bx  = int(s * 0.44)
    by  = int(s * 0.38)
    bw  = int(s * 0.30)
    bh  = int(s * 0.25)
    br  = int(s * 0.06)
    robot_bg    = (254, 240, 138)   # 淡黃色臉
    robot_bdr   = (251, 191,  36)   # 金色邊框
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=br,
                         fill=robot_bg, outline=robot_bdr,
                         width=max(1, s // 48))

    # 眼睛（兩個深色實心圓）
    ew = max(2, s // 20)
    ex1 = bx + int(bw * 0.28)
    ex2 = bx + int(bw * 0.68)
    ey  = by + int(bh * 0.38)
    eye_color = (79, 70, 229)
    d.ellipse([ex1 - ew, ey - ew, ex1 + ew, ey + ew], fill=eye_color)
    d.ellipse([ex2 - ew, ey - ew, ex2 + ew, ey + ew], fill=eye_color)

    # 微笑弧線
    mx1 = bx + int(bw * 0.25)
    mx2 = bx + int(bw * 0.75)
    my  = by + int(bh * 0.65)
    arc_h = int(bh * 0.22)
    smile_color = (251, 146, 60)
    d.arc([mx1, my - arc_h, mx2, my + arc_h],
          start=10, end=170, fill=smile_color,
          width=max(1, s // 42))

    # 天線（小短線 + 圓點）
    ax = bx + bw // 2
    ay = by
    al = int(s * 0.07)
    d.line([(ax, ay), (ax, ay - al)], fill=robot_bdr, width=max(1, s // 44))
    ar = max(2, s // 28)
    d.ellipse([ax - ar, ay - al - ar, ax + ar, ay - al + ar], fill=(252, 211, 77))

    # ── 四顆小星星（散布在角落）─────────────────────────────────────
    def star(cx, cy, r_out, points=4, color=(255, 223, 100)):
        pts = []
        for i in range(points * 2):
            angle = math.pi / points * i - math.pi / 2
            r = r_out if i % 2 == 0 else r_out * 0.42
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        d.polygon(pts, fill=color)

    stars = [
        (int(s * 0.15), int(s * 0.18), int(s * 0.055), (255, 220, 80)),
        (int(s * 0.82), int(s * 0.15), int(s * 0.045), (255, 200, 60)),
        (int(s * 0.78), int(s * 0.78), int(s * 0.038), (255, 210, 90)),
        (int(s * 0.18), int(s * 0.78), int(s * 0.032), (255, 230, 100)),
    ]
    for (cx, cy, ro, col) in stars:
        star(cx, cy, ro, color=col)

    return img


def main():
    sizes = [256, 128, 64, 48, 32, 16]
    frames = [draw_icon(sz) for sz in sizes]
    frames[0].save(
        OUT_ICO, format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )
    print(f"[OK] Icon saved to: {OUT_ICO}")


if __name__ == "__main__":
    main()
