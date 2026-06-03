"""
研究時間線視圖
顯示論文匯入軌跡、閱讀進度統計、星號論文快速回顧
"""

from collections import defaultdict
from datetime import datetime
import flet as ft
from typing import Optional

from ...database.sqlite_db import SQLiteDB
from ...models import Paper

_STATUS_COLOR = {
    "unread":  ("#6B7280", "#F3F4F6"),   # gray
    "reading": ("#4F46E5", "#EEF2FF"),   # indigo
    "read":    ("#059669", "#F0FDF4"),   # emerald
}
_STATUS_LABEL = {"unread": "未讀", "reading": "閱讀中", "read": "已讀"}


def _chip(text: str, bg: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=9, color=color, weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        border_radius=50,
        bgcolor=bg,
        border=ft.border.all(1, color),
    )


class TimelineView:
    def __init__(self, page: ft.Page):
        self.page = page
        self._sqlite = SQLiteDB()

    def build(self) -> ft.Control:
        papers = self._sqlite.get_all(limit=2000)

        # ── 統計 ──────────────────────────────────────────────────────
        total = len(papers)
        starred = [p for p in papers if p.starred]
        by_status: dict[str, int] = defaultdict(int)
        for p in papers:
            by_status[p.read_status] += 1

        # 按月分組
        by_month: dict[str, list[Paper]] = defaultdict(list)
        for p in papers:
            key = p.created_at.strftime("%Y/%m")
            by_month[key].append(p)
        sorted_months = sorted(by_month.keys())

        return ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("研究時間線", size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("你的文獻累積軌跡、閱讀進度與星號論文",
                            size=11, color=ft.colors.GREY_600),
                ], spacing=2, expand=True),
            ]),
            ft.Divider(height=1, color="#E4E4E7"),
            ft.Column([
                self._build_stats_row(total, by_status, starred),
                self._build_bar_chart(by_month, sorted_months),
                self._build_starred_section(starred),
                self._build_timeline(by_month, sorted_months),
            ], spacing=20, scroll=ft.ScrollMode.AUTO, expand=True),
        ], expand=True, spacing=12)

    # ── 統計卡片列 ────────────────────────────────────────────────────

    def _build_stats_row(self, total: int, by_status: dict,
                         starred: list[Paper]) -> ft.Column:
        """2×3 grid of stat cards (adapts to narrower windows)"""
        def stat_card(icon, label, value, color, bg):
            return ft.Container(
                content=ft.Column([
                    ft.Text(label, size=10, color="#71717A"),
                    ft.Text(str(value), size=24, weight=ft.FontWeight.BOLD,
                            color=color),
                ], spacing=2),
                bgcolor=bg,
                border=ft.border.all(1, color),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                expand=True,
            )

        read_pct = int(by_status.get("read", 0) / total * 100) if total else 0

        row1 = ft.Row([
            stat_card("library_books", "總論文數",   total,
                      "#4F46E5", "#EEF2FF"),
            stat_card("star",          "加星號",
                      len(starred),           "#D97706", "#FEF3C7"),
            stat_card("check_circle",  "已讀",
                      by_status.get("read", 0),    "#059669", "#F0FDF4"),
        ], spacing=10)

        row2 = ft.Row([
            stat_card("menu_book",     "閱讀中",
                      by_status.get("reading", 0), "#4F46E5", "#EEF2FF"),
            stat_card("radio_button_unchecked", "未讀",
                      by_status.get("unread", 0),  "#6B7280", "#F3F4F6"),
            stat_card("percent",       "完讀率",
                      f"{read_pct}%",              "#7C3AED", "#F5F3FF"),
        ], spacing=10)

        return ft.Column([row1, row2], spacing=10)

    # ── 每月匯入長條圖 ────────────────────────────────────────────────

    def _build_bar_chart(self, by_month: dict, sorted_months: list) -> ft.Container:
        if not sorted_months:
            return ft.Container()

        max_count = max(len(by_month[m]) for m in sorted_months) or 1
        bar_max_h = 100

        bars = []
        for month in sorted_months[-18:]:   # 最近 18 個月
            items = by_month[month]
            count = len(items)
            h = max(4, int(count / max_count * bar_max_h))

            read_cnt    = sum(1 for p in items if p.read_status == "read")
            reading_cnt = sum(1 for p in items if p.read_status == "reading")
            unread_cnt  = count - read_cnt - reading_cnt

            # 堆疊顏色
            def seg(n, color):
                if n == 0:
                    return ft.Container(height=0)
                seg_h = max(2, int(n / count * h))
                return ft.Container(height=seg_h, bgcolor=color,
                                    border_radius=ft.border_radius.all(2))

            bar_col = ft.Column(
                [seg(read_cnt, "#059669"),
                 seg(reading_cnt, "#4F46E5"),
                 seg(unread_cnt, "#D1D5DB")],
                spacing=1,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )

            bars.append(ft.Column([
                ft.Text(str(count), size=9, color="#475569",
                        text_align=ft.TextAlign.CENTER),
                ft.Container(
                    content=bar_col,
                    width=28,
                    height=bar_max_h,
                    alignment=ft.alignment.bottom_center,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ),
                ft.Text(month[5:],  # "MM"
                        size=9, color="#71717A",
                        text_align=ft.TextAlign.CENTER),
            ], spacing=3,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER))

        legend = ft.Row([
            ft.Container(width=8, height=8, bgcolor="#059669", border_radius=2),
            ft.Text("已讀", size=10, color="#6B7280"),
            ft.Container(width=8, height=8, bgcolor="#4F46E5", border_radius=2),
            ft.Text("閱讀中", size=10, color="#6B7280"),
            ft.Container(width=8, height=8, bgcolor="#D1D5DB", border_radius=2),
            ft.Text("未讀", size=10, color="#6B7280"),
        ], spacing=6)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("每月匯入", size=13,
                            weight=ft.FontWeight.W_600, color="#18181B"),
                    ft.Container(expand=True),
                    legend,
                ], spacing=8),
                ft.Divider(height=4, color="#E4E4E7"),
                ft.Row(
                    bars, spacing=4,
                    scroll=ft.ScrollMode.AUTO,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
            ], spacing=10),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=12,
            padding=16,
        )

    # ── 加星號論文快速回顧 ────────────────────────────────────────────

    def _build_starred_section(self, starred: list[Paper]) -> ft.Container:
        if not starred:
            return ft.Container(
                content=ft.Row([
                    ft.Icon("star_border", color="#CBD5E1", size=16),
                    ft.Text("尚無加星號的論文。在論文管理頁點擊 ⭐ 星號即可標記重要論文。",
                            size=12, color="#71717A", italic=True),
                ], spacing=8),
                bgcolor="#FFFBEB",
                border=ft.border.all(1, "#FDE68A"),
                border_radius=12,
                padding=16,
            )

        cards = []
        for p in starred[:12]:
            status_color, status_bg = _STATUS_COLOR.get(
                p.read_status, ("#71717A", "#F7F7F8"))
            auth = (p.authors[0] + (" et al." if len(p.authors) > 1 else "")
                    ) if p.authors else "作者不詳"
            cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("star", color="#F59E0B", size=13),
                        ft.Text(p.title, size=12, weight=ft.FontWeight.W_600,
                                color="#18181B", expand=True,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
                    ft.Row([
                        ft.Text(auth, size=10, color="#3F3F46"),
                        ft.Text(str(p.year) if p.year else "", size=10,
                                color="#71717A"),
                        _chip(_STATUS_LABEL.get(p.read_status, "未讀"),
                              status_bg, status_color),
                    ], spacing=6),
                    *([ ft.Text(p.personal_note[:80] + ("…" if len(p.personal_note) > 80 else ""),
                                size=10, color="#7C3AED", italic=True)
                       ] if p.personal_note else []),
                ], spacing=4),
                bgcolor="#FFFBEB",
                border=ft.border.all(1, "#FDE68A"),
                border_radius=10,
                padding=10,
                width=300,
            ))

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("star", color="#D97706", size=16),
                    ft.Text(f"加星號論文（{len(starred)} 篇）", size=13,
                            weight=ft.FontWeight.W_600, color="#D97706"),
                    ft.Container(expand=True),
                    *([ ft.Text("← 左右滑動查看更多", size=10, color="#D97706",
                                italic=True) ] if len(starred) > 3 else []),
                ], spacing=8),
                ft.Divider(height=4, color="#FDE68A"),
                ft.Row(cards, spacing=10, scroll=ft.ScrollMode.AUTO, wrap=False),
            ], spacing=10),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#FDE68A"),
            border_radius=12,
            padding=16,
        )

    # ── 時間線主體 ────────────────────────────────────────────────────

    def _build_timeline(self, by_month: dict, sorted_months: list) -> ft.Container:
        if not sorted_months:
            return ft.Container(
                content=ft.Text("尚無論文資料", size=13, color="#71717A"),
                padding=20,
            )

        rows = []
        for month in reversed(sorted_months):
            papers = sorted(by_month[month],
                            key=lambda p: p.created_at, reverse=True)
            month_items = []
            for p in papers:
                status_color, status_bg = _STATUS_COLOR.get(
                    p.read_status, ("#71717A", "#F7F7F8"))
                auth = (p.authors[0] + (" et al." if len(p.authors) > 1 else "")
                        ) if p.authors else "作者不詳"
                note_row = []
                if p.personal_note:
                    note_row = [ft.Text(
                        "📝 " + p.personal_note[:60] +
                        ("…" if len(p.personal_note) > 60 else ""),
                        size=10, color="#7C3AED", italic=True,
                    )]

                month_items.append(ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("star" if p.starred else "article",
                                    color="#F59E0B" if p.starred else "#71717A",
                                    size=13),
                            ft.Text(p.title, size=12,
                                    weight=ft.FontWeight.W_600, color="#18181B",
                                    expand=True, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            _chip(_STATUS_LABEL.get(p.read_status, "未讀"),
                                  status_bg, status_color),
                        ], spacing=6,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([
                            ft.Text(auth, size=10, color="#3F3F46"),
                            ft.Text(str(p.year) if p.year else "",
                                    size=10, color="#71717A"),
                            *[ft.Container(
                                content=ft.Text(t, size=9, color="#4F46E5"),
                                bgcolor="#EEF2FF", border_radius=50,
                                padding=ft.padding.symmetric(horizontal=6, vertical=1),
                              ) for t in (p.tags or [])[:3]],
                        ], spacing=6),
                        *note_row,
                    ], spacing=3),
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, "#FEF3C7" if p.starred else "#E2E8F0"),
                    border_radius=8,
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                ))

            rows.append(ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Text(month, size=12, weight=ft.FontWeight.W_700,
                                color="#18181B"),
                        ft.Text(f"· {len(papers)} 篇", size=11, color="#71717A"),
                    ], spacing=6),
                    padding=ft.padding.only(bottom=4),
                ),
                ft.Column(month_items, spacing=6),
            ], spacing=6))

        return ft.Container(
            content=ft.Column([
                ft.Text("時間線", size=13, weight=ft.FontWeight.W_600, color="#18181B"),
                ft.Divider(height=4, color="#E4E4E7"),
                ft.Column(rows, spacing=20),
            ], spacing=10),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=12,
            padding=16,
        )
