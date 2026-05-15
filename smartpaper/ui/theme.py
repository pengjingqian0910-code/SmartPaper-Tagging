"""
SmartPaper Design System
風格：Bento Box + 果凍透明感 + 簡約

顏色透明度以 #AARRGGBB 格式表示（AA = hex alpha）
  10% → 1A   12% → 1F   20% → 33   25% → 40
  28% → 47   30% → 4D   40% → 66   80% → CC
"""
import flet as ft

# ── colors ────────────────────────────────────────────────────────────
PAGE_BG = "#EDF0FF"
SIDEBAR_BG = "#FFFFFF"

CARD_BG = "#FFFFFF"
CARD_BORDER = "#DDE3FF"
CARD_SHADOW = "#1A5A5FDB"      # 10% indigo

TEXT_H = "#1E1B4B"
TEXT_B = "#374151"
TEXT_M = "#9CA3AF"

ACCENT = "#6366F1"
ACCENT_SOFT = "#EEF2FF"
ACCENT_DARK = "#4F46E5"

GREEN = "#10B981"
ORANGE = "#F59E0B"
VIOLET = "#8B5CF6"
ROSE = "#F43F5E"
TEAL = "#14B8A6"

# ── Stat card palettes: (card_bg, accent) ─────────────────────────────
STAT_PALETTES = [
    ("#EEF2FF", "#6366F1"),
    ("#F0FDF4", "#10B981"),
    ("#FFF7ED", "#F59E0B"),
    ("#F5F3FF", "#8B5CF6"),
]


def alpha(hex_color: str, opacity: float) -> str:
    """Convert #RRGGBB + opacity (0-1) → #AARRGGBB"""
    hex_color = hex_color.lstrip("#")
    a = int(opacity * 255)
    return f"#{a:02X}{hex_color}"


_alpha = alpha  # internal alias


# ── Card factories ────────────────────────────────────────────────────

def card(
    content,
    *,
    padding=24,
    radius: int = 20,
    bg: str = CARD_BG,
    border_color: str = CARD_BORDER,
    shadow_color: str = CARD_SHADOW,
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
            blur_radius=24,
            spread_radius=-4,
            color=shadow_color,
            offset=ft.Offset(0, 8),
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
    padding=28,
    radius: int = 24,
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
            colors=colors or [ACCENT, VIOLET],
        ),
        shadow=ft.BoxShadow(
            blur_radius=32,
            spread_radius=-4,
            color=_alpha(ACCENT, 0.28),
            offset=ft.Offset(0, 10),
        ),
        expand=expand,
        width=width,
        height=height,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )


# ── Typography ────────────────────────────────────────────────────────

def h1(text: str, color=None) -> ft.Text:
    return ft.Text(text, size=26, weight=ft.FontWeight.BOLD, color=color or TEXT_H)


def h2(text: str, color=None) -> ft.Text:
    return ft.Text(text, size=18, weight=ft.FontWeight.W_600, color=color or TEXT_H)


def h3(text: str, color=None) -> ft.Text:
    return ft.Text(text, size=15, weight=ft.FontWeight.W_600, color=color or TEXT_H)


def body(text: str, **kwargs) -> ft.Text:
    return ft.Text(text, size=13, color=TEXT_B, **kwargs)


def muted(text: str, **kwargs) -> ft.Text:
    return ft.Text(text, size=12, color=TEXT_M, **kwargs)


def section_label(text: str) -> ft.Text:
    return ft.Text(
        text.upper(),
        size=11,
        weight=ft.FontWeight.W_600,
        color=TEXT_M,
    )


# ── Button ────────────────────────────────────────────────────────────

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
                ft.Icon(icon, size=15, color=fg),
                ft.Text(text, size=13, weight=ft.FontWeight.W_500, color=fg),
            ],
            spacing=6,
            tight=True,
        ),
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=50),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
            bgcolor=color if filled else _alpha(color, 0.08),
            elevation=0,
            overlay_color=_alpha("#FFFFFF", 0.12),
        ),
    )


# ── Micro components ──────────────────────────────────────────────────

def icon_badge(icon, color: str = ACCENT, size: int = 18, bg_size: int = 40) -> ft.Container:
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
        padding=ft.padding.symmetric(horizontal=10, vertical=4),
        border_radius=50,
        bgcolor=_alpha(color, 0.10),
        border=ft.border.all(1, _alpha(color, 0.20)),
    )


def soft_divider(height: int = 1) -> ft.Container:
    return ft.Container(height=height, bgcolor=CARD_BORDER, border_radius=1)
