"""
知識圖譜視圖 v3 — 全面升級
新增：
- X 軸年份標籤修正（無旋轉、步距自適應、固定高度錨點）
- 標籤共現分析（Co-occurrence）Top-5 橫條圖
- 演進趨勢面板（Canvas 折線圖，前 3 大標籤 10 年消長）
- 新興 / 經典主題自動識別（🔥 Emerging / 🏛 Classic 徽章）
- 右側三模式面板：年份分布 ↔ 共現標籤 ↔ 演進趨勢
"""

import math
import flet as ft
import flet.canvas as fc
from pathlib import Path
from typing import Optional
from collections import Counter, defaultdict


# ── 色彩 ──────────────────────────────────────────────────────────────
ACCENT   = "#6366F1"
TEAL     = "#0D9488"
GREEN    = "#059669"
ORANGE   = "#D97706"
ROSE     = "#E11D48"
CARD     = "#FFFFFF"
BG       = "#F1F5F9"
BORDER   = "#E2E8F0"
TEXT_H   = "#1E293B"
TEXT_M   = "#475569"
TEXT_S   = "#94A3B8"
BAR_SEL  = "#F59E0B"
EMERGING_COLOR = "#EA580C"   # orange
CLASSIC_COLOR  = "#3B82F6"   # blue

_TAG_PALETTE = [
    "#6366f1", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
]


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    def parse(c):
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    r1, g1, b1 = parse(c1)
    r2, g2, b2 = parse(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _year_bar_color(year: int, min_y: int, max_y: int) -> str:
    span = max(max_y - min_y, 1)
    t = (year - min_y) / span
    return _lerp_hex("#60a5fa", "#f59e0b", t)


def _section(title: str, icon: str, children: list, color=ACCENT) -> ft.Container:
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(icon, color=color, size=18),
                ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=TEXT_H),
            ], spacing=8),
            *children,
        ], spacing=10),
        padding=16,
        border=ft.border.all(1, BORDER),
        border_radius=12,
        bgcolor=CARD,
    )


