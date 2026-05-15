"""
搜尋視圖
提供關鍵字搜尋與語義搜尋功能
"""

import flet as ft
from typing import List, Optional

from ...services.search import SearchService
from ...services.concept_extractor import ConceptExtractor, TYPE_LABELS
from ...services.citation import CitationService
from ...models import Paper, SearchResult


class SearchView:
    """搜尋視圖類"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.search_service = SearchService()
        self.concept_extractor = ConceptExtractor()
        self.citation_service = CitationService()
        self.results: List[SearchResult | Paper] = []
        self.search_mode = "semantic"  # "semantic" | "keyword" | "hybrid" | "concept"

        # UI 元件
        self.search_field: Optional[ft.TextField] = None
        self.results_column: Optional[ft.Column] = None
        self.results_count_text: Optional[ft.Text] = None

    def build(self) -> ft.Column:
        """建立搜尋視圖"""
        # 搜尋輸入框
        self.search_field = ft.TextField(
            label="輸入搜尋關鍵字或描述...",
            hint_text="例如：機器學習在醫療應用",
            width=500,
            on_submit=self.on_search,
            suffix=ft.IconButton(
                icon="search",
                on_click=self.on_search,
            ),
        )

        # 搜尋模式切換
        self.mode_toggle = ft.RadioGroup(
            content=ft.Row(
                [
                    ft.Radio(value="semantic", label="語義搜尋"),
                    ft.Radio(value="keyword", label="關鍵字搜尋"),
                    ft.Radio(value="hybrid", label="BM25＋語意（RRF）"),
                    ft.Radio(value="concept", label="概念搜尋"),
                ],
            ),
            value="semantic",
            on_change=self.on_mode_change,
        )

        # 結果計數
        self.results_count_text = ft.Text(
            "",
            size=14,
            color=ft.colors.GREY_600,
        )

        # 結果列表
        self.results_column = ft.Column(
            [],
            spacing=15,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        return ft.Column(
            [
                # 標題
                ft.Text(
                    "搜尋論文",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Divider(height=20),

                # 搜尋區域
                ft.Container(
                    content=ft.Column(
                        [
                            self.search_field,
                            ft.Text("搜尋模式", size=14, weight=ft.FontWeight.W_500),
                            self.mode_toggle,
                            ft.Text(
                                "語義：自然語言描述　關鍵字：精確標題匹配　混合：BM25+語意RRF　概念：BERT/ImageNet 等名稱",
                                size=11,
                                color=ft.colors.GREY_500,
                            ),
                        ],
                        spacing=10,
                    ),
                    padding=20,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    border_radius=10,
                ),

                ft.Divider(height=20),

                # 結果區域
                self.results_count_text,
                self.results_column,
            ],
            spacing=10,
            expand=True,
        )

    def on_mode_change(self, e):
        """處理搜尋模式變更"""
        self.search_mode = e.control.value

    def on_search(self, e):
        """執行搜尋"""
        query = self.search_field.value
        if not query or not query.strip():
            return

        query = query.strip()
        self.results = []

        try:
            if self.search_mode == "semantic":
                results = self.search_service.semantic_search(
                    query=query,
                    n_results=20,
                )
                self.results = results
            elif self.search_mode == "keyword":
                papers = self.search_service.keyword_search(
                    keyword=query,
                    search_in="title",
                )
                self.results = papers
            elif self.search_mode == "hybrid":
                results = self.search_service.hybrid_search(
                    query=query,
                    n_results=20,
                )
                self.results = results
            elif self.search_mode == "concept":
                papers = self.concept_extractor.search_by_concept(query)
                self.results = papers

            self.update_results_display()

        except Exception as ex:
            self.results_count_text.value = f"搜尋失敗: {str(ex)}"
            self.results_count_text.color = ft.colors.RED_700
            self.page.update()

    def update_results_display(self):
        """更新結果顯示"""
        self.results_column.controls.clear()

        if not self.results:
            self.results_count_text.value = "找不到符合的論文"
            self.results_count_text.color = ft.colors.GREY_600
        else:
            self.results_count_text.value = f"找到 {len(self.results)} 篇論文"
            self.results_count_text.color = ft.colors.GREEN_700

            for item in self.results:
                if isinstance(item, SearchResult):
                    paper = item.paper
                    score = item.score
                else:
                    paper = item
                    score = None

                self.results_column.controls.append(
                    self.build_result_card(paper, score)
                )

        self.page.update()

    def build_result_card(
        self, paper: Paper, score: Optional[float] = None
    ) -> ft.Container:
        """建立搜尋結果卡片"""
        # 摘要預覽
        abstract_preview = ""
        if paper.abstract:
            abstract_preview = (
                paper.abstract[:200] + "..."
                if len(paper.abstract) > 200
                else paper.abstract
            )

        # 標籤顯示
        tags_row = ft.Row(
            [
                ft.Container(
                    content=ft.Text(tag, size=11, color=ft.colors.WHITE),
                    bgcolor=ft.colors.BLUE_400,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=12,
                )
                for tag in paper.tags[:5]
            ],
            spacing=5,
            wrap=True,
        )

        # 相似度分數顯示
        score_widget = None
        if score is not None:
            score_percent = int(score * 100)
            score_color = (
                ft.colors.GREEN_700
                if score >= 0.7
                else ft.colors.ORANGE_700
                if score >= 0.4
                else ft.colors.RED_700
            )
            score_widget = ft.Container(
                content=ft.Text(
                    f"相似度: {score_percent}%",
                    size=12,
                    color=score_color,
                    weight=ft.FontWeight.BOLD,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=5),
                border=ft.border.all(1, score_color),
                border_radius=5,
            )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                paper.title,
                                size=16,
                                weight=ft.FontWeight.W_500,
                                expand=True,
                            ),
                            score_widget if score_widget else ft.Container(),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(
                        f"DOI: {paper.doi}" if paper.doi else "DOI: 無",
                        size=12,
                        color=ft.colors.BLUE_700 if paper.doi else ft.colors.GREY_600,
                    ),
                    tags_row if paper.tags else ft.Container(),
                    ft.Container(
                        content=ft.Text(
                            abstract_preview or "無摘要",
                            size=13,
                            color=ft.colors.GREY_700,
                        ),
                        padding=ft.padding.only(top=10),
                    ),
                    ft.Row(
                        [
                            ft.TextButton(
                                "檢視詳情",
                                icon="visibility",
                                on_click=lambda e, p=paper: self.on_view_detail(p),
                            ),
                            ft.TextButton(
                                "尋找相似",
                                icon="compare",
                                on_click=lambda e, p=paper: self.on_find_similar(p),
                            ),
                            ft.TextButton(
                                "引用關係",
                                icon="account_tree",
                                on_click=lambda e, p=paper: self.on_view_citations(p),
                            ),
                            ft.TextButton(
                                "共享概念",
                                icon="lightbulb",
                                on_click=lambda e, p=paper: self.on_find_by_concepts(p),
                            ),
                        ],
                    ),
                ],
                spacing=8,
            ),
            padding=20,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=10,
        )

    def on_view_detail(self, paper: Paper):
        """檢視論文詳情（含概念萃取結果）"""
        concepts = self.concept_extractor.get_paper_concepts(paper.id) if paper.id else {}

        concept_widgets = []
        if concepts:
            type_colors = {
                "method": ft.colors.BLUE_400,
                "dataset": ft.colors.GREEN_400,
                "metric": ft.colors.ORANGE_400,
                "task": ft.colors.PURPLE_400,
            }
            for ctype, names in concepts.items():
                if not names:
                    continue
                chips = ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(n, size=10, color=ft.colors.WHITE),
                            bgcolor=type_colors.get(ctype, ft.colors.GREY_400),
                            padding=ft.padding.symmetric(horizontal=7, vertical=3),
                            border_radius=10,
                        )
                        for n in names
                    ],
                    wrap=True,
                    spacing=4,
                )
                concept_widgets += [
                    ft.Text(TYPE_LABELS.get(ctype, ctype), size=11, weight=ft.FontWeight.BOLD, color=ft.colors.GREY_600),
                    chips,
                ]

        dlg = ft.AlertDialog(
            title=ft.Text("論文詳情"),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("標題", weight=ft.FontWeight.BOLD),
                        ft.Text(paper.title, selectable=True),
                        ft.Divider(),
                        ft.Text("DOI", weight=ft.FontWeight.BOLD),
                        ft.Text(paper.doi or "無", selectable=True),
                        ft.Divider(),
                        ft.Text("標籤", weight=ft.FontWeight.BOLD),
                        ft.Text(", ".join(paper.tags) if paper.tags else "無"),
                        *([ft.Divider(), ft.Text("概念索引", weight=ft.FontWeight.BOLD)] + concept_widgets if concept_widgets else []),
                        ft.Divider(),
                        ft.Text("摘要", weight=ft.FontWeight.BOLD),
                        ft.Container(
                            content=ft.Text(paper.abstract or "無摘要", selectable=True),
                            height=180,
                            padding=10,
                            border=ft.border.all(1, ft.colors.GREY_300),
                            border_radius=5,
                        ),
                    ],
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=520,
                height=480,
            ),
            actions=[ft.TextButton("關閉", on_click=lambda e: self.close_dialog(dlg))],
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def on_view_citations(self, paper: Paper):
        """檢視引用關係"""
        if not paper.id:
            return

        stats = self.citation_service.get_stats(paper.id)
        refs = self.citation_service.get_references(paper.id)
        citing = self.citation_service.get_citing_papers(paper.id)

        in_db_rows = [
            ft.ListTile(
                leading=ft.Icon("article", color=ft.colors.BLUE_400, size=16),
                title=ft.Text(p.title[:60], size=12),
                subtitle=ft.Text(f"DOI: {p.doi or '-'}", size=10),
            )
            for p in refs["in_db"]
        ]
        external_rows = [
            ft.ListTile(
                leading=ft.Icon("link", color=ft.colors.GREY_400, size=16),
                title=ft.Text(r["title"][:60], size=11, color=ft.colors.GREY_600),
                subtitle=ft.Text(f"DOI: {r['doi'] or '-'}", size=10),
            )
            for r in refs["external"][:20]
        ]
        citing_rows = [
            ft.ListTile(
                leading=ft.Icon("arrow_back", color=ft.colors.GREEN_400, size=16),
                title=ft.Text(p.title[:60], size=12),
            )
            for p in citing
        ]

        content_cols = [
            ft.Text(f"引用出去：{stats['citing']} 篇 ｜ 被引用：{stats['cited_by']} 篇",
                    size=12, color=ft.colors.GREY_600),
            ft.Divider(),
        ]
        if in_db_rows:
            content_cols += [ft.Text("引用的論文（資料庫內）", weight=ft.FontWeight.BOLD, size=12)] + in_db_rows
        if external_rows:
            content_cols += [ft.Text("引用的論文（資料庫外）", weight=ft.FontWeight.BOLD, size=12, color=ft.colors.GREY_500)] + external_rows
        if citing_rows:
            content_cols += [ft.Divider(), ft.Text("引用此論文的論文", weight=ft.FontWeight.BOLD, size=12)] + citing_rows
        if not in_db_rows and not external_rows and not citing_rows:
            content_cols.append(ft.Text("尚無引用資料，請先執行「建立引用圖」", color=ft.colors.GREY_500))

        dlg = ft.AlertDialog(
            title=ft.Text(f"引用關係：{paper.title[:40]}..."),
            content=ft.Container(
                content=ft.Column(content_cols, spacing=4, scroll=ft.ScrollMode.AUTO),
                width=520, height=450,
            ),
            actions=[ft.TextButton("關閉", on_click=lambda e: self.close_dialog(dlg))],
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def on_find_by_concepts(self, paper: Paper):
        """找出與此論文共享最多概念的論文"""
        if not paper.id:
            return

        related = self.concept_extractor.find_papers_sharing_concepts(paper.id, top_k=15)
        if not related:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text("尚無概念資料，請先執行「萃取概念」"),
            )
            self.page.snack_bar.open = True
            self.page.update()
            return

        self.results = [r["paper"] for r in related]
        self.results_count_text.value = (
            f"找到 {len(related)} 篇與「{paper.title[:30]}...」共享概念的論文"
        )
        self.update_results_display()

        # 在結果上方補充共享概念說明
        for i, r in enumerate(related):
            if i < len(self.results_column.controls):
                shared = ", ".join(r["shared_concepts"][:3])
                self.results_column.controls[i].content.controls.insert(
                    1,
                    ft.Text(f"共享概念：{shared}", size=11, color=ft.colors.TEAL_600, italic=True),
                )
        self.page.update()

    def on_find_similar(self, paper: Paper):
        """尋找相似論文"""
        if not paper.id:
            return

        try:
            similar_results = self.search_service.find_similar(
                paper_id=paper.id,
                n_results=10,
            )

            if similar_results:
                self.results = similar_results
                self.results_count_text.value = (
                    f"找到 {len(similar_results)} 篇與「{paper.title[:30]}...」相似的論文"
                )
                self.update_results_display()
            else:
                self.page.snack_bar = ft.SnackBar(
                    content=ft.Text("找不到相似論文"),
                )
                self.page.snack_bar.open = True
                self.page.update()

        except Exception as ex:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(f"搜尋失敗: {str(ex)}"),
                bgcolor=ft.colors.RED_700,
            )
            self.page.snack_bar.open = True
            self.page.update()

    def close_dialog(self, dlg: ft.AlertDialog):
        """關閉對話框"""
        dlg.open = False
        self.page.update()
