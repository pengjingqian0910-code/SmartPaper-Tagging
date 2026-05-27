"""
SmartPaper Design System
風格：果凍透明感 · 綠色主色 · 清爽有質感
"""
import flet as ft

# ── Color tokens ──────────────────────────────────────────────────────

# Backgrounds — 帶淡綠調的底色，呈現果凍感
PAGE_BG    = "#EDFAF3"   # 淡翠綠底色
SIDEBAR_BG = "#F5FDF8"   # sidebar 帶一絲綠調的白

# Surface
CARD_BG     = "#FFFFFF"
CARD_BORDER = "#6EE7B7"   # emerald-300：鮮明邊框，果凍感關鍵
CARD_SHADOW = "#2010B981" # 12% emerald，綠色光暈

# Typography — 保持中性 zinc，確保可讀性
TEXT_H = "#18181B"   # zinc-900
TEXT_B = "#3F3F46"   # zinc-700
TEXT_M = "#71717A"   # zinc-500
TEXT_D = "#A1A1AA"   # zinc-400

# Primary accent — emerald 綠
ACCENT      = "#10B981"   # emerald-500
ACCENT_SOFT = "#D1FAE5"   # emerald-100
ACCENT_DARK = "#059669"   # emerald-600

# Semantic colors
SUCCESS = "#10B981"
DANGER  = "#EF4444"
WARNING = "#F59E0B"

# Secondary accent — teal（用於漸層搭配）
TEAL   = "#14B8A6"

# Legacy aliases
GREEN  = SUCCESS
ROSE   = DANGER
ORANGE = WARNING
VIOLET = TEAL      # hero gradient 用 teal 取代 violet

# Stat palettes: (bg, accent) — 全部改為綠調
STAT_PALETTES = [
    ("#D1FAE5", "#059669"),   # emerald
    ("#CCFBF1", "#0D9488"),   # teal
    ("#D1FAE5", "#10B981"),   # emerald lighter
    ("#F0FDF4", "#16A34A"),   # green
]

# ── Spacing scale (8px grid) ─────────────────────────────────────────
SP1 = 4
SP2 = 8
SP3 = 12
SP4 = 16
SP5 = 24
SP6 = 32
SP7 = 40
SP8 = 48

# ── Border radius ────────────────────────────────────────────────────
RADIUS_S  = 8
RADIUS_M  = 12
RADIUS_L  = 16
RADIUS_XL = 22

# ── Animations (ease-out, 200-300ms) ─────────────────────────────────
ANIM      = ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT)
ANIM_SLOW = ft.animation.Animation(300, ft.AnimationCurve.EASE_OUT)


def alpha(hex_color: str, opacity: float) -> str:
    """Convert #RRGGBB + opacity (0–1) → #AARRGGBB"""
    hex_color = hex_color.lstrip("#")
    a = int(opacity * 255)
    return f"#{a:02X}{hex_color}"


_alpha = alpha


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
) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=radius,
        bgcolor=bg,
        border=ft.border.all(1.5, border_color),
        shadow=ft.BoxShadow(
            blur_radius=18,
            spread_radius=-2,
            color=CARD_SHADOW,
            offset=ft.Offset(0, 4),
        ),
        expand=expand,
        width=width,
        height=height,
        on_click=on_click,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


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
            blur_radius=24,
            spread_radius=-4,
            color=_alpha(ACCENT, 0.30),
            offset=ft.Offset(0, 8),
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
    return ft.Text(
        text.upper(),
        size=10,
        weight=ft.FontWeight.W_600,
        color=ACCENT_DARK,
    )


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
            [
                ft.Icon(icon, size=14, color=fg),
                ft.Text(text, size=13, weight=ft.FontWeight.W_500, color=fg),
            ],
            spacing=SP2,
            tight=True,
        ),
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_M),
            padding=ft.padding.symmetric(horizontal=SP4, vertical=10),
            bgcolor=color if filled else _alpha(color, 0.10),
            elevation=0,
            overlay_color=_alpha("#FFFFFF" if filled else color, 0.10),
        ),
    )


# ── Micro components ──────────────────────────────────────────────────

def icon_badge(icon, color: str = ACCENT, size: int = 16, bg_size: int = 36) -> ft.Container:
    return ft.Container(
        content=ft.Icon(icon, size=size, color=color),
        width=bg_size,
        height=bg_size,
        border_radius=bg_size // 2,
        bgcolor=_alpha(color, 0.12),
        alignment=ft.alignment.center,
    )


def tag_chip(text: str, color: str = ACCENT) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, color=color, weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=SP3, vertical=SP1),
        border_radius=RADIUS_S,
        bgcolor=_alpha(color, 0.10),
        border=ft.border.all(1, _alpha(color, 0.25)),
    )


def soft_divider(height: int = 1) -> ft.Container:
    return ft.Container(height=height, bgcolor=_alpha(ACCENT, 0.20))
