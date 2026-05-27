"""
SmartPaper Design System
風格：果凍透明感 · 綠色主色 · 彈跳動畫
"""
import time
import threading
import flet as ft

# ── Color tokens ──────────────────────────────────────────────────────

# Backgrounds
PAGE_BG    = "#D1FAE5"   # emerald-100，飽和底色讓透明感更明顯
SIDEBAR_BG = "#ECFDF5"   # emerald-50，sidebar 輕透綠

# Glass card — 半透明白，疊在綠底色上呈現果凍感
CARD_BG      = "#E8FFFFFF"   # ~91% 透明白
CARD_BORDER  = "#34D399"     # emerald-400，鮮明邊框
CARD_SHADOW  = "#3310B981"   # 20% emerald 綠色光暈

# Typography — zinc 灰保持可讀性
TEXT_H = "#18181B"
TEXT_B = "#3F3F46"
TEXT_M = "#52525B"
TEXT_D = "#A1A1AA"

# Primary accent — emerald
ACCENT      = "#10B981"
ACCENT_SOFT = "#D1FAE5"
ACCENT_DARK = "#059669"

# Semantic
SUCCESS = "#10B981"
DANGER  = "#EF4444"
WARNING = "#F59E0B"
TEAL    = "#14B8A6"

# Legacy aliases
GREEN  = SUCCESS
ROSE   = DANGER
ORANGE = WARNING
VIOLET = TEAL

# Stat palettes: (bg, accent)
STAT_PALETTES = [
    ("#D1FAE5", "#059669"),
    ("#CCFBF1", "#0D9488"),
    ("#D1FAE5", "#10B981"),
    ("#F0FDF4", "#16A34A"),
]

# ── Spacing (8px grid) ───────────────────────────────────────────────
SP1 = 4;  SP2 = 8;  SP3 = 12;  SP4 = 16
SP5 = 24; SP6 = 32; SP7 = 40;  SP8 = 48

# ── Border radius ────────────────────────────────────────────────────
RADIUS_S  = 8
RADIUS_M  = 12
RADIUS_L  = 16
RADIUS_XL = 22

# ── Animations ───────────────────────────────────────────────────────
ANIM           = ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT)
ANIM_SLOW      = ft.animation.Animation(300, ft.AnimationCurve.EASE_OUT)
# 果凍彈跳：壓縮快（80ms ease-in）→ 回彈慢（500ms elastic-out）
_ANIM_COMPRESS = ft.animation.Animation(80,  ft.AnimationCurve.EASE_IN)
_ANIM_BOUNCE   = ft.animation.Animation(500, ft.AnimationCurve.ELASTIC_OUT)


def alpha(hex_color: str, opacity: float) -> str:
    """Convert #RRGGBB + opacity (0–1) → #AARRGGBB"""
    a = int(opacity * 255)
    return f"#{a:02X}{hex_color.lstrip('#')}"


_alpha = alpha


# ── Jelly bounce ─────────────────────────────────────────────────────

def jelly_tap(container: ft.Container, page: ft.Page,
              callback=None) -> None:
    """
    點擊時觸發果凍彈跳動畫：壓縮 → 彈回（elastic-out）。
    container 必須事先設定 animate_scale。
    """
    def _run():
        # ① 快速壓縮
        container.animate_scale = _ANIM_COMPRESS
        container.scale = ft.transform.Scale(0.92)
        page.update()
        time.sleep(0.09)
        # ② elastic 彈回
        container.animate_scale = _ANIM_BOUNCE
        container.scale = ft.transform.Scale(1.0)
        page.update()
        if callback:
            callback()
    threading.Thread(target=_run, daemon=True).start()


# ── Card factories ────────────────────────────────────────────────────

