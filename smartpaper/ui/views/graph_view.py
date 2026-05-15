"""
知識圖譜視圖（重新設計版）
- 年份趨勢圖
- 標籤分布圖（可互動：點擊標籤看其年份分布）
- 知識圖譜生成（移除 GestureDetector）
- BibTeX / RIS 匯出
- 論文去重
"""

import flet as ft
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
BAR_COL  = "#6366F1"
BAR_SEL  = "#F59E0B"   # 選中的 bar 顏色


def _section(title: str, icon: str, children: list, color=ACCENT) -> ft.Container:
    """統一 section 卡片樣式"""
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
        # chart refs
        self._tag_bars: list[ft.Container] = []
        self._tag_year_chart: Optional[ft.Column] = None
        self._selected_tag_label: Optional[ft.Text] = None

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

        # File pickers
        self.bibtex_picker = ft.FilePicker()
        self.bibtex_picker.on_result = self._on_bibtex_save
        self.ris_picker = ft.FilePicker()
        self.ris_picker.on_result = self._on_ris_save
        self.page.overlay.extend([self.bibtex_picker, self.ris_picker])

        self.status = ft.Text("", size=12, color=TEXT_M)
        self.progress = ft.ProgressRing(visible=False, width=20, height=20)

        stats = self.kg_service.get_graph_stats()

        return ft.Column([
            # 標題
            ft.Text("知識圖譜與工具", size=26, weight=ft.FontWeight.BOLD, color=TEXT_H),
            ft.Text("視覺化論文關聯，分析標籤分布，匯出引用格式", size=13, color=TEXT_M),
            ft.Divider(height=4, color=BORDER),

            # 統計卡片
            self._build_stats(stats),

            # 年份趨勢
            self._build_year_trend(stats),

            # 標籤分布 + 標籤年份互動
            self._build_tag_analysis(),

            # 知識圖譜
            self._build_graph_section(),

            # 匯出
            self._build_export_section(),

            # 去重
            self._build_dedup_section(),

            ft.Row([self.progress, self.status], spacing=8),
        ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)

    # ── 統計卡片 ──────────────────────────────────────────────────────

    def _build_stats(self, stats: dict) -> ft.Row:
        def card(label, value, color, bg):
            return ft.Container(
                content=ft.Column([
                    ft.Text(str(value), size=28, weight=ft.FontWeight.BOLD, color=color),
                    ft.Text(label, size=11, color=TEXT_S),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                padding=ft.padding.symmetric(horizontal=20, vertical=14),
                border=ft.border.all(1, BORDER),
                border_radius=10,
                bgcolor=bg,
                width=130,
            )

        return ft.Row([
            card("論文總數", stats.get("total_papers", 0), ACCENT, "#EEF2FF"),
            card("有引用資料", stats.get("with_citations", 0), TEAL, "#F0FDFA"),
            card("有概念索引", stats.get("with_concepts", 0), "#7C3AED", "#F5F3FF"),
        ], spacing=12)

    # ── 年份趨勢圖 ────────────────────────────────────────────────────

    def _build_year_trend(self, stats: dict) -> ft.Container:
        year_dist = stats.get("year_distribution", {})
        if not year_dist:
            return ft.Container(
                content=ft.Text("尚無年份資料", color=TEXT_S, italic=True),
                padding=12,
            )

        max_count = max(year_dist.values(), default=1)
        max_h = 90

        bars = []
        for year in sorted(year_dist.keys()):
            count = year_dist[year]
            bar_h = max(4, int(count / max_count * max_h))
            bars.append(ft.Column([
                ft.Text(str(count), size=9, color=TEXT_M),
                ft.Container(width=26, height=bar_h, bgcolor=ACCENT,
                             border_radius=ft.border_radius.only(top_left=3, top_right=3)),
                ft.Text(str(year), size=9, color=TEXT_S,
                        rotate=ft.Rotate(0.5)),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2))

        return _section("論文發表年份趨勢", "bar_chart", [
            ft.Container(
                content=ft.Row(bars, spacing=4, scroll=ft.ScrollMode.AUTO),
                padding=ft.padding.only(top=8),
            ),
        ])

    # ── 標籤分析（分布 + 年份互動）────────────────────────────────────

    def _build_tag_analysis(self) -> ft.Container:
        # 計算 tag 出現次數
        tag_counter: Counter = Counter()
        for p in self._papers:
            for t in p.tags:
                tag_counter[t] += 1

        if not tag_counter:
            return _section("標籤分析", "label", [
                ft.Text("尚無標籤資料，請先匯入並自動標記論文", color=TEXT_S, italic=True),
            ], color=TEAL)

        top_tags = tag_counter.most_common(25)
        max_count = top_tags[0][1]

        # 計算每個 tag 的年份分布
        tag_year: dict[str, Counter] = defaultdict(Counter)
        for p in self._papers:
            if p.year:
                for t in p.tags:
                    tag_year[t][p.year] += 1

        # 右側年份圖（初始空）
        self._selected_tag_label = ft.Text("← 點擊左側標籤查看其年份分布",
                                           size=12, color=TEXT_S, italic=True)
        self._tag_year_chart = ft.Column([self._selected_tag_label], spacing=6)

        # 左側水平條狀圖
        def make_bar(tag, count, idx):
            bar_w_max = 200

            def on_click(e, t=tag):
                self._on_tag_click(t, tag_year.get(t, {}))

            bar = ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Text(tag, size=11, color=TEXT_M,
                                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                        width=130,
                    ),
                    ft.Container(
                        width=int(count / max_count * bar_w_max),
                        height=16,
                        bgcolor=BAR_COL,
                        border_radius=3,
                    ),
                    ft.Text(str(count), size=11, color=TEXT_M),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(vertical=4, horizontal=8),
                border_radius=6,
                on_click=on_click,
                tooltip=f"點擊查看「{tag}」的年份分布",
            )
            return bar

        self._tag_bars = [make_bar(tag, count, i) for i, (tag, count) in enumerate(top_tags)]
        bar_col = ft.Column(self._tag_bars, spacing=2)

        return _section("標籤分析", "label", [
            ft.Text("左：前 25 個標籤出現次數　右：點擊標籤查看年份分布",
                    size=11, color=TEXT_S),
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
                    content=self._tag_year_chart,
                    expand=3,
                    border=ft.border.all(1, BORDER),
                    border_radius=8,
                    padding=14,
                    bgcolor=CARD,
                ),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
        ], color=TEAL)

    def _on_tag_click(self, tag: str, year_dist: Counter):
        self._selected_tag = tag

        if not year_dist:
            self._tag_year_chart.controls = [
                ft.Text(f"「{tag}」沒有年份資料", size=12, color=TEXT_S, italic=True),
            ]
            self.page.update()
            return

        # 補齊最早～最新之間每一年（缺的補 0）
        min_year = min(year_dist.keys())
        max_year = max(year_dist.keys())
        full_dist = {y: year_dist.get(y, 0) for y in range(min_year, max_year + 1)}

        max_c = max(full_dist.values(), default=1)
        max_h = 80

        bars = []
        for year in sorted(full_dist.keys()):
            cnt = full_dist[year]
            h = max(2, int(cnt / max_c * max_h)) if cnt > 0 else 2
            bar_color = BAR_SEL if cnt > 0 else "#E2E8F0"
            count_label = str(cnt) if cnt > 0 else ""
            bars.append(ft.Column([
                ft.Text(count_label, size=9, color=TEXT_M),
                ft.Container(width=22, height=h, bgcolor=bar_color,
                             border_radius=ft.border_radius.only(top_left=3, top_right=3)),
                ft.Text(str(year), size=8, color=TEXT_S, rotate=ft.Rotate(0.5)),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2))

        total = sum(year_dist.values())
        span = max_year - min_year + 1
        self._tag_year_chart.controls = [
            ft.Text(f"「{tag}」年份分布（共 {total} 篇，{min_year}–{max_year}，{span} 年）",
                    size=13, weight=ft.FontWeight.W_600, color=TEXT_H),
            ft.Container(
                content=ft.Row(bars, spacing=3, scroll=ft.ScrollMode.AUTO),
                padding=ft.padding.only(top=8),
            ),
        ]
        self.page.update()

    # ── 知識圖譜生成 ──────────────────────────────────────────────────

    def _build_graph_section(self) -> ft.Container:
        # 論文勾選清單
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

        # 圖譜設定
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

        gen_btn = ft.ElevatedButton(
            "在瀏覽器開啟互動圖譜",
            icon="open_in_browser",
            on_click=self._on_gen_graph,
            style=ft.ButtonStyle(bgcolor=ACCENT, color="#FFFFFF"),
        )

        return _section("知識圖譜視覺化（互動）", "bubble_chart", [
            ft.Text(
                "勾選要分析的論文，點擊節點可高亮其關聯論文，支援拖拽 / 縮放",
                size=11, color=TEXT_S,
            ),
            # 論文選取
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
            # 圖譜類型 + 按鈕
            ft.Row([
                self.graph_type,
                self.min_shared_dd,
                gen_btn,
            ], spacing=10, wrap=True),
            ft.Text(
                "節點大小∝引用數　顏色∝主要標籤　邊=共享關聯\n"
                "互動操作：滾輪縮放 · 拖拽節點 · 單擊高亮鄰居 · 雙擊還原",
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
                    "匯出 BibTeX (.bib)",
                    icon="code",
                    on_click=lambda e: self.bibtex_picker.save_file(
                        allowed_extensions=["bib"], file_name="papers.bib",
                        dialog_title="儲存 BibTeX 檔案",
                    ),
                    style=ft.ButtonStyle(bgcolor="#166534", color="#FFFFFF"),
                ),
                ft.ElevatedButton(
                    "匯出 RIS (.ris)",
                    icon="code",
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
