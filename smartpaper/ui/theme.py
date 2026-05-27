"""
SmartPaper Design System
風格：Linear / Vercel / Stripe — clean, neutral, typography-first
"""
import flet as ft

# ── Color tokens ──────────────────────────────────────────────────────
# Background layers
PAGE_BG    = "#F7F7F8"   # zinc-50, neutral (not blue-tinted)
SIDEBAR_BG = "#FFFFFF"

# Surface
CARD_BG     = "#FFFFFF"
CARD_BORDER = "#E4E4E7"   # zinc-200, neutral
CARD_SHADOW = "#09000000" # 3.5% black, barely-there

# Typography — zinc scale
TEXT_H = "#18181B"   # zinc-900, headings
TEXT_B = "#3F3F46"   # zinc-700, body
TEXT_M = "#71717A"   # zinc-500, muted / meta
TEXT_D = "#A1A1AA"   # zinc-400, disabled / placeholder

# Primary accent — indigo (ONE accent color, used sparingly)
ACCENT      = "#6366F1"
ACCENT_SOFT = "#EEF2FF"
ACCENT_DARK = "#4F46E5"

# Semantic — only for status indicators, not decoration
SUCCESS = "#10B981"   # emerald
DANGER  = "#EF4444"   # red
WARNING = "#F59E0B"   # amber

# Legacy aliases — kept for backward compat with views that import these
GREEN  = SUCCESS
ROSE   = DANGER
ORANGE = WARNING
VIOLET = "#8B5CF6"
TEAL   = "#14B8A6"

# Stat card palettes: (bg, accent) — muted tones
STAT_PALETTES = [
    ("#F4F4F5", "#52525B"),   # zinc
    ("#F0FDF4", "#059669"),   # green
    ("#FFFBEB", "#D97706"),   # amber
    ("#EFF6FF", "#3B82F6"),   # blue
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
RADIUS_S  = 6
RADIUS_M  = 10
RADIUS_L  = 14
RADIUS_XL = 20

# ── Animations (ease-out, 200-300ms) ─────────────────────────────────
ANIM      = ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT)
ANIM_SLOW = ft.animation.Animation(300, ft.AnimationCurve.EASE_OUT)


def alpha(hex_color: str, opacity: float) -> str:
    """Convert #RRGGBB + opacity (0–1) → #AARRGGBB"""
    hex_color = hex_color.lstrip("#")
    a = int(opacity * 255)
    return f"#{a:02X}{hex_color}"


_alpha = alpha


# ── Card factory ─────────────────────────────────────────────────────

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
        border=ft.border.all(1, border_color),
        shadow=ft.BoxShadow(
            blur_radius=8,
            spread_radius=0,
            color=CARD_SHADOW,
            offset=ft.Offset(0, 2),
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
            colors=colors or [ACCENT, ACCENT_DARK],
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
        color=TEXT_D,
        letter_spacing=0.5,
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
            bgcolor=color if filled else _alpha(color, 0.07),
            elevation=0,
            overlay_color=_alpha("#000000" if filled else color, 0.06),
        ),
    )


# ── Micro components ──────────────────────────────────────────────────

def icon_badge(icon, color: str = ACCENT, size: int = 16, bg_size: int = 36) -> ft.Container:
    """Kept for backward compat — prefer plain icons in new designs."""
    return ft.Container(
        content=ft.Icon(icon, size=size, color=color),
        width=bg_size,
        height=bg_size,
        border_radius=bg_size // 2,
        bgcolor=_alpha(color, 0.10),
        alignment=ft.alignment.center,
    )


def tag_chip(text: str, color: str = ACCENT) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, color=color, weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=SP3, vertical=SP1),
        border_radius=RADIUS_S,
        bgcolor=_alpha(color, 0.08),
        border=ft.border.all(1, _alpha(color, 0.18)),
    )


def soft_divider(height: int = 1) -> ft.Container:
    return ft.Container(height=height, bgcolor=CARD_BORDER)
