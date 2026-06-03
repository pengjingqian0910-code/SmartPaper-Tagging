"""
搜尋視圖 — 重新設計版
段落式模式切換 + 精簡結果卡片（漸進式揭露）
"""

import flet as ft
from typing import List, Optional

from ...services.search import SearchService
from ...services.concept_extractor import ConceptExtractor, TYPE_LABELS
from ...services.citation import CitationService
from ...models import Paper, SearchResult
from .. import theme as T


_MODE_OPTIONS = [
    ("semantic", "語意"),
    ("hybrid",   "混合（推薦）"),
    ("keyword",  "關鍵字"),
    ("concept",  "概念"),
]
_MODE_DESC = {
    "semantic": "用自然語言描述，找語意相近的論文",
    "hybrid":   "BM25 + 語意向量 + 個人化排序，召回率最高",
    "keyword":  "精確標題關鍵字匹配",
    "concept":  "根據 BERT、ImageNet 等概念名稱搜尋",
}


class SearchView:

    def __init__(self, page: ft.Page):
        self.page = page
        self.search_service = SearchService()
        self.concept_extractor = ConceptExtractor()
        self.citation_service = CitationService()
        self.results: List[SearchResult | Paper] = []
        self.search_mode = "hybrid"
        self._mode_btns: dict[str, ft.Container] = {}

        self.search_field: Optional[ft.TextField] = None
        self.results_column: Optional[ft.Column] = None
        self.results_count_text: Optional[ft.Text] = None
        self._mode_desc_text: Optional[ft.Text] = None

    def build(self) -> ft.Column:
        self.search_field = ft.TextField(
            hint_text="輸入關鍵字或自然語言描述，如「Transformer 注意力效率」",
            expand=True,
            height=44,
            border_radius=T.RADIUS_M,
            content_padding=ft.padding.symmetric(horizontal=14, vertical=0),
            filled=True,
            fill_color="#FFFFFF",
            on_submit=self.on_search,
            suffix=ft.IconButton(
                icon="search", icon_size=18,
                icon_color=T.ACCENT,
                on_click=self.on_search,
                tooltip="搜尋",
            ),
        )

        self._mode_desc_text = ft.Text(
            _MODE_DESC[self.search_mode],
            size=11, color=T.TEXT_M, italic=True,
        )

        self.results_count_text = ft.Text("", size=12, color=T.TEXT_M)

        self.results_column = ft.Column(
            [], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
        )

        return ft.Column(
            [
                ft.Row([
                    ft.Column([
                        ft.Text("搜尋論文", size=22, weight=ft.FontWeight.BOLD, color=T.TEXT_H),
                        ft.Text("從文獻庫語意查詢，支援自然語言", size=11, color=T.TEXT_M),
                    ], spacing=2, expand=True),
                ]),
                T.soft_divider(),

                # ── 搜尋列 ────────────────────────────────────────
                ft.Row([self.search_field], spacing=12),

                # ── 模式切換（segment chips）─────────────────────
                ft.Column([
                    ft.Row(
                        [self._build_mode_chip(k, label) for k, label in _MODE_OPTIONS],
                        spacing=6,
                    ),
                    self._mode_desc_text,
                ], spacing=4),

                # ── 結果計數 ──────────────────────────────────────
                self.results_count_text,

                # ── 結果列表 ──────────────────────────────────────
                self.results_column,
            ],
            spacing=12,
            expand=True,
        )

    # ── Mode chips ────────────────────────────────────────────────

    def _build_mode_chip(self, key: str, label: str) -> ft.Container:
        is_active = key == self.search_mode
        chip = ft.Container(
            content=ft.Text(
                label, size=12,
                color="#FFFFFF" if is_active else T.TEXT_B,
                weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
            ),
            bgcolor=T.ACCENT if is_active else "#FFFFFF",
            border=ft.border.all(1, T.ACCENT if is_active else T.CARD_BORDER),
            border_radius=T.RADIUS_M,
            padding=ft.padding.symmetric(horizontal=14, vertical=7),
            on_click=lambda e, k=key: self._on_mode_click(k),
            ink=True,
            animate=T.ANIM,
        )
        self._mode_btns[key] = chip
        return chip

    def _on_mode_click(self, key: str):
        self.search_mode = key
        for k, chip in self._mode_btns.items():
            is_active = k == key
            chip.bgcolor = T.ACCENT if is_active else "#FFFFFF"
            chip.border = ft.border.all(1, T.ACCENT if is_active else T.CARD_BORDER)
            chip.content.color = "#FFFFFF" if is_active else T.TEXT_B
            chip.content.weight = ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL
        self._mode_desc_text.value = _MODE_DESC[key]
        self.page.update()

    def on_mode_change(self, e):
        self._on_mode_click(e.control.value)

    # ── Search ────────────────────────────────────────────────────

    def on_search(self, e):
        query = (self.search_field.value or "").strip()
        if not query:
            return

        self.results_count_text.value = "搜尋中…"
        self.results_count_text.color = T.ACCENT
        self.results_column.controls.clear()
        self.page.update()

        try:
            if self.search_mode == "semantic":
                self.results = self.search_service.semantic_search(query=query, n_results=20)
            elif self.search_mode == "keyword":
                self.results = self.search_service.keyword_search(keyword=query, search_in="title")
            elif self.search_mode == "hybrid":
                self.results = self.search_service.enhanced_search(query=query, n_results=20)
            elif self.search_mode == "concept":
                self.results = self.concept_extractor.search_by_concept(query)

            self.update_results_display()
        except Exception as ex:
            self.results_count_text.value = f"搜尋失敗：{ex}"
            self.results_count_text.color = T.DANGER
            self.page.update()

    def update_results_display(self):
        self.results_column.controls.clear()

        if not self.results:
            self.results_count_text.value = "找不到符合的論文"
            self.results_count_text.color = T.TEXT_M
        else:
            self.results_count_text.value = f"找到 {len(self.results)} 篇論文"
            self.results_count_text.color = T.SUCCESS
            for item in self.results:
                paper = item.paper if isinstance(item, SearchResult) else item
                score = item.score if isinstance(item, SearchResult) else None
                self.results_column.controls.append(self.build_result_card(paper, score))

        self.page.update()

    # ── Result card (漸進式揭露) ──────────────────────────────────

    def build_result_card(self, paper: Paper, score: Optional[float] = None) -> ft.Container:
        # 分數 badge
        score_badge = ft.Container()
        if score is not None:
            pct = int(score * 100)
            clr = T.SUCCESS if score >= 0.7 else T.WARNING if score >= 0.4 else T.DANGER
            score_badge = ft.Container(
                content=ft.Text(f"{pct}%", size=11, color=clr, weight=ft.FontWeight.W_600),
                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                border=ft.border.all(1, clr),
                border_radius=T.RADIUS_S,
                bgcolor=T.alpha(clr, 0.07),
            )

        # 作者 + 年份
        meta_parts = []
        if paper.authors:
            auth = paper.authors[0] + (" et al." if len(paper.authors) > 1 else "")
            meta_parts.append(auth)
        if paper.year:
            meta_parts.append(str(paper.year))
        if paper.venue:
            meta_parts.append(paper.venue[:30])
        if paper.doi:
            meta_parts.append(f"DOI: {paper.doi[:20]}")

        meta_text = ft.Text(
            "  ·  ".join(meta_parts) if meta_parts else "無作者資訊",
            size=11, color=T.TEXT_M,
        )

        # 標籤 chips
        tag_row = ft.Row(
            [
                ft.Container(
                    content=ft.Text(t, size=10, color=T.ACCENT),
                    bgcolor=T.ACCENT_SOFT,
                    padding=ft.padding.symmetric(horizontal=8, vertical=2),
                    border_radius=T.RADIUS_S,
                )
                for t in (paper.tags or [])[:4]
            ],
            spacing=4, wrap=True,
        ) if paper.tags else ft.Container()

        # 摘要（可展開）
        abstract_short = (paper.abstract or "無摘要")[:150]
        if paper.abstract and len(paper.abstract) > 150:
            abstract_short += "…"

        abstract_expanded = ft.Container(
            content=ft.Text(paper.abstract or "無摘要", size=12, color=T.TEXT_B),
            visible=False,
            padding=ft.padding.only(top=6),
        )
        expand_btn = ft.TextButton(
            "展開摘要",
            icon="expand_more",
            style=ft.ButtonStyle(color=T.TEXT_M),
            visible=bool(paper.abstract and len(paper.abstract) > 150),
        )

        def _toggle_abstract(e):
            abstract_expanded.visible = not abstract_expanded.visible
            expand_btn.text = "收合" if abstract_expanded.visible else "展開摘要"
            expand_btn.icon = "expand_less" if abstract_expanded.visible else "expand_more"
            self.page.update()

        expand_btn.on_click = _toggle_abstract

        # 主要操作 (2個) + 次要操作 (PopupMenu)
        primary_row = ft.Row([
            ft.TextButton(
                "詳情", icon="open_in_new",
                style=ft.ButtonStyle(color=T.ACCENT),
                on_click=lambda e, p=paper: self.on_view_detail(p),
            ),
            ft.TextButton(
                "相似論文", icon="compare",
                style=ft.ButtonStyle(color=T.TEXT_M),
                on_click=lambda e, p=paper: self.on_find_similar(p),
            ),
            expand_btn,
            ft.Container(expand=True),
            ft.PopupMenuButton(
                icon="more_horiz",
                icon_color=T.TEXT_M,
                items=[
                    ft.PopupMenuItem(
                        text="引用關係",
                        icon="account_tree",
                        on_click=lambda e, p=paper: self.on_view_citations(p),
                    ),
                    ft.PopupMenuItem(
                        text="共享概念",
                        icon="lightbulb",
                        on_click=lambda e, p=paper: self.on_find_by_concepts(p),
                    ),
                ],
            ),
        ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(paper.title, size=14, weight=ft.FontWeight.W_600,
                            color=T.TEXT_H, expand=True),
                    score_badge,
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                meta_text,
                tag_row,
                ft.Text(abstract_short, size=12, color=T.TEXT_M),
                abstract_expanded,
                primary_row,
            ], spacing=6),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor=T.CARD_BG,
            border=ft.border.all(1, T.CARD_BORDER),
            border_radius=T.RADIUS_M,
            shadow=ft.BoxShadow(blur_radius=4, spread_radius=0,
                                color=T.CARD_SHADOW, offset=ft.Offset(0, 1)),
        )

    # ── Detail / similar / citations ──────────────────────────────

    def on_view_detail(self, paper: Paper):
        concepts = self.concept_extractor.get_paper_concepts(paper.id) if paper.id else {}
        concept_widgets = []
        if concepts:
            type_colors = {
                "method": "#3B82F6", "dataset": "#10B981",
                "metric": "#F59E0B", "task": "#8B5CF6",
            }
            for ctype, names in concepts.items():
                if not names:
                    continue
                concept_widgets += [
                    ft.Text(TYPE_LABELS.get(ctype, ctype), size=11,
                            weight=ft.FontWeight.W_600, color=T.TEXT_M),
                    ft.Row([
                        ft.Container(
                            content=ft.Text(n, size=10, color="#FFFFFF"),
                            bgcolor=type_colors.get(ctype, "#6B7280"),
                            padding=ft.padding.symmetric(horizontal=7, vertical=3),
                            border_radius=T.RADIUS_S,
                        )
                        for n in names
                    ], wrap=True, spacing=4),
                ]

        dlg = ft.AlertDialog(
            title=ft.Text(paper.title, size=14, weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("DOI", weight=ft.FontWeight.BOLD, size=11, color=T.TEXT_M),
                    ft.Text(paper.doi or "無", selectable=True, size=12),
                    ft.Divider(height=8, color=T.CARD_BORDER),
                    ft.Text("標籤", weight=ft.FontWeight.BOLD, size=11, color=T.TEXT_M),
                    ft.Text(", ".join(paper.tags) if paper.tags else "無", size=12),
                    *([ft.Divider(height=8, color=T.CARD_BORDER),
                       ft.Text("概念索引", weight=ft.FontWeight.BOLD, size=11, color=T.TEXT_M)]
                      + concept_widgets if concept_widgets else []),
                    ft.Divider(height=8, color=T.CARD_BORDER),
                    ft.Text("摘要", weight=ft.FontWeight.BOLD, size=11, color=T.TEXT_M),
                    ft.Container(
                        content=ft.Text(paper.abstract or "無摘要",
                                        selectable=True, size=12),
                        height=180, padding=10,
                        border=ft.border.all(1, T.CARD_BORDER),
                        border_radius=T.RADIUS_S,
                    ),
                ], spacing=6, scroll=ft.ScrollMode.AUTO),
                width=520, height=460,
            ),
            actions=[ft.TextButton("關閉", on_click=lambda e: self.close_dialog(dlg))],
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def on_find_similar(self, paper: Paper):
        similar = self.search_service.find_similar(paper.id, n_results=10)
        self.results = similar
        self.results_count_text.value = f"與「{paper.title[:30]}…」相似的論文："
        self.results_count_text.color = T.ACCENT
        self.update_results_display()

    def on_view_citations(self, paper: Paper):
        cited_papers = self.citation_service.get_cited_papers(paper.id)
        if not cited_papers:
            self.results_count_text.value = "此論文尚無引用關係資料"
            self.results_count_text.color = T.TEXT_M
            self.page.update()
            return
        self.results = cited_papers
        self.results_count_text.value = f"「{paper.title[:30]}」引用的論文（{len(cited_papers)} 篇）："
        self.results_count_text.color = T.ACCENT
        self.update_results_display()

    def on_find_by_concepts(self, paper: Paper):
        concepts = self.concept_extractor.get_paper_concepts(paper.id)
        if not concepts:
            self.results_count_text.value = "此論文尚無概念索引資料"
            self.results_count_text.color = T.TEXT_M
            self.page.update()
            return
        all_concepts = [c for names in concepts.values() for c in names]
        if not all_concepts:
            return
        query = " ".join(all_concepts[:5])
        self.search_field.value = query
        self.search_mode = "concept"
        self.on_search(None)

    def close_dialog(self, dlg):
        dlg.open = False
        self.page.update()
