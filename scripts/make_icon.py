"""
SmartPaper — 圖示產生器 v2
輸出：assets/icon.ico (Windows) + assets/icon.png (macOS / 通用)

執行：python scripts/make_icon.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)
OUT_ICO = ASSETS / "icon.ico"
OUT_PNG = ASSETS / "icon.png"


# ── 色彩 ──────────────────────────────────────────────────────────────────
BG_TOP     = (76,  29, 149)    # #4C1D95  深紫
BG_BOT     = (30,  27,  75)    # #1E1B4B  近黑紫
FACE_COLOR = (221, 214, 254)   # #DDD6FE  薰衣草
FACE_SHADE = (196, 181, 253)   # #C4B5FD  稍深一點（底部）
EYE_WHITE  = (255, 255, 255)
EYE_PUPIL  = ( 67,  56, 202)   # #4338CA  靛藍
EYE_SHINE  = (255, 255, 255)
SMILE_COL  = (109,  40, 217)   # #6D28D9  紫羅蘭
CHEEK_COL  = (252, 165, 165, 90)  # 淡粉紅（帶透明）
ANT_STEM   = (167, 139, 250)   # #A78BFA
ANT_BALL   = (251, 191,  36)   # #FBBF24  琥珀金
ANT_HILITE = (255, 243, 163)   # 高光
PAPER_BODY = (255, 255, 255)
PAPER_FOLD = (224, 215, 254)   # #E0D7FE
PAPER_LINE = (196, 181, 253)   # #C4B5FD
STAR_GOLD  = (251, 191,  36)
STAR_SOFT  = (196, 181, 253)   # 紫色小星（點綴）


# ── 工具函式 ──────────────────────────────────────────────────────────────

def lerp_int(a, b, t):
    return int(a + (b - a) * t)


def paste_with_blur(base: Image.Image, layer: Image.Image, blur: float) -> Image.Image:
    """將 layer 高斯模糊後以 alpha_composite 貼到 base，回傳新圖。"""
    blurred = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(base, blurred)


def draw_gradient_bg(img: Image.Image, pad: int, radius: int):
    """在 img 上繪製圓角矩形漸層背景。"""
    s = img.size[0]
    grad = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    for y in range(s):
        t = y / s
        r = lerp_int(BG_TOP[0], BG_BOT[0], t)
        g = lerp_int(BG_TOP[1], BG_BOT[1], t)
        b = lerp_int(BG_TOP[2], BG_BOT[2], t)
        grad.paste((r, g, b, 255), (0, y, s, y + 1))

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, s - pad, s - pad], radius=radius, fill=255
    )
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bg.paste(grad, mask=mask)
    return Image.alpha_composite(img, bg)


def draw_sparkle(d: ImageDraw.ImageDraw, cx, cy, r, color, points=4):
    """繪製 N 角閃光星。"""
    pts = []
    for i in range(points * 2):
        angle = math.pi / points * i - math.pi / 2
        rr = r if i % 2 == 0 else r * 0.38
        pts.append((cx + rr * math.cos(angle), cy + rr * math.sin(angle)))
    d.polygon(pts, fill=color)


# ── 主繪圖函式 ────────────────────────────────────────────────────────────

def draw_icon(size: int) -> Image.Image:
    s = size

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # ── 1. 漸層背景 ─────────────────────────────────────────────────
    pad = max(2, int(s * 0.04))
    rad = int(s * 0.22)
    img = draw_gradient_bg(img, pad, rad)
    d = ImageDraw.Draw(img)

    # 頂部微光（讓背景有玻璃感）
    d.rounded_rectangle(
        [pad + 1, pad + 1, s - pad - 1, s // 3],
        radius=rad,
        fill=(255, 255, 255, 18),
    )

    # ── 2. 論文徽章（右下角，小而精緻）────────────────────────────
    #   讓機器人「抱著」論文的感覺
    ppw   = int(s * 0.30)
    pph   = int(s * 0.32)
    ppx   = s - pad - ppw - int(s * 0.04)
    ppy   = s - pad - pph - int(s * 0.04)
    pfold = int(s * 0.07)

    # 陰影
    sh_paper = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sp_d = ImageDraw.Draw(sh_paper)
    sp_d.polygon(
        [
            (ppx + 3,           ppy + pfold + 2),
            (ppx + ppw - pfold + 3, ppy + 2),
            (ppx + ppw + 3,     ppy + pfold + 2),
            (ppx + ppw + 3,     ppy + pph + 2),
            (ppx + 3,           ppy + pph + 2),
        ],
        fill=(0, 0, 0, 55),
    )
    img = paste_with_blur(img, sh_paper, max(1, s / 64))
    d = ImageDraw.Draw(img)

    # 紙張主體
    d.polygon(
        [
            (ppx,               ppy + pfold),
            (ppx + ppw - pfold, ppy),
            (ppx + ppw,         ppy + pfold),
            (ppx + ppw,         ppy + pph),
            (ppx,               ppy + pph),
        ],
        fill=PAPER_BODY,
    )
    # 折角
    d.polygon(
        [
            (ppx + ppw - pfold, ppy),
            (ppx + ppw,         ppy + pfold),
            (ppx + ppw - pfold, ppy + pfold),
        ],
        fill=PAPER_FOLD,
    )
    # 文字線條
    lx1 = ppx + int(ppw * 0.14)
    lx2 = ppx + ppw - int(ppw * 0.14)
    lw  = max(1, s // 72)
    for frac in (0.40, 0.56, 0.72):
        ly = ppy + pfold + int((pph - pfold) * frac)
        d.line([(lx1, ly), (lx2, ly)], fill=PAPER_LINE, width=lw)

    # ── 3. 機器人臉（主角，居中偏上）───────────────────────────────
    # 臉的位置：左右居中，垂直偏上（讓論文徽章在右下不被遮住）
    fw  = int(s * 0.58)
    fh  = int(s * 0.52)
    fx  = (s - fw) // 2
    fy  = int(s * 0.16)
    fr  = int(s * 0.13)

    # 臉部陰影
    sh_face = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sf_d = ImageDraw.Draw(sh_face)
    sf_d.rounded_rectangle(
        [fx + 4, fy + 6, fx + fw + 4, fy + fh + 6],
        radius=fr, fill=(0, 0, 0, 60),
    )
    img = paste_with_blur(img, sh_face, max(2, s / 40))
    d = ImageDraw.Draw(img)

    # 臉部漸層（用兩層圓角矩形模擬）
    d.rounded_rectangle([fx, fy, fx + fw, fy + fh], radius=fr, fill=FACE_COLOR)
    # 底部陰影色（只在夠大時畫，避免座標倒轉）
    shade_y0 = fy + fh // 2
    shade_y1 = fy + fh - 2
    if shade_y1 > shade_y0:
        d.rounded_rectangle([fx + 2, shade_y0, fx + fw - 2, shade_y1],
                             radius=fr, fill=FACE_SHADE)
    # 頂部高光
    hl_y0 = fy + 4
    hl_y1 = fy + fh // 3
    if hl_y1 > hl_y0 and (fx + fw - 4) > (fx + 4):
        d.rounded_rectangle([fx + 4, hl_y0, fx + fw - 4, hl_y1],
                             radius=fr, fill=(255, 255, 255, 55))

    # 耳朵（小圓形在臉兩側）
    ear_r = int(s * 0.052)
    ear_y = fy + int(fh * 0.52)
    d.ellipse([fx - ear_r, ear_y - ear_r, fx + ear_r, ear_y + ear_r], fill=FACE_COLOR)
    d.ellipse(
        [fx + fw - ear_r, ear_y - ear_r, fx + fw + ear_r, ear_y + ear_r],
        fill=FACE_COLOR,
    )
    # 耳朵裝飾圓點
    inner_r = int(ear_r * 0.52)
    for ex in [fx, fx + fw]:
        d.ellipse(
            [ex - inner_r, ear_y - inner_r, ex + inner_r, ear_y + inner_r],
            fill=ANT_STEM,
        )

    # 天線
    ant_x    = fx + fw // 2
    ant_base = fy
    ant_top  = fy - int(s * 0.11)
    ant_sw   = max(2, s // 38)
    d.line([(ant_x, ant_base), (ant_x, ant_top)], fill=ANT_STEM, width=ant_sw)
    # 天線球（金色，帶高光）
    ant_r = int(s * 0.052)
    d.ellipse(
        [ant_x - ant_r, ant_top - ant_r, ant_x + ant_r, ant_top + ant_r],
        fill=ANT_BALL,
    )
    hl_r = max(1, ant_r // 2)
    d.ellipse(
        [
            ant_x - ant_r + hl_r // 2,
            ant_top - ant_r + hl_r // 2,
            ant_x - ant_r + hl_r // 2 + hl_r,
            ant_top - ant_r + hl_r // 2 + hl_r,
        ],
        fill=ANT_HILITE,
    )

    # 眼睛
    eye_r  = int(s * 0.082)
    eye_y  = fy + int(fh * 0.37)
    eye_off = int(fw * 0.24)
    ex_l   = fx + fw // 2 - eye_off
    ex_r   = fx + fw // 2 + eye_off

    for ex in [ex_l, ex_r]:
        # 白眼珠
        d.ellipse(
            [ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r],
            fill=EYE_WHITE,
        )
        # 瞳孔（稍微往下，讓眼神更柔和）
        p_r = int(eye_r * 0.56)
        p_y = eye_y + int(eye_r * 0.18)
        d.ellipse(
            [ex - p_r, p_y - p_r, ex + p_r, p_y + p_r],
            fill=EYE_PUPIL,
        )
        # 高光反射
        sh_r = max(1, p_r // 3)
        d.ellipse(
            [
                ex - p_r + sh_r,
                p_y - p_r + sh_r,
                ex - p_r + sh_r * 3,
                p_y - p_r + sh_r * 3,
            ],
            fill=EYE_SHINE,
        )

    # 腮紅（疊加半透明粉紅橢圓）
    cheek_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ck_d = ImageDraw.Draw(cheek_layer)
    ck_r_x = int(s * 0.062)
    ck_r_y = int(s * 0.040)
    ck_y   = fy + int(fh * 0.62)
    for ck_x in [fx + int(fw * 0.18), fx + fw - int(fw * 0.18)]:
        ck_d.ellipse(
            [ck_x - ck_r_x, ck_y - ck_r_y, ck_x + ck_r_x, ck_y + ck_r_y],
            fill=CHEEK_COL,
        )
    img = Image.alpha_composite(img, cheek_layer)
    d = ImageDraw.Draw(img)

    # 嘴巴（弧形微笑）
    sm_l = fx + int(fw * 0.27)
    sm_r = fx + int(fw * 0.73)
    sm_t = fy + int(fh * 0.64)
    sm_b = fy + int(fh * 0.84)
    sm_w = max(2, s // 30)
    d.arc([sm_l, sm_t, sm_r, sm_b], start=12, end=168, fill=SMILE_COL, width=sm_w)

    # ── 4. 閃光裝飾 ──────────────────────────────────────────────────
    draw_sparkle(d, int(s * 0.11), int(s * 0.22), int(s * 0.048), STAR_GOLD)
    draw_sparkle(d, int(s * 0.88), int(s * 0.20), int(s * 0.036), STAR_GOLD)
    draw_sparkle(d, int(s * 0.10), int(s * 0.76), int(s * 0.027), STAR_SOFT)

    return img


# ── 儲存 ──────────────────────────────────────────────────────────────────

def main():
    ico_sizes = [256, 128, 64, 48, 32, 16]
    frames = [draw_icon(sz) for sz in ico_sizes]

    # Windows .ico
    frames[0].save(
        OUT_ICO,
        format="ICO",
        sizes=[(sz, sz) for sz in ico_sizes],
        append_images=frames[1:],
    )
    print(f"[OK] icon.ico  -> {OUT_ICO}")

    # 通用 PNG（512px，macOS / 其他平台用）
    big = draw_icon(512)
    big.save(OUT_PNG, format="PNG")
    print(f"[OK] icon.png  -> {OUT_PNG}")


if __name__ == "__main__":
    main()