class GraphView:
    def __init__(self, page: ft.Page):
        self.page = page
        self._papers = []
        self._selected_tag: Optional[str] = None
        self._right_mode: str = "year"   # "year" | "cooccur" | "trend"

        # Chart refs
        self._tag_bars: list[ft.Container] = []
        self._right_content: Optional[ft.Column] = None
        self._right_header: Optional[ft.Column] = None
        self._mode_btn_containers: dict[str, ft.Container] = {}

        # Precomputed
        self._cooccur: dict[str, Counter] = {}
        self._tag_year: dict[str, Counter] = {}
        self._tag_counts: Counter = Counter()
        self._tag_class: dict[str, str] = {}   # "emerging" | "classic" | "normal"
        self._tag_stats: dict[str, dict] = {}

    # ── Build ──────────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        try:
            return self._build_inner()
        except Exception as ex:
            import traceback
            return ft.Column([
                ft.Text("知識圖譜載入失敗", color=ROSE, size=16),
                ft.Text(str(ex), color=ROSE, size=12),
                ft.Text(traceback.format_exc(), size=10, color=TEXT_S, selectable=True),
            ], scroll=ft.ScrollMode.AUTO, expand=True)

    def _build_inner(self) -> ft.Column:
        from ...services.knowledge_graph import KnowledgeGraphService
        from ...services.deduplicator import Deduplicator
        from ...services.exporter import PaperExporter
        from ...database.sqlite_db import SQLiteDB

        self.kg_service = KnowledgeGraphService()
        self.dedup = Deduplicator()
        self.exporter = PaperExporter()
        self.db = SQLiteDB()

        self._papers = list(self.db.get_all(limit=5000))
        self._precompute()

        self.bibtex_picker = ft.FilePicker()
        self.bibtex_picker.on_result = self._on_bibtex_save
        self.ris_picker = ft.FilePicker()
        self.ris_picker.on_result = self._on_ris_save
        self.page.overlay.extend([self.bibtex_picker, self.ris_picker])

        self.status = ft.Text("", size=12, color=TEXT_M)
        self.progress = ft.ProgressRing(visible=False, width=20, height=20)

        stats = self.kg_service.get_graph_stats()

        return ft.Column([
            ft.Text("知識圖譜與工具", size=26, weight=ft.FontWeight.BOLD, color=TEXT_H),
            ft.Text("視覺化論文關聯，分析標籤分布，匯出引用格式", size=13, color=TEXT_M),
            ft.Divider(height=4, color=BORDER),
            self._build_stats(stats),
            self._build_year_trend(stats),
            self._build_tag_analysis(),
            self._build_graph_section(),
            self._build_export_section(),
            self._build_dedup_section(),
            ft.Row([self.progress, self.status], spacing=8),
        ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)

    # ── Precompute ────────────────────────────────────────────────────

    def _precompute(self):
        """計算共現矩陣、標籤年份分布、新興/經典分類。"""
        papers = self._papers

        for p in papers:
            for t in (p.tags or []):
                self._tag_counts[t] += 1
                if p.year:
                    self._tag_year.setdefault(t, Counter())[p.year] += 1

        # Co-occurrence
        for p in papers:
            tags = list(set(p.tags or []))
            for t in tags:
                if t not in self._cooccur:
                    self._cooccur[t] = Counter()
                for other in tags:
                    if other != t:
                        self._cooccur[t][other] += 1

        # Global year range
        all_years = [p.year for p in papers if p.year]
        if not all_years:
            return
        global_min_y = min(all_years)
        global_max_y = max(all_years)
        recent_thr = global_max_y - 2

        for tag, year_dist in self._tag_year.items():
            total = sum(year_dist.values())
            if total < 2:
                self._tag_class[tag] = "normal"
                continue

            mean_y = sum(y * c for y, c in year_dist.items()) / total
            recent = sum(c for y, c in year_dist.items() if y >= recent_thr)
            recent_ratio = recent / total

            last2 = sum(year_dist.get(y, 0) for y in [global_max_y, global_max_y - 1])
            prev2 = sum(year_dist.get(y, 0) for y in [global_max_y - 2, global_max_y - 3])
            growth = (last2 - prev2) / max(prev2, 1)

            if (recent_ratio >= 0.45 and total >= 3) or growth >= 0.5:
                cls = "emerging"
            elif mean_y <= (global_min_y + 5) and recent > 0 and total >= 3:
                cls = "classic"
            else:
                cls = "normal"

            self._tag_class[tag] = cls
            self._tag_stats[tag] = {
                "mean_year": round(mean_y, 1),
                "recent_pct": round(recent_ratio * 100, 1),
                "growth_pct": round(growth * 100, 1),
                "total": total,
            }

    # ── 統計卡片 ──────────────────────────────────────────────────────

    def _build_stats(self, stats: dict) -> ft.Row:
        unique_tags = len({t for p in self._papers for t in (p.tags or [])})
        emerging_n = sum(1 for v in self._tag_class.values() if v == "emerging")
        classic_n  = sum(1 for v in self._tag_class.values() if v == "classic")

        def card(label, value, color, bg):
            return ft.Container(
                content=ft.Column([
                    ft.Text(str(value), size=26, weight=ft.FontWeight.BOLD, color=color),
                    ft.Text(label, size=10, color=TEXT_S),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
                border=ft.border.all(1, BORDER),
                border_radius=10,
                bgcolor=bg,
                width=130,
            )

        return ft.Row([
            card("論文總數",   stats.get("total_papers", 0), ACCENT,  "#EEF2FF"),
            card("有引用資料", stats.get("with_citations", 0), TEAL,   "#F0FDFA"),
            card("唯一標籤數", unique_tags,                   ORANGE,  "#FFFBEB"),
            card("🔥 新興主題", emerging_n,                   EMERGING_COLOR, "#FFF7ED"),
            card("🏛 經典主題", classic_n,                    CLASSIC_COLOR,  "#EFF6FF"),
        ], spacing=10, wrap=True)

    # ── 年份趨勢圖（修正版：無旋轉、步距跳躍、固定錨點）────────────

    def _build_year_trend(self, stats: dict) -> ft.Container:
        year_dist = stats.get("year_distribution", {})
        if not year_dist:
            return ft.Container(
                content=ft.Text("尚無年份資料", color=TEXT_S, italic=True),
                padding=12,
            )

        sorted_years = sorted(year_dist.keys())
        n = len(sorted_years)
        max_count = max(year_dist.values(), default=1)
        max_h = 100
        min_y, max_y_val = sorted_years[0], sorted_years[-1]

        # ★ 最多顯示 10 個標籤，避免密集
        step = max(1, math.ceil(n / 10))

        bars = []
        for i, year in enumerate(sorted_years):
            count = year_dist[year]
            bar_h = max(4, int(count / max_count * max_h))
            bar_color = _year_bar_color(year, min_y, max_y_val)
            show_label = (i % step == 0) or (i == n - 1)

            bars.append(ft.Column([
                # 數量標籤
                ft.Text(str(count), size=9, color=TEXT_M),
                # 柱體
                ft.Container(
                    width=28, height=bar_h, bgcolor=bar_color,
                    border_radius=ft.border_radius.only(top_left=4, top_right=4),
                    tooltip=f"{year}：{count} 篇",
                ),
                # ★ 固定高度標籤區（不旋轉 → 無錨點偏移）
                ft.Container(
                    width=28, height=22,
                    content=ft.Text(
                        str(year) if show_label else "",
                        size=8, color=TEXT_S,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    alignment=ft.alignment.top_center,
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2))

        return _section("論文發表年份趨勢", "bar_chart", [
            ft.Container(
                content=ft.Row(bars, spacing=3, scroll=ft.ScrollMode.AUTO),
                padding=ft.padding.only(top=8, bottom=4),
            ),
        ])

    # ── 標籤分析（三模式右面板）──────────────────────────────────────

    def _build_tag_analysis(self) -> ft.Container:
        tag_counter: Counter = Counter()
        for p in self._papers:
            for t in (p.tags or []):
                tag_counter[t] += 1

        if not tag_counter:
            return _section("標籤分析", "label", [
                ft.Text("尚無標籤資料，請先匯入並自動標記論文", color=TEXT_S, italic=True),
            ], color=TEAL)

        top_tags = tag_counter.most_common(25)
        max_count = top_tags[0][1]
        total_count = sum(c for _, c in top_tags)

        # ── 右側面板的模式切換按鈕 ───────────────────────────────────
        def _make_mode_btn(label: str, mode: str) -> ft.Container:
            def on_click(e, m=mode):
                self._set_right_mode(m)

            c = ft.Container(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.W_600 if mode == self._right_mode else ft.FontWeight.NORMAL),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                border_radius=6,
                bgcolor=ACCENT if mode == self._right_mode else BG,
                border=ft.border.all(1, ACCENT if mode == self._right_mode else BORDER),
                on_click=on_click,
                ink=True,
            )
            self._mode_btn_containers[mode] = c
            return c

        mode_row = ft.Row([
            _make_mode_btn("📅 年份分布", "year"),
            _make_mode_btn("🔗 共現標籤", "cooccur"),
            _make_mode_btn("📈 演進趨勢", "trend"),
        ], spacing=6)

        # ── 右側面板 header（顯示選中標籤的統計）────────────────────
        self._right_header = ft.Column(
            [ft.Text("← 點擊左側標籤開始分析", size=12, color=TEXT_S, italic=True)],
            spacing=4,
        )

        # ── 右側面板 content ─────────────────────────────────────────
        self._right_content = ft.Column(
            [ft.Text("請先選擇左側標籤，或切至「演進趨勢」查看整體", size=11, color=TEXT_S, italic=True)],
            spacing=6,
        )
        if self._right_mode == "trend":
            self._right_content.controls = [self._build_trend_panel()]

        self._right_panel = ft.Column([
            mode_row,
            ft.Divider(height=1, color=BORDER),
            self._right_header,
            ft.Container(
                content=self._right_content,
                border=ft.border.all(1, BORDER),
                border_radius=8,
                padding=10,
                bgcolor=BG,
            ),
        ], spacing=8)

        # ── 左側標籤條 ───────────────────────────────────────────────
        bar_w_max = 160

        def make_bar(tag, count, idx):
            bar_color = _TAG_PALETTE[idx % len(_TAG_PALETTE)]
            pct = count / total_count * 100 if total_count else 0
            cls = self._tag_class.get(tag, "normal")
            badge = "🔥" if cls == "emerging" else ("🏛" if cls == "classic" else "")

            def on_click(e, t=tag):
                self._on_tag_click(t, self._tag_year.get(t, {}))

            bar = ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Row([
                            ft.Text(badge, size=10) if badge else ft.Container(width=14),
                            ft.Text(tag, size=11, color=TEXT_M,
                                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                        ], spacing=2),
                        width=136,
                    ),
                    ft.Container(
                        width=int(count / max_count * bar_w_max),
                        height=16, bgcolor=bar_color, border_radius=3,
                    ),
                    ft.Text(f"{count} ({pct:.1f}%)", size=11, color=TEXT_M),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(vertical=4, horizontal=6),
                border_radius=6,
                on_click=on_click,
                tooltip=f"點擊分析「{tag}」{' (' + cls + ')' if cls != 'normal' else ''}",
                ink=True,
            )
            return bar

        self._tag_bars = [make_bar(tag, count, i) for i, (tag, count) in enumerate(top_tags)]
        bar_col = ft.Column(self._tag_bars, spacing=2)

        # ── 圖例說明 ─────────────────────────────────────────────────
        legend_row = ft.Row([
            ft.Text("🔥 新興主題", size=10, color=EMERGING_COLOR),
            ft.Text("｜", size=10, color=TEXT_S),
            ft.Text("🏛 經典主題", size=10, color=CLASSIC_COLOR),
            ft.Text("｜ 點擊標籤查看詳細分析", size=10, color=TEXT_S),
        ], spacing=4)

        return _section("標籤分析", "label", [
            legend_row,
            ft.Row([
                ft.Container(
                    content=ft.Column([bar_col], scroll=ft.ScrollMode.AUTO),
                    expand=2,
                    border=ft.border.all(1, BORDER),
                    border_radius=8,
                    padding=10,
                    bgcolor=BG,
                ),
                ft.Container(
                    content=self._right_panel,
                    expand=3,
                    border=ft.border.all(1, BORDER),
                    border_radius=8,
                    padding=12,
                    bgcolor=CARD,
                ),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
        ], color=TEAL)

    # ── 右側面板：切換模式 ────────────────────────────────────────────

    def _set_right_mode(self, mode: str):
        self._right_mode = mode

        # Update button styles
        for m, container in self._mode_btn_containers.items():
            is_active = (m == mode)
            container.bgcolor = ACCENT if is_active else BG
            container.border = ft.border.all(1, ACCENT if is_active else BORDER)
            lbl = container.content
            lbl.weight = ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL

        # Refresh right panel content
        self._refresh_right_panel()
        self.page.update()

    def _refresh_right_panel(self):
        if self._right_mode == "trend":
            self._right_content.controls = [self._build_trend_panel()]
        elif self._selected_tag:
            year_dist = self._tag_year.get(self._selected_tag, {})
            if self._right_mode == "year":
                self._right_content.controls = [self._build_year_dist_panel(self._selected_tag, year_dist)]
            else:
                self._right_content.controls = [self._build_cooccur_panel(self._selected_tag)]
        else:
            self._right_content.controls = [
                ft.Text("請先選擇左側標籤", size=11, color=TEXT_S, italic=True)
            ]

    # ── 點擊標籤 ─────────────────────────────────────────────────────

    def _on_tag_click(self, tag: str, year_dist: Counter):
        self._selected_tag = tag

        # Update header
        stats = self._tag_stats.get(tag, {})
        cls = self._tag_class.get(tag, "normal")
        badge = "🔥 新興主題" if cls == "emerging" else ("🏛 經典主題" if cls == "classic" else "")
        badge_color = EMERGING_COLOR if cls == "emerging" else (CLASSIC_COLOR if cls == "classic" else TEXT_M)

        header_rows = [
            ft.Row([
                ft.Text(f"📌 {tag}", size=13, weight=ft.FontWeight.W_600, color=TEXT_H),
                ft.Text(badge, size=11, color=badge_color,
                        weight=ft.FontWeight.W_600) if badge else ft.Container(),
            ], spacing=8),
        ]
        if stats:
            header_rows.append(
                ft.Row([
                    ft.Text(f"均值年份 {stats['mean_year']}", size=10, color=TEXT_S),
                    ft.Text("｜", size=10, color=BORDER),
                    ft.Text(f"近年佔比 {stats['recent_pct']}%", size=10, color=TEXT_S),
                    ft.Text("｜", size=10, color=BORDER),
                    ft.Text(f"成長率 {'+' if stats['growth_pct'] >= 0 else ''}{stats['growth_pct']}%",
                            size=10,
                            color=GREEN if stats['growth_pct'] > 0 else ROSE),
                ], spacing=4, wrap=True)
            )
        self._right_header.controls = header_rows

        # Update content
        self._refresh_right_panel()
        self.page.update()

    # ── 右側面板：年份分布 ────────────────────────────────────────────

    def _build_year_dist_panel(self, tag: str, year_dist: Counter) -> ft.Control:
        if not year_dist:
            return ft.Text(f"「{tag}」沒有年份資料", size=12, color=TEXT_S, italic=True)

        min_year = min(year_dist.keys())
        max_year = max(year_dist.keys())
        full_dist = {y: year_dist.get(y, 0) for y in range(min_year, max_year + 1)}

        max_c = max(full_dist.values(), default=1)
        max_h = 75
        n = len(full_dist)
        step = max(1, math.ceil(n / 8))

        bars = []
        for i, year in enumerate(sorted(full_dist.keys())):
            cnt = full_dist[year]
            h = max(2, int(cnt / max_c * max_h)) if cnt > 0 else 2
            bar_color = BAR_SEL if cnt > 0 else "#E2E8F0"
            show_label = (i % step == 0) or (i == n - 1)
            bars.append(ft.Column([
                ft.Text(str(cnt) if cnt > 0 else "", size=9, color=TEXT_M),
                ft.Container(width=22, height=h, bgcolor=bar_color,
                             border_radius=ft.border_radius.only(top_left=3, top_right=3)),
                ft.Container(
                    width=22, height=20,
                    content=ft.Text(str(year) if show_label else "", size=8, color=TEXT_S,
                                    text_align=ft.TextAlign.CENTER),
                    alignment=ft.alignment.top_center,
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2))

        total = sum(year_dist.values())
        span = max_year - min_year + 1
        return ft.Column([
            ft.Text(f"「{tag}」年份分布（共 {total} 篇，{min_year}–{max_year}）",
                    size=12, weight=ft.FontWeight.W_600, color=TEXT_H),
            ft.Container(
                content=ft.Row(bars, spacing=3, scroll=ft.ScrollMode.AUTO),
                padding=ft.padding.only(top=6),
            ),
        ], spacing=6)

    # ── 右側面板：共現標籤 ────────────────────────────────────────────

    def _build_cooccur_panel(self, tag: str) -> ft.Control:
        co = self._cooccur.get(tag, Counter())
        if not co:
            return ft.Text(f"「{tag}」沒有共現標籤資料", size=12, color=TEXT_S, italic=True)

        papers_with_tag = sum(1 for p in self._papers if tag in (p.tags or []))
        top5 = co.most_common(5)
        max_co = top5[0][1] if top5 else 1
        bar_w_max = 140

        rows = []
        for i, (other_tag, count) in enumerate(top5):
            pct = count / papers_with_tag * 100 if papers_with_tag else 0
            bar_color = _TAG_PALETTE[i % len(_TAG_PALETTE)]
            rows.append(ft.Row([
                ft.Container(
                    content=ft.Text(other_tag, size=11, color=TEXT_M,
                                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                    width=110,
                ),
                ft.Container(
                    width=int(count / max_co * bar_w_max),
                    height=14, bgcolor=bar_color, border_radius=3,
                ),
                ft.Text(f"{count} ({pct:.0f}%)", size=10, color=TEXT_S),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        return ft.Column([
            ft.Text(f"「{tag}」最常共現的標籤 Top-5",
                    size=12, weight=ft.FontWeight.W_600, color=TEXT_H),
            ft.Text(f"（基於 {papers_with_tag} 篇含此標籤的論文）",
                    size=10, color=TEXT_S),
            ft.Column(rows, spacing=6),
        ], spacing=8)

    # ── 右側面板：演進趨勢（Canvas 折線圖）───────────────────────────

    def _build_trend_panel(self) -> ft.Control:
        if not self._tag_year:
            return ft.Text("尚無年份資料", size=12, color=TEXT_S, italic=True)

        top3 = self._tag_counts.most_common(3)
        if not top3:
            return ft.Text("尚無標籤資料", size=12, color=TEXT_S, italic=True)

        line_colors = ["#6366f1", "#f28e2b", "#e15759"]

        # 近 10 年範圍
        all_ys: set[int] = set()
        for tag, _ in top3:
            all_ys.update(self._tag_year.get(tag, {}).keys())
        if not all_ys:
            return ft.Text("無年份資料", size=12, color=TEXT_S)

        max_yr = max(all_ys)
        min_yr_range = max(max_yr - 9, min(all_ys))
        years = list(range(min_yr_range, max_yr + 1))
        n_years = len(years)

        # Max count across all tags + years
        all_counts = [self._tag_year.get(t, {}).get(y, 0) for t, _ in top3 for y in years]
        max_cnt = max(all_counts) if all_counts else 1

        # Canvas dimensions
        CW, CH = 340, 110
        pad_l, pad_r, pad_t, pad_b = 8, 8, 6, 20

        def x_of(i: int) -> float:
            span = max(n_years - 1, 1)
            return pad_l + (CW - pad_l - pad_r) * i / span

        def y_of(cnt: int) -> float:
            h = CH - pad_t - pad_b
            return pad_t + h * (1 - cnt / max_cnt)

        shapes = []

        # Grid lines (horizontal)
        for frac in [0.25, 0.5, 0.75, 1.0]:
            gy = pad_t + (CH - pad_t - pad_b) * (1 - frac)
            shapes.append(fc.Line(
                x1=pad_l, y1=gy, x2=CW - pad_r, y2=gy,
                paint=ft.Paint(color="#E2E8F020", stroke_width=1),
            ))

        # Trend lines + dots per tag
        for (tag, _), color in zip(top3, line_colors):
            dist = self._tag_year.get(tag, {})
            pts = [(x_of(i), y_of(dist.get(y, 0))) for i, y in enumerate(years)]

            # Polyline
            for k in range(len(pts) - 1):
                shapes.append(fc.Line(
                    x1=pts[k][0], y1=pts[k][1],
                    x2=pts[k + 1][0], y2=pts[k + 1][1],
                    paint=ft.Paint(color=color, stroke_width=2.0),
                ))

            # Dots
            for i, (px, py) in enumerate(pts):
                cnt = dist.get(years[i], 0)
                if cnt > 0:
                    shapes.append(fc.Circle(
                        px, py, 3.5,
                        paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL),
                    ))

        canvas = fc.Canvas(shapes, width=CW, height=CH, expand=True)

        # X-axis year labels (step to avoid crowding)
        step = max(1, math.ceil(n_years / 8))
        x_labels = ft.Row(
            [
                ft.Container(
                    content=ft.Text(str(years[i]) if i % step == 0 or i == n_years - 1 else "",
                                    size=8, color=TEXT_S, text_align=ft.TextAlign.CENTER),
                    width=(CW - pad_l - pad_r) / max(n_years - 1, 1) if n_years > 1 else CW,
                    alignment=ft.alignment.center,
                )
                for i in range(n_years)
            ],
            spacing=0,
        )

        # Legend
        legend = ft.Row([
            ft.Row([
                ft.Container(
                    width=18, height=3, bgcolor=color,
                    border_radius=2,
                ),
                ft.Text(tag[:18] + ("…" if len(tag) > 18 else ""), size=10, color=TEXT_M),
            ], spacing=5)
            for (tag, _), color in zip(top3, line_colors)
        ], spacing=12, wrap=True)

        # Emerging / classic annotation
        annotations = []
        for tag, _ in top3:
            cls = self._tag_class.get(tag, "normal")
            st = self._tag_stats.get(tag, {})
            if cls == "emerging":
                annotations.append(
                    ft.Text(f"🔥 {tag[:16]}：近年佔比 {st.get('recent_pct', '?')}%，成長 +{st.get('growth_pct', '?')}%",
                            size=10, color=EMERGING_COLOR)
                )
            elif cls == "classic":
                annotations.append(
                    ft.Text(f"🏛 {tag[:16]}：均值年份 {st.get('mean_year', '?')}，歷史基石",
                            size=10, color=CLASSIC_COLOR)
                )

        anno_col = ft.Column(annotations, spacing=3) if annotations else ft.Container()

        return ft.Column([
            ft.Text("前三大標籤演進趨勢（近 10 年）",
                    size=12, weight=ft.FontWeight.W_600, color=TEXT_H),
            ft.Stack([
                ft.Container(
                    width=CW, height=CH,
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, BORDER),
                    border_radius=6,
                ),
                canvas,
            ]),
            ft.Container(content=x_labels, padding=ft.padding.only(left=pad_l)),
            legend,
            anno_col,
        ], spacing=6)

    # ── 知識圖譜生成 ──────────────────────────────────────────────────

    def _build_graph_section(self) -> ft.Container:
        self._graph_paper_selected: dict[int, ft.Checkbox] = {}
        self._all_graph_papers: dict[int, object] = {p.id: p for p in self._papers}

        paper_checkboxes = []
        for p in self._papers[:500]:
            label = f"[{p.id}] {p.title[:55]}{'…' if len(p.title) > 55 else ''} ({p.year or '?'})"
            if p.tags:
                label += f"  [{', '.join(p.tags[:2])}]"
            cb = ft.Checkbox(label=label, value=True, label_style=ft.TextStyle(size=11))
            self._graph_paper_selected[p.id] = cb
            paper_checkboxes.append(cb)

        self._graph_papers_list = ft.Column(
            controls=paper_checkboxes,
            scroll=ft.ScrollMode.AUTO,
            height=180,
            spacing=1,
        )
        self._graph_selected_count = ft.Text(
            f"已選 {len(self._papers)} 篇", size=11, color=ft.colors.BLUE_700
        )
        self._graph_search = ft.TextField(
            label="篩選論文", expand=True, dense=True,
            on_change=self._on_graph_search,
        )

        def _sel_all(e):
            for cb in self._graph_paper_selected.values():
                if cb.visible:
                    cb.value = True
            self._update_graph_count()
            self.page.update()

        def _desel_all(e):
            for cb in self._graph_paper_selected.values():
                cb.value = False
            self._update_graph_count()
            self.page.update()

        self.graph_type = ft.RadioGroup(
            content=ft.Row([
                ft.Radio(value="tag",      label="共享標籤 ★"),
                ft.Radio(value="concept",  label="共享概念"),
                ft.Radio(value="citation", label="引用關係"),
            ]),
            value="tag",
        )
        self.min_shared_dd = ft.Dropdown(
            label="最少共享數", value="1", width=110,
            options=[ft.dropdown.Option(str(n), f"≥{n}") for n in [1, 2, 3, 5]],
        )
        self.color_by_dd = ft.Dropdown(
            label="節點顏色", value="tag", width=140,
            options=[
                ft.dropdown.Option("tag",       "依標籤"),
                ft.dropdown.Option("year",      "依年份"),
                ft.dropdown.Option("citations", "依引用數"),
            ],
        )
        self.layout_dd = ft.Dropdown(
            label="佈局方式", value="physics", width=160,
            options=[
                ft.dropdown.Option("physics",      "力導向（推薦）"),
                ft.dropdown.Option("hierarchical", "層次佈局"),
            ],
        )

        gen_btn = ft.ElevatedButton(
            "在瀏覽器開啟互動圖譜",
            icon="open_in_browser",
            on_click=self._on_gen_graph,
            style=ft.ButtonStyle(bgcolor=ACCENT, color="#FFFFFF"),
        )

        return _section("知識圖譜視覺化（互動）", "bubble_chart", [
            ft.Text("勾選要分析的論文，點擊節點可高亮其關聯論文，支援拖拽 / 縮放",
                    size=11, color=TEXT_S),
            ft.Row([
                self._graph_search,
                ft.TextButton("全選", on_click=_sel_all),
                ft.TextButton("全不選", on_click=_desel_all),
                self._graph_selected_count,
            ], spacing=8),
            ft.Container(
                content=self._graph_papers_list,
                border=ft.border.all(1, BORDER),
                border_radius=6,
                padding=8,
                bgcolor=BG,
            ),
            ft.Row([self.graph_type, self.min_shared_dd], spacing=10, wrap=True),
            ft.Row([self.color_by_dd, self.layout_dd, gen_btn], spacing=10, wrap=True),
            ft.Text(
                "節點大小∝度中心性　顏色可選標籤/年份/引用數　邊=共享關聯\n"
                "互動操作：滾輪縮放 · 拖拽節點 · 單擊高亮鄰居 · 圖例點擊閃爍 · Esc 重置",
                size=10, color=TEXT_S,
            ),
        ])

    def _on_graph_search(self, e):
        keyword = (e.control.value or "").lower()
        for pid, cb in self._graph_paper_selected.items():
            p = self._all_graph_papers.get(pid)
            if p:
                cb.visible = not keyword or keyword in p.title.lower()
        self.page.update()

    def _update_graph_count(self):
        n = sum(1 for cb in self._graph_paper_selected.values() if cb.value)
        self._graph_selected_count.value = f"已選 {n} 篇"

    def _on_gen_graph(self, e):
        selected_ids = [pid for pid, cb in self._graph_paper_selected.items() if cb.value]
        if not selected_ids:
            self.status.value = "請至少勾選一篇論文"
            self.page.update()
            return

        self._set_busy(f"生成圖譜（{len(selected_ids)} 篇）…")
        try:
            html_path = self.kg_service.build_interactive_graph(
                graph_type=self.graph_type.value,
                min_shared=int(self.min_shared_dd.value or "1"),
                paper_ids=selected_ids,
                color_by=self.color_by_dd.value or "tag",
                layout=self.layout_dd.value or "physics",
            )
            if not html_path:
                self.status.value = "沒有足夠資料建立圖譜（請確認論文有標籤）"
                return
            import webbrowser
            webbrowser.open(f"file:///{html_path}")
            self.status.value = f"已在瀏覽器開啟互動圖譜（{len(selected_ids)} 篇論文）"
        except Exception as ex:
            import traceback
            self.status.value = f"圖譜生成失敗：{ex}"
            traceback.print_exc()
        finally:
            self._set_idle()

    # ── 匯出 ──────────────────────────────────────────────────────────

    def _build_export_section(self) -> ft.Container:
        return _section("匯出引用格式", "download", [
            ft.Text("匯出為 Zotero、Mendeley、EndNote 可匯入的格式",
                    size=11, color=TEXT_S),
            ft.Row([
                ft.ElevatedButton(
                    "匯出 BibTeX (.bib)", icon="code",
                    on_click=lambda e: self.bibtex_picker.save_file(
                        allowed_extensions=["bib"], file_name="papers.bib",
                        dialog_title="儲存 BibTeX 檔案",
                    ),
                    style=ft.ButtonStyle(bgcolor="#166534", color="#FFFFFF"),
                ),
                ft.ElevatedButton(
                    "匯出 RIS (.ris)", icon="code",
                    on_click=lambda e: self.ris_picker.save_file(
                        allowed_extensions=["ris"], file_name="papers.ris",
                        dialog_title="儲存 RIS 檔案",
                    ),
                    style=ft.ButtonStyle(bgcolor="#0F766E", color="#FFFFFF"),
                ),
            ], spacing=12),
        ], color=GREEN)

    def _on_bibtex_save(self, e):
        if not e.path:
            return
        self._set_busy("匯出 BibTeX 中…")
        try:
            papers = self.db.get_all(limit=5000)
            self.exporter.save_bibtex(papers, e.path)
            self.status.value = f"BibTeX 已儲存：{Path(e.path).name}（{len(papers)} 篇）"
        except Exception as ex:
            self.status.value = f"匯出失敗：{ex}"
        finally:
            self._set_idle()

    def _on_ris_save(self, e):
        if not e.path:
            return
        self._set_busy("匯出 RIS 中…")
        try:
            papers = self.db.get_all(limit=5000)
            self.exporter.save_ris(papers, e.path)
            self.status.value = f"RIS 已儲存：{Path(e.path).name}（{len(papers)} 篇）"
        except Exception as ex:
            self.status.value = f"匯出失敗：{ex}"
        finally:
            self._set_idle()

    # ── 去重 ──────────────────────────────────────────────────────────

    def _build_dedup_section(self) -> ft.Container:
        self._dedup_threshold = 0.85
        self._threshold_text = ft.Text(f"相似度門檻：{self._dedup_threshold:.0%}", size=12, color=TEXT_M)
        self.dedup_results = ft.Column(spacing=8)

        def lower(e):
            self._dedup_threshold = max(0.70, self._dedup_threshold - 0.05)
            self._threshold_text.value = f"相似度門檻：{self._dedup_threshold:.0%}"
            self.page.update()

        def higher(e):
            self._dedup_threshold = min(0.99, self._dedup_threshold + 0.05)
            self._threshold_text.value = f"相似度門檻：{self._dedup_threshold:.0%}"
            self.page.update()

        return _section("論文去重", "content_copy", [
            ft.Text("偵測標題相似度超過門檻的論文，合併或刪除重複項",
                    size=11, color=TEXT_S),
            ft.Row([
                ft.IconButton(icon="remove", on_click=lower, tooltip="降低門檻"),
                self._threshold_text,
                ft.IconButton(icon="add", on_click=higher, tooltip="提高門檻"),
                ft.ElevatedButton(
                    "掃描重複論文", icon="find_replace",
                    on_click=self._on_scan_dedup,
                    style=ft.ButtonStyle(bgcolor=ORANGE, color="#FFFFFF"),
                ),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.dedup_results,
        ], color=ORANGE)

    def _on_scan_dedup(self, e):
        self._set_busy("掃描重複論文中…")
        self.dedup_results.controls.clear()
        try:
            groups = self.dedup.find_duplicates(threshold=self._dedup_threshold)
            if not groups:
                self.dedup_results.controls.append(
                    ft.Text("✓ 未發現重複論文", color=GREEN, size=13)
                )
            else:
                self.status.value = f"發現 {len(groups)} 組重複論文"
                for i, group in enumerate(groups, 1):
                    self.dedup_results.controls.append(self._build_dedup_group(i, group))
        except Exception as ex:
            self.status.value = f"掃描失敗：{ex}"
        finally:
            self._set_idle()

    def _build_dedup_group(self, idx: int, group: list) -> ft.Container:
        radio_group = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(
                    value=str(p.id),
                    label=f"[{p.id}] {p.title[:60]}{'…' if len(p.title) > 60 else ''}"
                          + (f" ({p.year})" if p.year else ""),
                ) for p in group
            ], spacing=4),
            value=str(group[0].id),
        )

        def _on_merge(e, _group=group, _rg=radio_group):
            keep_id = int(_rg.value)
            delete_ids = [p.id for p in _group if p.id != keep_id]
            deleted = self.dedup.merge(keep_id, delete_ids)
            self.status.value = f"已合併：保留 [{keep_id}]，刪除 {deleted} 篇"
            self.dedup_results.controls = [
                c for c in self.dedup_results.controls
                if getattr(c, "_group_idx", None) != idx
            ]
            self.page.update()

        card = ft.Container(
            content=ft.Column([
                ft.Text(f"重複組 #{idx}（{len(group)} 篇）",
                        size=12, weight=ft.FontWeight.BOLD, color="#92400E"),
                radio_group,
                ft.Text("選擇要保留的論文，其餘將被刪除（標籤合併）",
                        size=10, color=TEXT_S, italic=True),
                ft.ElevatedButton(
                    "合併（保留選取）", icon="merge_type",
                    on_click=_on_merge,
                    style=ft.ButtonStyle(bgcolor=ORANGE, color="#FFFFFF"),
                ),
            ], spacing=6),
            padding=12,
            bgcolor="#FFFBEB",
            border=ft.border.all(1, "#FDE68A"),
            border_radius=8,
        )
        card._group_idx = idx
        return card

    # ── Helpers ───────────────────────────────────────────────────────

    def _set_busy(self, msg: str):
        self.progress.visible = True
        self.status.value = msg
        self.page.update()

    def _set_idle(self):
        self.progress.visible = False
        self.page.update()
