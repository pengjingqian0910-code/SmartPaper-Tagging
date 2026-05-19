"""
論文管理視圖 — 重新設計版
"""

import os
import platform
import subprocess
import flet as ft
from typing import Optional, List

import threading

from ...services.pipeline import Pipeline
from ...services.search import SearchService
from ...database.chunk_store import ChunkStore
from ...models import Paper

# ── 色彩 ──────────────────────────────────────────────────────────────
BG        = "#F1F5F9"   # 頁面底色（淺灰藍）
CARD      = "#FFFFFF"
BORDER    = "#E2E8F0"
BORDER_A  = "#6366F1"
TITLE_C   = "#1E293B"
AUTH_C    = "#475569"
META_C    = "#94A3B8"
TAG_BG    = "#EEF2FF"
TAG_C     = "#4F46E5"
YEAR_BG   = "#ECFDF5"
YEAR_C    = "#059669"
SRC_BG    = "#EFF6FF"
SRC_C     = "#2563EB"
ABST_C    = "#64748B"
ACCENT    = "#6366F1"
RED       = "#EF4444"
GREEN     = "#10B981"


def _chip(text: str, bg: str, color: str, size: int = 10) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=size, color=color, weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        border_radius=50,
        bgcolor=bg,
    )


def _tag_chip(text: str, on_remove=None) -> ft.Container:
    label = ft.Text(text, size=10, color=TAG_C, weight=ft.FontWeight.W_500)
    if on_remove:
        inner = ft.Row([
            label,
            ft.Container(
                content=ft.Text("×", size=13, color=TAG_C, weight=ft.FontWeight.BOLD),
                on_click=on_remove,
                padding=ft.padding.only(left=2),
                tooltip="移除此標籤",
            ),
        ], spacing=2, tight=True)
    else:
        inner = label
    return ft.Container(
        content=inner,
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        border_radius=50,
        bgcolor=TAG_BG,
    )