def card(
    content,
    *,
    padding=SP5,
    radius: int = RADIUS_L,
    bg: str = CARD_BG,
    border_color: str = CARD_BORDER,
    expand=False,
    width=None,
    height=None,
    on_click=None,
    page: ft.Page = None,     # 傳入 page 啟用彈跳動畫
) -> ft.Container:
    container = ft.Container(
        content=content,
        padding=padding,
        border_radius=radius,
        bgcolor=bg,
        border=ft.border.all(1.5, border_color),
        shadow=ft.BoxShadow(
            blur_radius=20,
            spread_radius=-2,
            color=CARD_SHADOW,
            offset=ft.Offset(0, 6),
        ),
        expand=expand,
        width=width,
        height=height,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        animate_scale=_ANIM_BOUNCE,   # 預設啟用 elastic scale
    )

    if on_click and page:
        def _click(e, _c=container, _p=page, _cb=on_click):
            jelly_tap(_c, _p, lambda: _cb(e))
        container.on_click = _click
    elif on_click:
        container.on_click = on_click

    return container


def gradient_card(
    content,
    *,
    colors=None,
    padding=SP5,
    radius: int = RADIUS_L,
    expand=False,
    width=None,
    height=None,
) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=radius,
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=colors or [ACCENT, TEAL],
        ),
        shadow=ft.BoxShadow(
            blur_radius=28,
            spread_radius=-4,
            color=_alpha(ACCENT, 0.35),
            offset=ft.Offset(0, 10),
        ),
        expand=expand,
        width=width,
        height=height,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


# ── Typography ────────────────────────────────────────────────────────

def h1(text: str, color=None) -> ft.Text:
    return ft.Text(text, size=24, weight=ft.FontWeight.BOLD, color=color or TEXT_H)

def h2(text: str, color=None) -> ft.Text:
    return ft.Text(text, size=17, weight=ft.FontWeight.W_600, color=color or TEXT_H)

def h3(text: str, color=None) -> ft.Text:
    return ft.Text(text, size=14, weight=ft.FontWeight.W_600, color=color or TEXT_H)

def body(text: str, **kwargs) -> ft.Text:
    return ft.Text(text, size=13, color=TEXT_B, **kwargs)

def muted(text: str, **kwargs) -> ft.Text:
    return ft.Text(text, size=12, color=TEXT_M, **kwargs)

def section_label(text: str) -> ft.Text:
    return ft.Text(text.upper(), size=10, weight=ft.FontWeight.W_600, color=ACCENT_DARK)


# ── Buttons ───────────────────────────────────────────────────────────

def pill_btn(
    text: str,
    icon,
    on_click,
    *,
    filled: bool = True,
    color: str = ACCENT,
    disabled: bool = False,
) -> ft.ElevatedButton:
    fg = "#FFFFFF" if filled else color
    return ft.ElevatedButton(
        content=ft.Row(
            [ft.Icon(icon, size=14, color=fg),
             ft.Text(text, size=13, weight=ft.FontWeight.W_500, color=fg)],
            spacing=SP2, tight=True,
        ),
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_M),
            padding=ft.padding.symmetric(horizontal=SP4, vertical=10),
            bgcolor=color if filled else _alpha(color, 0.12),
            elevation=0,
            overlay_color=_alpha("#FFFFFF" if filled else color, 0.12),
        ),
    )


# ── Micro components ──────────────────────────────────────────────────

def icon_badge(icon, color: str = ACCENT, size: int = 16, bg_size: int = 36) -> ft.Container:
    return ft.Container(
        content=ft.Icon(icon, size=size, color=color),
        width=bg_size, height=bg_size,
        border_radius=bg_size // 2,
        bgcolor=_alpha(color, 0.14),
        alignment=ft.alignment.center,
    )


def tag_chip(text: str, color: str = ACCENT) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, color=color, weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=SP3, vertical=SP1),
        border_radius=RADIUS_S,
        bgcolor=_alpha(color, 0.12),
        border=ft.border.all(1, _alpha(color, 0.28)),
    )


def soft_divider(height: int = 1) -> ft.Container:
    return ft.Container(height=height, bgcolor=_alpha(ACCENT, 0.25))
