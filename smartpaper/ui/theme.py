"""
SmartPaper Design System
參考：Linear（暗色 sidebar）/ Stripe（按鈕配色）/ Vercel（卡片版面）
"""
import flet as ft

# ── Palette ───────────────────────────────────────────────────────────

# Content area — Vercel / Stripe 的極淺灰底
PAGE_BG = "#F5F5F5"

# Sidebar — Linear 的深色側欄
SIDEBAR_BG       = "#111827"   # gray-900
SIDEBAR_BORDER   = "#1F2937"   # gray-800
SIDEBAR_ICON     = "#6B7280"   # gray-500  (inactive)
SIDEBAR_ICON_ACT = "#FFFFFF"   # white     (active)
SIDEBAR_TEXT     = "#9CA3AF"   # gray-400  (inactive)
SIDEBAR_TEXT_ACT = "#FFFFFF"   # white     (active)
SIDEBAR_ACTIVE   = "#1D4ED8"   # blue-700 pill  (Linear 風格)
SIDEBAR_HOVER    = "#1F2937"   # gray-800

# Cards — 純白、細邊框、淺陰影（Vercel 風格）
CARD_BG     = "#FFFFFF"
CARD_BORDER = "#E5E7EB"   # gray-200
CARD_SHADOW = "#0A000000" # 4% black

# Typography — gray scale，不用純黑
TEXT_H = "#111827"   # gray-900
TEXT_B = "#374151"   # gray-700
TEXT_M = "#6B7280"   # gray-500
TEXT_D = "#9CA3AF"   # gray-400

# Primary accent — Stripe 的 indigo-blue
ACCENT      = "#4F46E5"   # indigo-600
ACCENT_SOFT = "#EEF2FF"   # indigo-50
ACCENT_DARK = "#3730A3"   # indigo-800

# Semantic
SUCCESS = "#059669"   # emerald-600
DANGER  = "#DC2626"   # red-600
WARNING = "#D97706"   # amber-600

# Legacy
GREEN  = SUCCESS
ROSE   = DANGER
ORANGE = WARNING
VIOLET = "#7C3AED"   # violet-700
TEAL   = "#0D9488"   # teal-600

# Stat palettes: (bg, accent)
STAT_PALETTES = [
    ("#EEF2FF", "#4F46E5"),
    ("#F0FDF4", "#059669"),
    ("#FEF3C7", "#D97706"),
    ("#F5F3FF", "#7C3AED"),
]

# ── Spacing (8px grid) ───────────────────────────────────────────────
SP1 = 4;  SP2 = 8;  SP3 = 12;  SP4 = 16
SP5 = 24; SP6 = 32; SP7 = 40;  SP8 = 48

# ── Border radius ────────────────────────────────────────────────────
RADIUS_S  = 6
RADIUS_M  = 10
RADIUS_L  = 14
RADIUS_XL = 20

# ── Animations ───────────────────────────────────────────────────────
ANIM       = ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT)
ANIM_SLOW  = ft.animation.Animation(300, ft.AnimationCurve.EASE_OUT)
_ANIM_BOUNCE = ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT)


def alpha(hex_color: str, opacity: float) -> str:
    a = int(opacity * 255)
    return f"#{a:02X}{hex_color.lstrip('#')}"


_alpha = alpha


# ── Press animation (subtle tactile, not cartoonish) ─────────────────

def jelly_tap(container: ft.Container, page: ft.Page,
              callback=None) -> None:
    """輕微縮放按壓反饋，參考 iOS 的 scale 效果。"""
    import time, threading
    def _run():
        container.animate_scale = ft.animation.Animation(120, ft.AnimationCurve.EASE_IN)
        container.scale = ft.transform.Scale(0.96)
        page.update()
        time.sleep(0.13)
        container.animate_scale = ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT)
        container.scale = ft.transform.Scale(1.0)
        page.update()
        if callback:
            callback()
    threading.Thread(target=_run, daemon=True).start()


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
    page: ft.Page = None,
) -> ft.Container:
    container = ft.Container(
        content=content,
        padding=padding,
        border_radius=radius,
        bgcolor=bg,
        border=ft.border.all(1, border_color),
        shadow=ft.BoxShadow(
            blur_radius=6,
            spread_radius=0,
            color=CARD_SHADOW,
            offset=ft.Offset(0, 1),
        ),
        expand=expand,
        width=width,
        height=height,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
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
    """Hero 用深色漸層卡片（Stripe CTA 風格）"""
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=radius,
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=colors or ["#1E1B4B", "#312E81", "#4338CA"],
        ),
        shadow=ft.BoxShadow(
            blur_radius=24,
            spread_radius=-4,
            color=alpha("#4F46E5", 0.40),
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
    return ft.Text(text.upper(), size=10, weight=ft.FontWeight.W_600, color=TEXT_D)


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
            bgcolor={
                ft.ControlState.DEFAULT:  color if filled else "#FFFFFF",
                ft.ControlState.HOVERED:  alpha(color, 0.85) if filled else alpha(color, 0.06),
                ft.ControlState.DISABLED: "#D1D5DB",
            },
            elevation=0,
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(
                    1, ft.colors.TRANSPARENT if filled else color),
            },
        ),
    )


# ── Micro components ──────────────────────────────────────────────────

def icon_badge(icon, color: str = ACCENT, size: int = 16, bg_size: int = 36) -> ft.Container:
    return ft.Container(
        content=ft.Icon(icon, size=size, color=color),
        width=bg_size, height=bg_size,
        border_radius=bg_size // 2,
        bgcolor=alpha(color, 0.10),
        alignment=ft.alignment.center,
    )


def tag_chip(text: str, color: str = ACCENT) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, color=color, weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=SP3, vertical=SP1),
        border_radius=RADIUS_S,
        bgcolor=alpha(color, 0.08),
        border=ft.border.all(1, alpha(color, 0.20)),
    )


def soft_divider(height: int = 1) -> ft.Container:
    return ft.Container(height=height, bgcolor=CARD_BORDER)
