"""
論文管理視圖 — 重新設計版
"""

import json
import os
import platform
import subprocess
import flet as ft
from pathlib import Path
from typing import Optional, List

import threading

from ...services.pipeline import Pipeline
from ...services.search import SearchService
from ...database.chunk_store import ChunkStore
from ...models import Paper
from ...api import semantic_scholar as ss_api
from ...api.arxiv import ArxivAPI

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


_ALL_FIELDS = {"abstract", "authors", "venue", "year", "source", "citation_count", "tags", "doi"}


class _Card:
    def __init__(self, paper: Paper, on_delete, on_tag_remove, page: ft.Page,
                 has_fulltext: bool = False, on_read_fulltext=None,
                 search_service=None, pipeline=None,
                 visible_fields=None, custom_fields=None, custom_field_values=None):
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
        self._visible_fields: set = visible_fields if visible_fields is not None else _ALL_FIELDS
        self._custom_fields: list = custom_fields or []
        self._custom_field_values: dict = custom_field_values or {}

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
        vf = self._visible_fields

        # 作者
        if p.authors:
            auth = p.authors[0] + (" et al." if len(p.authors) > 1 else "")
        else:
            auth = "作者不詳"

        # 頂部 badge 列（依可見欄位決定）
        badges = []
        if p.year and "year" in vf:
            badges.append(_chip(str(p.year), YEAR_BG, YEAR_C))
        if p.source and "source" in vf:
            badges.append(_chip(p.source, SRC_BG, SRC_C))
        if p.citation_count and "citation_count" in vf:
            badges.append(_chip(f"引用 {p.citation_count}", "#FEF3C7", "#D97706"))

        # 標籤列
        self._tag_row = self._build_tag_row()

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

        # Semantic Scholar 補齊元資料按鈕
        self._ss_status = ft.Text("", size=10, color="#64748B")
        ss_enrich_btn = ft.Container(
            content=ft.Row([
                ft.Icon("cloud_sync", size=12, color="#0369A1"),
                ft.Text("SS 補齊元資料", size=11, color="#0369A1"),
            ], spacing=4, tight=True),
            on_click=self._on_enrich_ss,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            border_radius=6,
            border=ft.border.all(1, "#BAE6FD"),
            bgcolor="#F0F9FF",
            tooltip="透過 Semantic Scholar 補齊作者、期刊、年份、引用數等元資料",
            visible=bool(p.doi or p.title),
        )

        # 展開區內容（依可見欄位決定）
        detail_items: list = [ft.Container(height=4)]
        if "abstract" in vf:
            detail_items.append(ft.Container(
                content=ft.Text(p.abstract or "（無摘要）", size=12, color=ABST_C),
                bgcolor="#F8FAFC", padding=10, border_radius=8,
                border=ft.border.all(1, BORDER),
            ))
        if "doi" in vf:
            detail_items.append(ft.Text(
                f"DOI: {p.doi}" if p.doi else "",
                size=10, color="#3B82F6", selectable=True,
            ))
        # 自訂欄位
        for cf in self._custom_fields:
            val = self._custom_field_values.get(str(p.id), {}).get(cf["name"], "")
            if val:
                detail_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"{cf['name']}：", size=11, color=AUTH_C,
                                weight=ft.FontWeight.W_600),
                        ft.Text(val, size=12, color=TITLE_C, expand=True, selectable=True),
                    ], spacing=6),
                    bgcolor="#F8FAFC", padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    border_radius=6, border=ft.border.all(1, BORDER),
                ))
        detail_items += [
            ft.Row([sim_btn, self._cite_btn, ss_enrich_btn], spacing=8, wrap=True),
            self._ss_status,
            self._similar_col,
        ]

        self._detail_col = ft.Column(detail_items, spacing=6, visible=False)

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

        # 卡片內容（依可見欄位決定）
        card_items: list = [
            ft.Row([
                ft.Text(p.title, size=14, weight=ft.FontWeight.W_600, color=TITLE_C,
                        expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                read_btn,
                del_btn,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
        ]
        if "authors" in vf:
            card_items.append(ft.Text(auth, size=11, color=AUTH_C,
                                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        if "venue" in vf and p.venue:
            card_items.append(ft.Text(p.venue, size=11, color=META_C, italic=True))
        if badges:
            card_items.append(ft.Row(badges, spacing=6))
        if "tags" in vf:
            card_items.append(
                self._tag_row if p.tags else ft.Text("（無標籤）", size=10, color=META_C)
            )
        card_items.append(self._detail_col)

        card_inner = ft.Column(card_items, spacing=5)

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
            # ── 本地相似論文
            try:
                local_results = self._search_service.find_similar(self.paper.id, n_results=4)
            except Exception:
                local_results = []

            # ── 外部推薦（Semantic Scholar）
            external: list[dict] = []
            if self.paper.doi:
                try:
                    external = ss_api.fetch_recommendations(self.paper.doi, n=5)
                    # 排除已在本地庫的論文（按標題比對）
                    local_titles = {r.paper.title.lower() for r in local_results}
                    external = [
                        ex for ex in external
                        if ex["title"].lower() not in local_titles
                    ][:5]
                except Exception:
                    external = []

            # ── arXiv fallback（無 DOI 時）
            if not external:
                try:
                    arxiv = ArxivAPI()
                    query = self.paper.title
                    external_raw = arxiv.search_by_keywords(query, n_results=5)
                    local_titles = {r.paper.title.lower() for r in local_results}
                    external = [
                        {
                            "title": ex["title"],
                            "doi": None,
                            "arxiv_id": ex.get("arxiv_id"),
                            "year": ex.get("year"),
                            "authors": ex.get("authors", []),
                            "abstract": (ex.get("abstract") or "")[:400],
                        }
                        for ex in external_raw
                        if ex["title"].lower() not in local_titles
                    ][:5]
                except Exception:
                    external = []

            def _done():
                items = []

                # 本地相似
                if local_results:
                    items.append(ft.Text("📚 文獻庫中的相似論文", size=11,
                                         weight=ft.FontWeight.W_600, color="#059669"))
                    for sr in local_results:
                        rp = sr.paper
                        score_pct = int(sr.score * 100) if sr.score <= 1 else int(sr.score)
                        items.append(ft.Container(
                            content=ft.Column([
                                ft.Text(rp.title, size=12, color=TITLE_C,
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
                else:
                    items.append(ft.Text("文獻庫中無相似論文", size=11, color=META_C))

                # 外部推薦
                if external:
                    items.append(ft.Container(height=4))
                    src_label = "🌐 Semantic Scholar 外部推薦" if self.paper.doi else "🌐 arXiv 外部推薦"
                    items.append(ft.Text(src_label, size=11,
                                         weight=ft.FontWeight.W_600, color="#2563EB"))
                    for ex in external:
                        items.append(self._build_external_rec_card(ex))

                if not local_results and not external:
                    items = [ft.Text("找不到相似論文", size=11, color=META_C)]

                self._similar_col.controls = items
                self._page.update()

            self._page.run_task(_async_done, _done)

        async def _async_done(fn):
            fn()

        threading.Thread(target=_run, daemon=True).start()

    def _build_external_rec_card(self, ex: dict) -> ft.Container:
        """建立外部推薦論文卡（含加入文獻庫按鈕）。"""
        import_btn = ft.Container(
            content=ft.Text("+ 加入文獻庫", size=10, color="#2563EB"),
            on_click=lambda e, data=ex, btn=None: None,   # 先佔位，下面用 ref 賦值
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
            border_radius=6,
            border=ft.border.all(1, "#BFDBFE"),
            bgcolor="#EFF6FF",
            tooltip="將此論文加入你的文獻庫",
        )
        import_btn.on_click = lambda e, data=ex, b=import_btn: self._import_external_paper(data, b)

        abstract_snippet = ex.get("abstract") or ""
        year_str = str(ex.get("year") or "")
        authors = ex.get("authors") or []
        author_str = authors[0] + (" et al." if len(authors) > 1 else "") if authors else ""

        return ft.Container(
            content=ft.Column([
                ft.Text(ex["title"], size=12, color=TITLE_C,
                        weight=ft.FontWeight.W_500),
                ft.Text(author_str, size=10, color="#475569"),
                ft.Row([
                    ft.Text(year_str, size=10, color=META_C),
                    import_btn,
                ], spacing=8, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text(abstract_snippet,
                        size=10, color="#64748B", italic=True) if abstract_snippet else ft.Container(),
            ], spacing=3),
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_radius=8,
            bgcolor="#EFF6FF",
            border=ft.border.all(1, "#BFDBFE"),
        )

    def _import_external_paper(self, ex: dict, btn: ft.Container):
        """將外部推薦論文匯入文獻庫（背景執行）。"""
        if not self._pipeline:
            return
        btn.content = ft.Row([
            ft.ProgressRing(width=10, height=10, stroke_width=2),
            ft.Text("匯入中…", size=10, color=META_C),
        ], spacing=4, tight=True)
        btn.on_click = None
        self._page.update()

        def _run():
            try:
                paper = Paper(
                    title=ex["title"],
                    doi=ex.get("doi"),
                    abstract=ex.get("abstract") or "",
                    year=ex.get("year"),
                    authors=ex.get("authors") or [],
                    source="semantic_scholar" if ex.get("doi") else "arxiv",
                )
                paper_id = self._pipeline.sqlite_db.insert(paper)
                paper.id = paper_id
                if paper.abstract:
                    self._pipeline.vector_db.add(
                        paper_id=paper_id,
                        abstract=paper.abstract,
                        metadata={"title": paper.title, "tags": ""},
                    )
                success = True
            except Exception:
                success = False

            def _done():
                if success:
                    btn.content = ft.Row([
                        ft.Icon("check_circle", size=11, color="#059669"),
                        ft.Text("已加入", size=10, color="#059669"),
                    ], spacing=4, tight=True)
                    btn.bgcolor = "#ECFDF5"
                    btn.border = ft.border.all(1, "#A7F3D0")
                else:
                    btn.content = ft.Text("匯入失敗", size=10, color=RED)
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

    def _on_enrich_ss(self, e):
        """透過 Semantic Scholar 補齊元資料（作者、期刊、年份、引用數）。"""
        self._ss_status.value = "⏳ 查詢 Semantic Scholar..."
        self._ss_status.color = "#0369A1"
        self._page.update()

        def _run():
            try:
                from ...api import semantic_scholar as ss_api
                from ...database.sqlite_db import SQLiteDB
                db = SQLiteDB()
                p = self.paper

                # 用 DOI 或標題查詢
                result = None
                if p.doi:
                    result = ss_api.get_paper_by_doi(p.doi)
                if not result and p.title:
                    results = ss_api.search_papers(p.title, limit=1)
                    if results:
                        result = results[0]

                if not result:
                    self._ss_status.value = "⚠️ 找不到此論文的 Semantic Scholar 記錄"
                    self._ss_status.color = "#D97706"
                    self._page.update()
                    return

                updates: dict = {}
                updated_fields = []

                if not p.authors and result.get("authors"):
                    updates["authors"] = [a.get("name", "") for a in result["authors"]]
                    updated_fields.append("作者")
                if not p.year and result.get("year"):
                    updates["year"] = result["year"]
                    updated_fields.append("年份")
                if not p.venue and result.get("venue"):
                    updates["venue"] = result["venue"]
                    updated_fields.append("期刊")
                if not p.citation_count and result.get("citationCount"):
                    updates["citation_count"] = result["citationCount"]
                    updated_fields.append(f"引用數({result['citationCount']})")
                if not p.abstract and result.get("abstract"):
                    updates["abstract"] = result["abstract"]
                    updated_fields.append("摘要")

                if updates:
                    for k, v in updates.items():
                        setattr(p, k, v)
                    db.update(p)
                    self._ss_status.value = f"✅ 補齊：{', '.join(updated_fields)}"
                    self._ss_status.color = "#059669"
                else:
                    self._ss_status.value = "✓ 元資料已完整，無需補齊"
                    self._ss_status.color = "#64748B"

            except Exception as ex:
                self._ss_status.value = f"❌ 補齊失敗：{ex}"
                self._ss_status.color = "#EF4444"
            self._page.update()

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


_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_CUSTOM_FIELDS_FILE = _DATA_DIR / "custom_fields.json"
_CUSTOM_VALUES_FILE = _DATA_DIR / "custom_field_values.json"


class PapersView:
    def __init__(self, page: ft.Page):
        self.page = page
        self.pipeline = Pipeline()
        self.search_service = SearchService()
        self._chunk_store = ChunkStore()
        self.papers: List[Paper] = []
        self._fulltext_ids: set[int] = set()
        self.current_page = 0
        self.page_size = 200  # ListView item_extent 虛擬化，一次加載全部
        self.selected_tag: Optional[str] = None
        self._sort_by = "id"
        self._sort_dir = 1
        self._search_q = ""
        self._list_col: Optional[ft.Column] = None
        self._count_text: Optional[ft.Text] = None
        self._pagination_text: Optional[ft.Text] = None
        self.tag_dropdown: Optional[ft.Dropdown] = None
        self.sort_dd: Optional[ft.Dropdown] = None
        # 欄位設定
        self._visible_fields: set = set(_ALL_FIELDS)
        self._custom_fields: list = self._load_custom_fields()
        self._custom_field_values: dict = self._load_custom_field_values()
        # 批次選取狀態
        self._selected_ids: set[int] = set()
        self._select_all_cb: Optional[ft.Checkbox] = None
        self._batch_row: Optional[ft.Row] = None
        self._batch_count_text: Optional[ft.Text] = None
        self._list_view: Optional[ft.ListView] = None

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

        # ── 虛擬化列表（item_extent=120 只渲染可見項目）────────────────
        self._list_view = ft.ListView(expand=True, item_extent=120, spacing=4)

        # ── 全選 + 批次操作 UI ────────────────────────────────────────
        self._select_all_cb = ft.Checkbox(
            label="全選", tristate=True, value=False,
            on_change=self._on_select_all,
        )
        self._batch_count_text = ft.Text("", size=12, color=AUTH_C)
        self._batch_row = ft.Row([
            self._batch_count_text,
            ft.ElevatedButton(
                "批次刪除", icon="delete_outline",
                style=ft.ButtonStyle(bgcolor=RED, color="#FFFFFF"),
                on_click=self._on_batch_delete,
            ),
            ft.ElevatedButton(
                "批次重標籤", icon="auto_awesome",
                style=ft.ButtonStyle(bgcolor="#7C3AED", color="#FFFFFF"),
                on_click=self._on_batch_retag,
            ),
        ], spacing=8, visible=False)

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
                    "欄位設定",
                    icon="tune",
                    color="#0D9488",
                    bgcolor=CARD,
                    on_click=self._on_open_field_settings,
                ),
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
                self._select_all_cb,
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
            self._batch_row,
            self._list_view,      # 虛擬化 ListView — 自行處理滾動
            pagination_row,
        ], spacing=12, expand=True)  # 外層不加 scroll，避免巢狀滾動衝突

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

        self._list_view.controls = [
            self._build_paper_tile(p)
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

    # ── 自訂欄位 I/O ─────────────────────────────────────────────────

    def _load_custom_fields(self) -> list:
        try:
            if _CUSTOM_FIELDS_FILE.exists():
                return json.loads(_CUSTOM_FIELDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_custom_fields(self):
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CUSTOM_FIELDS_FILE.write_text(
                json.dumps(self._custom_fields, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_custom_field_values(self) -> dict:
        try:
            if _CUSTOM_VALUES_FILE.exists():
                return json.loads(_CUSTOM_VALUES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_custom_field_values(self):
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CUSTOM_VALUES_FILE.write_text(
                json.dumps(self._custom_field_values, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── 欄位設定 ─────────────────────────────────────────────────────

    def _on_open_field_settings(self, e):
        field_labels = {
            "abstract":       "摘要（展開後顯示）",
            "authors":        "作者",
            "venue":          "期刊／會議",
            "year":           "年份",
            "source":         "來源",
            "citation_count": "引用數",
            "tags":           "標籤",
            "doi":            "DOI（展開後顯示）",
        }

        cb_refs: dict[str, ft.Checkbox] = {}
        builtin_rows = []
        for field, label in field_labels.items():
            cb = ft.Checkbox(value=field in self._visible_fields, label=label, scale=0.9)
            cb_refs[field] = cb
            builtin_rows.append(cb)

        custom_col = ft.Column(spacing=6)
        status_text = ft.Text("", size=11)

        def _rebuild_custom():
            custom_col.controls.clear()
            for i, cf in enumerate(self._custom_fields):
                def _make_del(idx=i):
                    def _del(_e):
                        name = self._custom_fields[idx]["name"]
                        self._custom_fields.pop(idx)
                        # remove stored values for this field
                        for vals in self._custom_field_values.values():
                            vals.pop(name, None)
                        self._save_custom_fields()
                        self._save_custom_field_values()
                        _rebuild_custom()
                        self.page.update()
                    return _del

                def _make_ai_btn(field_cfg=cf):
                    def _click(_e):
                        _do_ai_fill(field_cfg)
                    return _click

                custom_col.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(cf["name"], size=12, weight=ft.FontWeight.W_600),
                            ft.Text(cf.get("description", ""), size=10, color=META_C),
                        ], spacing=1, expand=True),
                        ft.TextButton("AI 填寫", icon="auto_awesome",
                                      on_click=_make_ai_btn(),
                                      style=ft.ButtonStyle(color="#7C3AED")),
                        ft.IconButton(icon="delete_outline", icon_color=RED,
                                      icon_size=18, on_click=_make_del()),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor="#F8FAFC", border=ft.border.all(1, BORDER),
                    border_radius=8, padding=ft.padding.symmetric(horizontal=10, vertical=6),
                ))

        _rebuild_custom()

        new_name = ft.TextField(
            hint_text="欄位名稱", expand=True, height=38, border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=0),
        )
        new_desc = ft.TextField(
            hint_text="描述（AI 根據摘要填寫此欄位時的說明）",
            expand=True, height=38, border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=0),
        )

        def _do_ai_fill(cf: dict):
            fname = cf["name"]
            fdesc = cf.get("description", fname)
            status_text.value = f"AI 填寫「{fname}」中…"
            status_text.color = "#7C3AED"
            self.page.update()

            def _run():
                try:
                    import google.genai as genai
                    from ... import config as _cfg
                    client = genai.Client(api_key=_cfg.GEMINI_API_KEY)
                    filled = 0
                    for paper in self.papers:
                        if not paper.abstract:
                            continue
                        prompt = (
                            f"Based on this academic paper abstract, provide a concise value "
                            f"for the field '{fname}' (description: '{fdesc}'). "
                            f"Abstract: {paper.abstract[:800]}\n"
                            f"Respond with only the value, no explanation, under 120 characters."
                        )
                        try:
                            val = client.models.generate_content(
                                model=_cfg.GEMINI_MODEL, contents=prompt
                            ).text.strip()
                            pid = str(paper.id)
                            if pid not in self._custom_field_values:
                                self._custom_field_values[pid] = {}
                            self._custom_field_values[pid][fname] = val
                            filled += 1
                        except Exception:
                            pass
                    self._save_custom_field_values()

                    def _done():
                        status_text.value = f"已填寫 {filled} 篇論文的「{fname}」"
                        status_text.color = GREEN
                        self._refresh_list()
                        self.page.update()

                    self.page.run_task(_async_done, _done)
                except Exception as ex:
                    def _err():
                        status_text.value = f"AI 填寫失敗：{ex}"
                        status_text.color = RED
                        self.page.update()
                    self.page.run_task(_async_done, _err)

            async def _async_done(fn):
                fn()

            threading.Thread(target=_run, daemon=True).start()

        def _add_field(_e):
            name = (new_name.value or "").strip()
            desc = (new_desc.value or "").strip()
            if not name:
                status_text.value = "請輸入欄位名稱"
                status_text.color = RED
                self.page.update()
                return
            if any(cf["name"] == name for cf in self._custom_fields):
                status_text.value = "欄位名稱已存在"
                status_text.color = RED
                self.page.update()
                return
            self._custom_fields.append({"name": name, "description": desc})
            self._save_custom_fields()
            new_name.value = ""
            new_desc.value = ""
            status_text.value = f"已新增欄位「{name}」，點擊「AI 填寫」可自動填寫"
            status_text.color = GREEN
            _rebuild_custom()
            self.page.update()

        def _apply(_e):
            self._visible_fields = {f for f, cb in cb_refs.items() if cb.value}
            self._refresh_list()
            self._close_dlg(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("欄位設定", size=15, weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("顯示欄位", size=12, weight=ft.FontWeight.W_600, color="#475569"),
                    ft.Column(builtin_rows, spacing=0),
                    ft.Divider(height=10, color=BORDER),
                    ft.Text("自訂欄位", size=12, weight=ft.FontWeight.W_600, color="#475569"),
                    ft.Text("展開論文卡片後顯示，AI 依摘要自動填寫",
                            size=11, color=META_C),
                    custom_col,
                    ft.Row([new_name, new_desc], spacing=8),
                    ft.ElevatedButton(
                        "新增欄位", icon="add",
                        on_click=_add_field,
                        style=ft.ButtonStyle(bgcolor="#6366F1", color=ft.colors.WHITE),
                    ),
                    status_text,
                ], spacing=10, scroll=ft.ScrollMode.AUTO),
                width=520,
                height=560,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda _e: self._close_dlg(dlg)),
                ft.ElevatedButton(
                    "套用顯示設定",
                    on_click=_apply,
                    style=ft.ButtonStyle(bgcolor="#6366F1", color=ft.colors.WHITE),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
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

    # ── 固定高度 Tile（120px）——用於 ListView 虛擬化 ──────────────────

    def _build_paper_tile(self, paper: Paper) -> ft.Container:
        p = paper
        auth = (p.authors[0] + (" et al." if len(p.authors) > 1 else "")) if p.authors else "作者不詳"
        has_fulltext = p.id in self._fulltext_ids

        cb = ft.Checkbox(
            value=p.id in self._selected_ids,
            on_change=lambda e, pid=p.id: self._on_card_check(pid, e.control.value),
        )

        badges: list[ft.Control] = []
        if p.year:
            badges.append(_chip(str(p.year), YEAR_BG, YEAR_C, 9))
        if p.source:
            badges.append(_chip(p.source, SRC_BG, SRC_C, 9))
        if p.citation_count:
            badges.append(_chip(f"引用{p.citation_count}", "#FEF3C7", "#D97706", 9))
        for t in (p.tags or [])[:3]:
            badges.append(_tag_chip(t))
        if len(p.tags or []) > 3:
            badges.append(ft.Text(f"+{len(p.tags) - 3}", size=9, color=META_C))

        del_btn = ft.Container(
            content=ft.Text("刪除", size=9, color=RED),
            on_click=lambda e, pp=p: self._on_delete(pp),
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            border_radius=4,
            border=ft.border.all(1, "#FECACA"),
            bgcolor="#FFF5F5",
            tooltip="刪除此論文",
        )
        detail_btn = ft.Container(
            content=ft.Row([
                ft.Text("詳細資訊", size=9, color=ACCENT),
                ft.Icon("chevron_right", size=11, color=ACCENT),
            ], spacing=2, tight=True),
            on_click=lambda e, pp=p: self._open_card_dialog(pp),
            padding=ft.padding.symmetric(horizontal=7, vertical=2),
            border_radius=4,
            border=ft.border.all(1, "#C7D2FE"),
            bgcolor="#EEF2FF",
            tooltip="查看摘要、DOI、相似論文等詳細資訊",
        )
        fulltext_icon = ft.Container(
            content=ft.Icon("menu_book", size=11, color="#065F46"),
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
            border_radius=4,
            bgcolor="#ECFDF5",
            tooltip="已上傳全文 PDF",
        ) if has_fulltext else ft.Container(width=0)

        return ft.Container(
            content=ft.Row([
                cb,
                ft.Column([
                    ft.Row([
                        ft.Text(p.title, size=13, weight=ft.FontWeight.W_600, color=TITLE_C,
                                expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        fulltext_icon,
                        del_btn,
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
                    ft.Text(auth, size=11, color=AUTH_C, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row(badges, spacing=4, wrap=False),
                    ft.Row([ft.Container(expand=True), detail_btn]),
                ], spacing=4, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            height=110,
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            border=ft.border.all(1, BORDER),
            border_radius=10,
            bgcolor=CARD,
            shadow=ft.BoxShadow(blur_radius=3, spread_radius=0,
                                color="#06000000", offset=ft.Offset(0, 1)),
        )

    def _open_card_dialog(self, paper: Paper):
        """開啟詳細資訊 Dialog（含展開式 _Card）。"""
        has_fulltext = paper.id in self._fulltext_ids
        card_ctrl = _Card(
            paper, self._on_delete, self._on_tag_remove, self.page,
            has_fulltext=has_fulltext,
            on_read_fulltext=self._on_read_fulltext,
            search_service=self.search_service,
            pipeline=self.pipeline,
            visible_fields=self._visible_fields,
            custom_fields=self._custom_fields,
            custom_field_values=self._custom_field_values,
        ).build()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                paper.title[:60] + ("…" if len(paper.title) > 60 else ""),
                size=14, weight=ft.FontWeight.W_600, color=TITLE_C,
            ),
            content=ft.Container(
                content=ft.Column([card_ctrl], scroll=ft.ScrollMode.AUTO),
                width=700, height=520,
            ),
            actions=[
                ft.TextButton("關閉", on_click=lambda e: self._close_dlg(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    # ── 批次選取 ─────────────────────────────────────────────────────

    def _on_select_all(self, e):
        start = self.current_page * self.page_size
        page_ids = {p.id for p in self.papers[start:start + self.page_size]}
        if e.control.value is True:
            self._selected_ids.update(page_ids)
        elif e.control.value is False:
            self._selected_ids -= page_ids
        self._refresh_list()
        self._update_batch_state()
        self.page.update()

    def _on_card_check(self, paper_id: int, selected: bool):
        if selected:
            self._selected_ids.add(paper_id)
        else:
            self._selected_ids.discard(paper_id)
        self._update_batch_state()
        self.page.update()

    def _update_batch_state(self):
        n = len(self._selected_ids)
        if self._batch_row is None:
            return
        self._batch_row.visible = n > 0
        self._batch_count_text.value = f"已選 {n} 篇"
        # 同步全選 checkbox 的三態
        start = self.current_page * self.page_size
        page_ids = {p.id for p in self.papers[start:start + self.page_size]}
        sel_in_page = self._selected_ids & page_ids
        if not sel_in_page:
            self._select_all_cb.value = False
        elif sel_in_page == page_ids:
            self._select_all_cb.value = True
        else:
            self._select_all_cb.value = None   # indeterminate

    def _on_batch_delete(self, e):
        if not self._selected_ids:
            return
        count = len(self._selected_ids)

        def confirm(ev):
            self._close_dlg(dlg)
            deleted = sum(
                1 for pid in list(self._selected_ids)
                if self.pipeline.delete_paper(pid)
            )
            self._selected_ids.clear()
            self._load_papers(self.selected_tag, self._search_q)
            self._refresh_list()
            self._update_batch_state()
            self._snack(f"已刪除 {deleted} 篇論文")
            self.page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("確認批次刪除", size=15),
            content=ft.Text(f"確定刪除選取的 {count} 篇論文？此操作無法復原。", size=13),
            actions=[
                ft.TextButton("取消", on_click=lambda ev: self._close_dlg(dlg)),
                ft.TextButton("刪除", on_click=confirm,
                              style=ft.ButtonStyle(color=RED)),
            ],
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _on_batch_retag(self, e):
        if not self._selected_ids:
            return
        count = len(self._selected_ids)
        tags_field = ft.TextField(
            label="新增標籤（逗號分隔，不會刪除現有標籤）",
            hint_text="例如：Machine Learning, NLP",
            expand=True,
        )
        status_t = ft.Text("", size=12)

        def _do_retag(ev):
            tags_str = (tags_field.value or "").strip()
            if not tags_str:
                status_t.value = "⚠️ 請輸入至少一個標籤"
                status_t.color = RED
                self.page.update()
                return
            new_tags = [t.strip() for t in tags_str.split(",") if t.strip()]
            status_t.value = "處理中..."
            status_t.color = ACCENT
            self.page.update()

            def run():
                updated = 0
                for pid in list(self._selected_ids):
                    paper = self.pipeline.sqlite_db.get_by_id(pid)
                    if paper:
                        existing = list(paper.tags or [])
                        for nt in new_tags:
                            if nt not in existing:
                                existing.append(nt)
                        paper.tags = existing
                        self.pipeline.sqlite_db.update(paper)
                        updated += 1

                self._close_dlg(dlg)
                self._selected_ids.clear()
                self._load_papers(self.selected_tag, self._search_q)
                self._refresh_list()
                self._update_batch_state()
                self._snack(f"已為 {updated} 篇論文新增標籤：{', '.join(new_tags)}")
                self.page.update()

            threading.Thread(target=run, daemon=True).start()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"批次重標籤（{count} 篇）", size=15, weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(f"為選取的 {count} 篇論文新增以下標籤", size=12, color=AUTH_C),
                    tags_field,
                    status_t,
                ], spacing=10),
                width=480,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda ev: self._close_dlg(dlg)),
                ft.ElevatedButton(
                    "套用標籤", on_click=_do_retag,
                    style=ft.ButtonStyle(bgcolor="#7C3AED", color="#FFFFFF"),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def _snack(self, msg: str, error: bool = False):
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(msg),
            bgcolor=RED if error else GREEN,
        )
        self.page.snack_bar.open = True
        self.page.update()