class _Card:
    def __init__(self, paper: Paper, on_delete, on_tag_remove, page: ft.Page,
                 has_fulltext: bool = False, on_read_fulltext=None,
                 search_service=None, pipeline=None):
        self.paper = paper
        self._page = page
        self._on_delete = on_delete
        self._on_tag_remove = on_tag_remove
        self._has_fulltext = has_fulltext
        self._on_read_fulltext = on_read_fulltext
        self._search_service = search_service
        self._pipeline = pipeline
        self._expanded = False
        self._tag_row: Optional[ft.Row] = None
        self._detail_col: Optional[ft.Column] = None
        self._container: Optional[ft.Container] = None
        self._similar_col: Optional[ft.Column] = None
        self._cite_btn: Optional[ft.Container] = None

    def _build_tag_row(self) -> ft.Row:
        return ft.Row([
            _tag_chip(t, on_remove=lambda e, tag=t: self._remove_tag(e, tag))
            for t in self.paper.tags
        ], spacing=4, wrap=True)

    def _remove_tag(self, e, tag: str):
        self._on_tag_remove(self.paper, tag)
        self._tag_row.controls = [
            _tag_chip(t, on_remove=lambda ev, tg=t: self._remove_tag(ev, tg))
            for t in self.paper.tags
        ]
        self._page.update()

    def build(self) -> ft.Container:
        p = self.paper

        # 作者
        if p.authors:
            auth = p.authors[0] + (" et al." if len(p.authors) > 1 else "")
        else:
            auth = "作者不詳"

        # 頂部 badge 列
        badges = []
        if p.year:
            badges.append(_chip(str(p.year), YEAR_BG, YEAR_C))
        if p.source:
            badges.append(_chip(p.source, SRC_BG, SRC_C))
        if p.citation_count:
            badges.append(_chip(f"引用 {p.citation_count}", "#FEF3C7", "#D97706"))

        # 標籤列
        self._tag_row = self._build_tag_row()

        # 摘要 + DOI（預設隱藏）
        abst = (p.abstract or "")[:600] + ("…" if p.abstract and len(p.abstract) > 600 else "")

        # 相似論文區塊
        self._similar_col = ft.Column([], spacing=4, visible=False)

        # 抓取引用按鈕
        self._cite_btn = ft.Container(
            content=ft.Row([
                ft.Icon("link", size=12, color="#7C3AED"),
                ft.Text("補抓引用關係", size=11, color="#7C3AED"),
            ], spacing=4, tight=True),
            on_click=self._on_fetch_citations,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=6,
            border=ft.border.all(1, "#DDD6FE"),
            bgcolor="#F5F3FF",
            tooltip="透過 Semantic Scholar 補抓此論文的引用關係",
            visible=bool(p.doi),
        )

        # 相似論文按鈕
        sim_btn = ft.Container(
            content=ft.Row([
                ft.Icon("recommend", size=12, color="#059669"),
                ft.Text("推薦相似論文", size=11, color="#059669"),
            ], spacing=4, tight=True),
            on_click=self._on_find_similar,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=6,
            border=ft.border.all(1, "#A7F3D0"),
            bgcolor="#ECFDF5",
            tooltip="依摘要語意搜尋相似論文",
        )

        self._detail_col = ft.Column([
            ft.Container(height=4),
            ft.Container(
                content=ft.Text(abst or "（無摘要）", size=12, color=ABST_C),
                bgcolor="#F8FAFC",
                padding=10,
                border_radius=8,
                border=ft.border.all(1, BORDER),
            ),
            ft.Text(
                f"DOI: {p.doi}" if p.doi else "",
                size=10, color="#3B82F6", selectable=True,
            ),
            ft.Row([sim_btn, self._cite_btn], spacing=8),
            self._similar_col,
        ], spacing=6, visible=False)

        # 刪除按鈕
        del_btn = ft.Container(
            content=ft.Text("刪除", size=11, color=RED),
            on_click=lambda e, pp=p: self._on_delete(pp),
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=6,
            border=ft.border.all(1, "#FECACA"),
            bgcolor="#FFF5F5",
            tooltip="刪除此論文",
        )

        # 閱覽全文按鈕（有 PDF 才顯示）
        read_btn = ft.Container(
            content=ft.Row([
                ft.Icon("menu_book", size=13, color="#065F46"),
                ft.Text("閱覽全文", size=11, color="#065F46"),
            ], spacing=4, tight=True),
            on_click=lambda e, pp=p: self._on_read_fulltext(pp) if self._on_read_fulltext else None,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=6,
            border=ft.border.all(1, "#A7F3D0"),
            bgcolor="#ECFDF5",
            tooltip="用系統預設程式開啟 PDF",
            visible=self._has_fulltext,
        )

        card_inner = ft.Column([
            # 標題列
            ft.Row([
                ft.Text(
                    p.title,
                    size=14,
                    weight=ft.FontWeight.W_600,
                    color=TITLE_C,
                    expand=True,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                read_btn,
                del_btn,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),

            # 作者
            ft.Text(auth, size=11, color=AUTH_C,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),

            # 期刊
            ft.Text(
                p.venue[:70] + ("…" if p.venue and len(p.venue) > 70 else "") if p.venue else "",
                size=11, color=META_C, italic=True,
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            ),

            # Badges
            ft.Row(badges, spacing=6) if badges else ft.Container(height=0),

            # 標籤
            self._tag_row if p.tags else ft.Text("（無標籤）", size=10, color=META_C),

            # 摘要展開區
            self._detail_col,
        ], spacing=5)

        self._container = ft.Container(
            content=card_inner,
            padding=ft.padding.symmetric(horizontal=18, vertical=14),
            border=ft.border.all(1, BORDER),
            border_radius=12,
            bgcolor=CARD,
            on_click=self._toggle,
            shadow=ft.BoxShadow(blur_radius=4, spread_radius=0,
                                color="#08000000", offset=ft.Offset(0, 1)),
        )
        return self._container

    def _on_find_similar(self, e):
        if not self._search_service:
            return
        self._similar_col.controls = [
            ft.Row([
                ft.ProgressRing(width=14, height=14, stroke_width=2),
                ft.Text("搜尋相似論文中…", size=11, color=META_C),
            ], spacing=6)
        ]
        self._similar_col.visible = True
        self._page.update()

        def _run():
            try:
                results = self._search_service.find_similar(self.paper.id, n_results=4)
            except Exception:
                results = []

            def _done():
                if not results:
                    self._similar_col.controls = [
                        ft.Text("找不到相似論文", size=11, color=META_C)
                    ]
                else:
                    items = [
                        ft.Text("相似論文推薦", size=11, weight=ft.FontWeight.W_600,
                                color="#059669"),
                    ]
                    for sr in results:
                        rp = sr.paper
                        score_pct = int(sr.score * 100) if sr.score <= 1 else int(sr.score)
                        items.append(ft.Container(
                            content=ft.Column([
                                ft.Text(rp.title, size=12, color=TITLE_C,
                                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                                        weight=ft.FontWeight.W_500),
                                ft.Row([
                                    ft.Text(f"相似度 {score_pct}%", size=10, color="#059669"),
                                    ft.Text(str(rp.year or ""), size=10, color=META_C),
                                    *[_chip(t, TAG_BG, TAG_C, 9) for t in (rp.tags or [])[:2]],
                                ], spacing=6),
                            ], spacing=2),
                            padding=ft.padding.symmetric(horizontal=10, vertical=6),
                            border_radius=8,
                            bgcolor="#F0FDF4",
                            border=ft.border.all(1, "#BBF7D0"),
                        ))
                    self._similar_col.controls = items
                self._page.update()

            self._page.run_task(_async_done, _done)

        async def _async_done(fn):
            fn()

        threading.Thread(target=_run, daemon=True).start()

    def _on_fetch_citations(self, e):
        if not self._pipeline:
            return
        self._cite_btn.content = ft.Row([
            ft.ProgressRing(width=12, height=12, stroke_width=2),
            ft.Text("抓取中…", size=11, color="#7C3AED"),
        ], spacing=4, tight=True)
        self._cite_btn.on_click = None
        self._page.update()

        def _run():
            count = self._pipeline.fetch_citations_for_paper(self.paper.id)

            def _done():
                if count > 0:
                    self._cite_btn.content = ft.Row([
                        ft.Icon("check_circle", size=12, color="#059669"),
                        ft.Text(f"已儲存 {count} 筆引用", size=11, color="#059669"),
                    ], spacing=4, tight=True)
                    self._cite_btn.bgcolor = "#ECFDF5"
                    self._cite_btn.border = ft.border.all(1, "#A7F3D0")
                else:
                    self._cite_btn.content = ft.Row([
                        ft.Icon("info_outline", size=12, color=META_C),
                        ft.Text("無引用資料（需有 DOI）", size=11, color=META_C),
                    ], spacing=4, tight=True)
                self._page.update()

            self._page.run_task(_async_done, _done)

        async def _async_done(fn):
            fn()

        threading.Thread(target=_run, daemon=True).start()

    def _toggle(self, e):
        self._expanded = not self._expanded
        self._detail_col.visible = self._expanded
        self._container.border = ft.border.all(
            1.5 if self._expanded else 1,
            BORDER_A if self._expanded else BORDER,
        )
        self._container.shadow = ft.BoxShadow(
            blur_radius=12 if self._expanded else 4,
            spread_radius=0,
            color="#14000000" if self._expanded else "#08000000",
            offset=ft.Offset(0, 2 if self._expanded else 1),
        )
        self._page.update()


class PapersView:
    def __init__(self, page: ft.Page):
        self.page = page
        self.pipeline = Pipeline()
        self.search_service = SearchService()
        self._chunk_store = ChunkStore()
        self.papers: List[Paper] = []
        self._fulltext_ids: set[int] = set()
        self.current_page = 0
        self.page_size = 25
        self.selected_tag: Optional[str] = None
        self._sort_by = "id"
        self._sort_dir = 1
        self._search_q = ""
        self._list_col: Optional[ft.Column] = None
        self._count_text: Optional[ft.Text] = None
        self._pagination_text: Optional[ft.Text] = None
        self.tag_dropdown: Optional[ft.Dropdown] = None
        self.sort_dd: Optional[ft.Dropdown] = None

    # ── Build ─────────────────────────────────────────────────────────

    def build(self) -> ft.Column:
        try:
            return self._build_inner()
        except Exception as e:
            import traceback
            with open("papers_view_error.log", "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            return ft.Column([
                ft.Text("論文管理載入失敗", color=RED, size=16),
                ft.Text(str(e), color=RED, size=13),
            ], scroll=ft.ScrollMode.AUTO, expand=True)

    def _build_inner(self) -> ft.Column:
        self._load_papers()

        # FilePicker
        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self._on_export_path
        self.page.overlay.append(self.file_picker)

        # 搜尋框
        self._search_field = ft.TextField(
            hint_text="搜尋標題、作者、期刊…",
            prefix_icon="search",
            expand=True,
            height=42,
            border_radius=10,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=0),
            filled=True,
            fill_color=CARD,
            on_change=self._on_search_change,
        )

        # 標籤篩選
        all_tags = self.search_service.get_all_tags()
        self.tag_dropdown = ft.Dropdown(
            label="標籤篩選",
            value="__all__",
            options=[ft.dropdown.Option("__all__", "全部標籤")] +
                    [ft.dropdown.Option(t, t) for t in all_tags[:80]],
            width=170,
            border_radius=10,
        )
        self.tag_dropdown.on_change = self._on_tag_change

        # 排序
        self.sort_dd = ft.Dropdown(
            label="排序",
            value=self._sort_by,
            width=130,
            border_radius=10,
            options=[
                ft.dropdown.Option("id",             "匯入順序"),
                ft.dropdown.Option("title",          "標題 A→Z"),
                ft.dropdown.Option("year",           "年份"),
                ft.dropdown.Option("citation_count", "引用數"),
                ft.dropdown.Option("venue",          "期刊"),
            ],
        )
        self.sort_dd.on_change = self._on_sort_change

        self._sort_dir_btn = ft.IconButton(
            icon="arrow_upward",
            tooltip="切換升/降序",
            icon_color=ACCENT,
            on_click=self._toggle_sort_dir,
        )

        self._count_text = ft.Text("", size=13, color=AUTH_C)
        self._pagination_text = ft.Text("", size=12, color=META_C)

        self._list_col = ft.Column(spacing=8)
        self._refresh_list()

        # 分頁
        pagination_row = ft.Row([
            ft.IconButton(icon="chevron_left", on_click=self._prev_page,
                          icon_color=ACCENT),
            self._pagination_text,
            ft.IconButton(icon="chevron_right", on_click=self._next_page,
                          icon_color=ACCENT),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=4)

        # 頂部標題列
        header = ft.Row([
            ft.Column([
                ft.Text("論文管理", size=24, weight=ft.FontWeight.BOLD, color=TITLE_C),
                self._count_text,
            ], spacing=2),
            ft.Row([
                ft.ElevatedButton(
                    "標籤管理",
                    icon="label",
                    color="#7C3AED",
                    bgcolor=CARD,
                    on_click=self._on_open_tag_manager,
                ),
                ft.ElevatedButton(
                    "匯出 XLSX",
                    icon="download",
                    color=ACCENT,
                    bgcolor=CARD,
                    on_click=self._on_export_click,
                ),
                ft.ElevatedButton(
                    "重新整理",
                    icon="refresh",
                    color=ACCENT,
                    bgcolor=CARD,
                    on_click=self._on_refresh,
                ),
            ], spacing=8),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        # 篩選列
        filter_row = ft.Container(
            content=ft.Row([
                self._search_field,
                self.tag_dropdown,
                self.sort_dd,
                self._sort_dir_btn,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            border_radius=12,
            bgcolor=CARD,
            border=ft.border.all(1, BORDER),
        )

        return ft.Column([
            header,
            filter_row,
            self._list_col,
            pagination_row,
        ], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

    # ── Data ──────────────────────────────────────────────────────────

    def _load_papers(self, tag=None, query=""):
        self._fulltext_ids = set(self._chunk_store.papers_with_fulltext())
        if tag and tag not in ("__all__",):
            papers = list(self.search_service.search_by_tag(tag))
        else:
            papers = list(self.pipeline.sqlite_db.get_all(limit=2000))

        if query:
            q = query.lower()
            papers = [p for p in papers if
                      q in p.title.lower() or
                      any(q in a.lower() for a in p.authors) or
                      (p.venue and q in p.venue.lower())]

        reverse = (self._sort_dir == -1)
        key = self._sort_by
        if key in ("year", "citation_count"):
            papers.sort(key=lambda p: getattr(p, key) or 0, reverse=reverse)
        else:
            papers.sort(
                key=lambda p: (getattr(p, key) or "").lower()
                if isinstance(getattr(p, key, ""), str) else 0,
                reverse=reverse,
            )

        self.papers = papers
        self.current_page = 0

    def _refresh_list(self):
        total = len(self.papers)
        total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        start = self.current_page * self.page_size
        page_papers = self.papers[start:start + self.page_size]

        self._count_text.value = f"共 {total} 篇論文"
        self._pagination_text.value = f"第 {self.current_page + 1} / {total_pages} 頁"

        self._list_col.controls = [
            _Card(
                p, self._on_delete, self._on_tag_remove, self.page,
                has_fulltext=(p.id in self._fulltext_ids),
                on_read_fulltext=self._on_read_fulltext,
                search_service=self.search_service,
                pipeline=self.pipeline,
            ).build()
            for p in page_papers
        ]

    # ── Events ────────────────────────────────────────────────────────

    def _on_search_change(self, e):
        self._search_q = e.control.value or ""
        self._load_papers(self.selected_tag, self._search_q)
        self._refresh_list()
        self.page.update()

    def _on_tag_change(self, e):
        val = e.control.value
        self.selected_tag = None if val == "__all__" else val
        self._load_papers(self.selected_tag, self._search_q)
        self._refresh_list()
        self.page.update()

    def _on_sort_change(self, e):
        self._sort_by = e.control.value
        self._load_papers(self.selected_tag, self._search_q)
        self._refresh_list()
        self.page.update()

    def _toggle_sort_dir(self, e):
        self._sort_dir *= -1
        self._sort_dir_btn.icon = (
            "arrow_downward" if self._sort_dir == -1 else "arrow_upward"
        )
        self._load_papers(self.selected_tag, self._search_q)
        self._refresh_list()
        self.page.update()

    def _on_refresh(self, e):
        self._load_papers(self.selected_tag, self._search_q)
        self._refresh_list()
        self.page.update()

    def _prev_page(self, e):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_list()
            self.page.update()

    def _next_page(self, e):
        total_pages = max(1, (len(self.papers) + self.page_size - 1) // self.page_size)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._refresh_list()
            self.page.update()

    def _on_export_click(self, e):
        self.file_picker.save_file(
            allowed_extensions=["xlsx"],
            dialog_title="選擇匯出位置",
            file_name="papers_export.xlsx",
        )

    def _on_export_path(self, e):
        if e.path:
            try:
                self.pipeline.export_to_xlsx(e.path, self.papers)
                self._snack(f"已匯出 {len(self.papers)} 篇至 {e.path}")
            except Exception as ex:
                self._snack(f"匯出失敗: {ex}", error=True)

    def _on_tag_remove(self, paper: Paper, tag: str):
        if tag in paper.tags:
            paper.tags.remove(tag)
            self.pipeline.sqlite_db.update(paper)

    def _on_delete(self, paper: Paper):
        def confirm(e):
            self._close_dlg(dlg)
            if self.pipeline.delete_paper(paper.id):
                self._load_papers(self.selected_tag, self._search_q)
                self._refresh_list()
                self._snack("已刪除")
                self.page.update()
            else:
                self._snack("刪除失敗", error=True)

        dlg = ft.AlertDialog(
            title=ft.Text("確認刪除", size=15),
            content=ft.Text(f"確定刪除「{paper.title[:60]}」？", size=13),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dlg(dlg)),
                ft.TextButton("刪除", on_click=confirm,
                              style=ft.ButtonStyle(color=RED)),
            ],
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _close_dlg(self, dlg):
        dlg.open = False
        self.page.update()

    # ── 標籤管理 ─────────────────────────────────────────────────────

    def _on_open_tag_manager(self, e):
        """開啟標籤管理對話框（可合併/重命名/刪除標籤）"""
        db = self.pipeline.sqlite_db
        tag_counts = db.get_tag_counts()   # [(tag, count), ...]

        if not tag_counts:
            self._snack("目前沒有任何標籤")
            return

        status_text = ft.Text("", size=12)
        selected: set[str] = set()
        checkboxes: dict[str, ft.Checkbox] = {}
        tag_rows_col = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)

        def _rebuild_rows(filter_text=""):
            tag_rows_col.controls.clear()
            for tag, cnt in tag_counts:
                if filter_text and filter_text.lower() not in tag.lower():
                    continue
                cb = ft.Checkbox(
                    value=tag in selected,
                    scale=0.85,
                    on_change=lambda e, t=tag: _toggle(t, e.control.value),
                )
                checkboxes[tag] = cb
                tag_rows_col.controls.append(
                    ft.Row([
                        cb,
                        ft.Text(tag, size=12, expand=True),
                        ft.Container(
                            content=ft.Text(str(cnt), size=10, color="#FFFFFF"),
                            bgcolor="#7C3AED",
                            border_radius=8,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        ),
                    ], spacing=6)
                )

        def _toggle(tag, val):
            if val:
                selected.add(tag)
            else:
                selected.discard(tag)

        search_f = ft.TextField(
            hint_text="搜尋標籤…", prefix_icon="search",
            height=38, expand=True, border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=0),
            on_change=lambda e: (_rebuild_rows(e.control.value), self.page.update()),
        )
        merge_target = ft.TextField(
            hint_text="合併後的標籤名稱", expand=True, height=38,
            border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=0),
        )

        def _do_merge(e):
            new_name = (merge_target.value or "").strip()
            if not selected:
                status_text.value = "⚠️ 請先勾選要合併的標籤"
                status_text.color = RED
                self.page.update()
                return
            if not new_name:
                status_text.value = "⚠️ 請輸入合併後的名稱"
                status_text.color = RED
                self.page.update()
                return
            total = 0
            for old in list(selected):
                if old != new_name:
                    n = db.rename_tag(old, new_name)
                    total += n
                    # update local list
                    for i, (t, c) in enumerate(tag_counts):
                        if t == old:
                            tag_counts.pop(i)
                            break
            selected.clear()
            status_text.value = f"✅ 已合併 → 「{new_name}」，更新 {total} 篇論文"
            status_text.color = GREEN
            _rebuild_rows()
            self.page.update()

        def _do_rename(e):
            if len(selected) != 1:
                status_text.value = "⚠️ 重命名請只勾選 1 個標籤"
                status_text.color = RED
                self.page.update()
                return
            new_name = (merge_target.value or "").strip()
            if not new_name:
                status_text.value = "⚠️ 請在下方輸入新名稱"
                status_text.color = RED
                self.page.update()
                return
            old = next(iter(selected))
            n = db.rename_tag(old, new_name)
            for i, (t, c) in enumerate(tag_counts):
                if t == old:
                    tag_counts[i] = (new_name, c)
                    break
            selected.clear()
            status_text.value = f"✅ 「{old}」→「{new_name}」，更新 {n} 篇"
            status_text.color = GREEN
            _rebuild_rows()
            self.page.update()

        def _do_delete(e):
            if not selected:
                status_text.value = "⚠️ 請先勾選要刪除的標籤"
                status_text.color = RED
                self.page.update()
                return
            total = 0
            for tag in list(selected):
                n = db.delete_tag(tag)
                total += n
                for i, (t, c) in enumerate(tag_counts):
                    if t == tag:
                        tag_counts.pop(i)
                        break
            selected.clear()
            status_text.value = f"✅ 已刪除，更新 {total} 篇論文"
            status_text.color = GREEN
            _rebuild_rows()
            self.page.update()

        _rebuild_rows()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("標籤管理", size=15, weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"共 {len(tag_counts)} 個標籤，勾選後可合併或刪除",
                            size=12, color="#475569"),
                    search_f,
                    ft.Container(
                        content=tag_rows_col,
                        height=280,
                        border=ft.border.all(1, "#E2E8F0"),
                        border_radius=8,
                        padding=8,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    ft.Row([
                        ft.Text("新名稱：", size=12),
                        merge_target,
                    ], spacing=8),
                    ft.Row([
                        ft.ElevatedButton(
                            "合併選取",
                            icon="merge",
                            style=ft.ButtonStyle(bgcolor="#7C3AED", color="#FFFFFF"),
                            on_click=_do_merge,
                        ),
                        ft.ElevatedButton(
                            "重命名",
                            icon="edit",
                            style=ft.ButtonStyle(bgcolor="#2563EB", color="#FFFFFF"),
                            on_click=_do_rename,
                        ),
                        ft.ElevatedButton(
                            "刪除選取",
                            icon="delete_outline",
                            style=ft.ButtonStyle(bgcolor=RED, color="#FFFFFF"),
                            on_click=_do_delete,
                        ),
                    ], spacing=8),
                    status_text,
                ], spacing=10, scroll=ft.ScrollMode.AUTO),
                width=480,
                height=520,
            ),
            actions=[
                ft.TextButton("關閉", on_click=lambda e: self._close_tag_manager(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def _close_tag_manager(self, dlg):
        dlg.open = False
        # 關閉後重新整理論文列表（標籤可能已改變）
        self._load_papers(self.selected_tag, self._search_q)
        self._refresh_list()
        self.page.update()

    def _on_read_fulltext(self, paper: Paper):
        """用系統預設程式開啟論文的原始 PDF 檔案"""
        pdf_path = self.pipeline.sqlite_db.get_pdf_path(paper.id)

        if not pdf_path:
            self._snack("此論文尚未記錄 PDF 路徑（舊版匯入），請重新上傳 PDF", error=True)
            return

        from pathlib import Path
        path = Path(pdf_path)
        if not path.exists():
            self._snack(f"找不到檔案：{pdf_path}", error=True)
            return

        try:
            sys = platform.system()
            if sys == "Windows":
                os.startfile(str(path))
            elif sys == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as ex:
            self._snack(f"無法開啟 PDF：{ex}", error=True)

    def _snack(self, msg: str, error: bool = False):
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(msg),
            bgcolor=RED if error else GREEN,
        )
        self.page.snack_bar.open = True
        self.page.update()
