"""
寫作引用導引視圖
用戶輸入寫作大綱，系統推薦每個段落應引用哪些論文及其概念
"""

import flet as ft
from typing import Optional

from ...services.writing_guide import WritingGuideService, SectionGuide
from ...skills import ALL_SKILLS, get_skill
from ...config import GEMINI_API_KEY


class WritingGuideView:
    """寫作引用導引視圖"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.service: Optional[WritingGuideService] = None
        self.results_container: Optional[ft.Column] = None

    def build(self) -> ft.Control:
        """建構視圖"""

        # 大綱輸入區
        self.outline_input = ft.TextField(
            label="寫作大綱（每行一個段落）",
            hint_text=(
                "例如：\n"
                "1. 引言：深度學習在醫療影像的背景\n"
                "2. 相關工作：現有方法與局限\n"
                "3. 方法：提出的模型架構\n"
                "4. 實驗：評測結果與分析"
            ),
            multiline=True,
            min_lines=5,
            max_lines=12,
            expand=True,
        )

        # 專家角色選擇
        self.skill_dropdown = ft.Dropdown(
            label="專家角色",
            value="general",
            options=[
                ft.dropdown.Option(skill_id, skill.name)
                for skill_id, skill in ALL_SKILLS.items()
            ],
            width=200,
            tooltip="選擇符合你論文領域的專家角色，獲得更精準的引用建議",
        )

        # 候選論文數量
        self.n_candidates_dropdown = ft.Dropdown(
            label="每段落候選論文數",
            value="8",
            options=[
                ft.dropdown.Option("5", "5 篇（快速）"),
                ft.dropdown.Option("8", "8 篇（推薦）"),
                ft.dropdown.Option("12", "12 篇（完整）"),
            ],
            width=180,
        )

        # Step 1：搜尋候選論文
        self.find_btn = ft.ElevatedButton(
            text="Step 1：搜尋候選論文",
            icon="search",
            on_click=self.run_find_candidates,
            style=ft.ButtonStyle(bgcolor=ft.colors.INDIGO_600, color=ft.colors.WHITE),
        )

        # Step 2：AI 分析（需先完成 Step 1）
        self.analyze_btn = ft.ElevatedButton(
            text="Step 2：AI 分析引用",
            icon="auto_awesome",
            on_click=self.run_analyze,
            disabled=True,
            style=ft.ButtonStyle(bgcolor=ft.colors.TEAL_700, color=ft.colors.WHITE),
            tooltip="先完成 Step 1 搜尋候選論文，再執行 AI 分析" if not GEMINI_API_KEY
                    else "確認候選論文後執行 AI 引用分析",
        )

        self.export_btn = ft.OutlinedButton(
            text="匯出 Markdown",
            icon="download",
            on_click=self.export_guide,
            visible=False,
        )

        # 內部狀態
        self._last_guides: list[SectionGuide] = []
        self._section_candidates: dict[str, list[dict]] = {}   # section -> candidates
        self._candidate_checks: dict[str, dict[int, ft.Checkbox]] = {}  # section -> {paper_id -> checkbox}

        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self.on_export_path_selected
        self.page.overlay.append(self.file_picker)

        self.progress_ring = ft.ProgressRing(visible=False)
        self.status_text = ft.Text("", size=12, color=ft.colors.GREY_600)

        if not GEMINI_API_KEY:
            self.status_text.value = "未設定 Gemini API Key — Step 2 AI 分析將停用，但仍可查看候選論文"
            self.status_text.color = ft.colors.ORANGE_700

        self.results_container = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=0,
        )

        return ft.Column(
            [
                ft.Text("寫作引用導引", size=28, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Step 1 搜尋候選→確認要分析的論文→Step 2 AI 分析各段落的引用建議",
                    size=13, color=ft.colors.GREY_600,
                ),
                ft.Divider(height=16),

                ft.Row([self.outline_input], alignment=ft.MainAxisAlignment.START),

                ft.Row(
                    [
                        self.skill_dropdown,
                        self.n_candidates_dropdown,
                        self.find_btn,
                        self.analyze_btn,
                        self.export_btn,
                        self.progress_ring,
                        self.status_text,
                    ],
                    spacing=12,
                    alignment=ft.MainAxisAlignment.START,
                    wrap=True,
                ),

                ft.Divider(height=16),

                ft.Container(
                    content=self.results_container,
                    expand=True,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    border_radius=8,
                    padding=15,
                ),
            ],
            spacing=12,
            expand=True,
        )

    def _parse_outline(self) -> list[str]:
        """解析大綱文字，每行為一個段落（忽略空行）"""
        raw = self.outline_input.value or ""
        sections = [line.strip() for line in raw.splitlines() if line.strip()]
        return sections

    def run_find_candidates(self, e):
        """Step 1：為每個段落搜尋候選論文，顯示確認面板"""
        sections = self._parse_outline()
        if not sections:
            self.status_text.value = "請輸入至少一個段落描述"
            self.page.update()
            return

        self.progress_ring.visible = True
        self.find_btn.disabled = True
        self.analyze_btn.disabled = True
        self.export_btn.visible = False
        self.status_text.value = "搜尋候選論文中..."
        self.results_container.controls.clear()
        self._section_candidates.clear()
        self._candidate_checks.clear()
        self.page.update()

        try:
            skill = get_skill(self.skill_dropdown.value or "general")
            n_candidates = int(self.n_candidates_dropdown.value or "8")
            self.service = WritingGuideService(skill=skill)

            for idx, section in enumerate(sections, 1):
                self.status_text.value = f"搜尋中 [{idx}/{len(sections)}] {section[:30]}..."
                self.page.update()

                candidates = self.service.find_section_candidates(section, n_candidates)
                self._section_candidates[section] = candidates

                card, checks = self._build_confirm_card(idx, section, candidates)
                self._candidate_checks[section] = checks
                self.results_container.controls.append(card)

            total_candidates = sum(len(v) for v in self._section_candidates.values())
            self.status_text.value = (
                f"找到 {total_candidates} 篇候選論文（{len(sections)} 個段落）。"
                "請確認後點擊 Step 2 執行 AI 分析。"
            )
            self.analyze_btn.disabled = not bool(total_candidates)

        except Exception as ex:
            self.status_text.value = f"搜尋失敗：{ex}"
        finally:
            self.progress_ring.visible = False
            self.find_btn.disabled = False
            self.page.update()

    def _build_confirm_card(
        self, index: int, section: str, candidates: list[dict]
    ) -> tuple[ft.Control, dict[int, ft.Checkbox]]:
        """建立候選論文確認卡片，回傳 (card_widget, {paper_id: Checkbox})"""
        checks: dict[int, ft.Checkbox] = {}

        if not candidates:
            card = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Text(str(index), size=13, weight=ft.FontWeight.BOLD,
                                           color=ft.colors.WHITE),
                            bgcolor=ft.colors.GREY_500, width=26, height=26,
                            border_radius=13, alignment=ft.alignment.center,
                        ),
                        ft.Text(section, size=14, weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text("找不到相關論文", size=12, color=ft.colors.GREY_500),
                    ], spacing=8),
                ], spacing=6),
                padding=12,
                border=ft.border.all(1, ft.colors.GREY_200),
                border_radius=8,
                margin=ft.margin.only(bottom=10),
            )
            return card, checks

        rows = []
        for c in candidates:
            paper = c["paper"]
            score = c.get("rerank_score", c.get("score", 0.0))
            cb = ft.Checkbox(value=True, label="")
            checks[paper.id] = cb
            rows.append(ft.Row([
                cb,
                ft.Column([
                    ft.Text(
                        paper.title[:70] + ("…" if len(paper.title) > 70 else ""),
                        size=12, weight=ft.FontWeight.W_500, expand=True,
                    ),
                    ft.Row([
                        ft.Text(f"相關度 {score:.2f}", size=10, color=ft.colors.INDIGO_400),
                        ft.Text(f"  {paper.year or ''}", size=10, color=ft.colors.GREY_500),
                        ft.Text(f"  {(paper.venue or '')[:30]}", size=10, color=ft.colors.GREY_500),
                        *([ft.Text("  " + "  ".join(paper.tags[:3]), size=10,
                                   color=ft.colors.TEAL_600)] if paper.tags else []),
                    ], spacing=0),
                ], spacing=2, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        def _toggle_all(e, _rows=rows, _checks=checks):
            val = e.control.value
            for pid, cb in _checks.items():
                cb.value = val
            self.page.update()

        select_all_cb = ft.Checkbox(value=True, label="全選", on_change=_toggle_all)

        card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Text(str(index), size=13, weight=ft.FontWeight.BOLD,
                                       color=ft.colors.WHITE),
                        bgcolor=ft.colors.INDIGO_600, width=26, height=26,
                        border_radius=13, alignment=ft.alignment.center,
                    ),
                    ft.Text(section, size=14, weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(f"{len(candidates)} 篇候選", size=12, color=ft.colors.GREY_500),
                    select_all_cb,
                ], spacing=8),
                ft.Divider(height=6),
                *rows,
            ], spacing=5),
            padding=12,
            border=ft.border.all(1, ft.colors.INDIGO_100),
            border_radius=8,
            bgcolor=ft.colors.INDIGO_50,
            margin=ft.margin.only(bottom=10),
        )
        return card, checks

    def run_analyze(self, e):
        """Step 2：對確認的候選論文執行 AI 分析"""
        if not self._section_candidates:
            self.status_text.value = "請先執行 Step 1 搜尋候選論文"
            self.page.update()
            return

        self.progress_ring.visible = True
        self.find_btn.disabled = True
        self.analyze_btn.disabled = True
        self.export_btn.visible = False
        self.results_container.controls.clear()
        self.page.update()

        try:
            guides = []
            sections = list(self._section_candidates.keys())
            for idx, section in enumerate(sections, 1):
                self.status_text.value = f"AI 分析中 [{idx}/{len(sections)}] {section[:30]}..."
                self.page.update()

                # 只保留使用者勾選的論文
                checks = self._candidate_checks.get(section, {})
                all_candidates = self._section_candidates[section]
                selected = [c for c in all_candidates
                            if checks.get(c["paper"].id, ft.Checkbox(value=True)).value]
                if not selected:
                    selected = all_candidates  # 若全不選則保留全部

                guide = self.service.analyze_from_candidates(section, selected)
                guides.append(guide)
                self.results_container.controls.append(
                    self._build_section_card(idx, guide)
                )
                self.page.update()

            self._last_guides = guides
            self.status_text.value = f"完成！共 {len(guides)} 個段落"
            self.export_btn.visible = True

        except Exception as ex:
            self.status_text.value = f"AI 分析失敗：{ex}"
        finally:
            self.progress_ring.visible = False
            self.find_btn.disabled = False
            self.analyze_btn.disabled = False
            self.page.update()

    def _display_guides(self, guides: list[SectionGuide]):
        """顯示所有段落的引用導引"""
        for i, guide in enumerate(guides, 1):
            self.results_container.controls.append(
                self._build_section_card(i, guide)
            )

    def _build_section_card(self, index: int, guide: SectionGuide) -> ft.Control:
        """建立單一段落的引用導引卡片"""

        # 寫作建議橫幅
        hint_row = []
        if guide.writing_hint:
            hint_row.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon("lightbulb_outline", size=14, color=ft.colors.AMBER_700),
                            ft.Text(
                                guide.writing_hint,
                                size=12,
                                color=ft.colors.AMBER_900,
                                expand=True,
                            ),
                        ],
                        spacing=6,
                    ),
                    bgcolor=ft.colors.AMBER_50,
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=6,
                    margin=ft.margin.only(bottom=10),
                )
            )

        # 引用論文列表
        citation_tiles = []
        if guide.citations:
            for c in guide.citations:
                # 顏色依位置區分
                position_colors = {
                    "段落開頭": ft.colors.GREEN_100,
                    "中間論述": ft.colors.BLUE_100,
                    "結尾總結": ft.colors.PURPLE_100,
                }
                pos_color = position_colors.get(c.cite_position, ft.colors.GREY_100)
                pos_label_colors = {
                    "段落開頭": ft.colors.GREEN_700,
                    "中間論述": ft.colors.BLUE_700,
                    "結尾總結": ft.colors.PURPLE_700,
                }
                pos_label_color = pos_label_colors.get(c.cite_position, ft.colors.GREY_700)

                citation_tiles.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                # 論文標題列
                                ft.Row(
                                    [
                                        ft.Icon("article", size=14, color=ft.colors.BLUE_600),
                                        ft.Text(
                                            c.paper.title[:70] + "..." if len(c.paper.title) > 70 else c.paper.title,
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            expand=True,
                                        ),
                                        ft.Container(
                                            content=ft.Text(
                                                c.cite_position,
                                                size=10,
                                                color=pos_label_color,
                                            ),
                                            bgcolor=pos_color,
                                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                            border_radius=10,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                # 引用理由 + 引用概念
                                ft.Row(
                                    [
                                        ft.Column(
                                            [
                                                ft.Row([
                                                    ft.Text("引用時機：", size=11, color=ft.colors.GREY_600, weight=ft.FontWeight.BOLD),
                                                    ft.Text(c.cite_reason, size=11, color=ft.colors.GREY_800, expand=True),
                                                ]),
                                                ft.Row([
                                                    ft.Text("引用概念：", size=11, color=ft.colors.TEAL_600, weight=ft.FontWeight.BOLD),
                                                    ft.Text(c.key_concept, size=11, color=ft.colors.TEAL_800, expand=True),
                                                ]),
                                            ],
                                            spacing=2,
                                            expand=True,
                                        ),
                                    ],
                                    spacing=0,
                                ),
                                # 標籤
                                ft.Row(
                                    [
                                        ft.Text(tag, size=10, color=ft.colors.GREY_500)
                                        for tag in (c.paper.tags or [])[:4]
                                    ],
                                    spacing=6,
                                ) if c.paper.tags else ft.Container(),
                            ],
                            spacing=4,
                        ),
                        padding=ft.padding.all(10),
                        border=ft.border.all(1, ft.colors.BLUE_100),
                        border_radius=6,
                        bgcolor=ft.colors.WHITE,
                        margin=ft.margin.only(bottom=6),
                    )
                )
        else:
            citation_tiles.append(
                ft.Text(
                    "未找到與此段落相關的論文，建議補充更多文獻或調整描述。",
                    size=12,
                    color=ft.colors.GREY_500,
                    italic=True,
                )
            )

        return ft.Container(
            content=ft.Column(
                [
                    # 段落標題
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(
                                    str(index),
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.colors.WHITE,
                                ),
                                bgcolor=ft.colors.BLUE_600,
                                width=28,
                                height=28,
                                border_radius=14,
                                alignment=ft.alignment.center,
                            ),
                            ft.Text(
                                guide.section,
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                expand=True,
                            ),
                            ft.Text(
                                f"{len(guide.citations)} 篇引用",
                                size=12,
                                color=ft.colors.GREY_500,
                            ),
                        ],
                        spacing=10,
                    ),
                    *hint_row,
                    *citation_tiles,
                ],
                spacing=6,
            ),
            padding=15,
            border=ft.border.all(1, ft.colors.GREY_200),
            border_radius=8,
            margin=ft.margin.only(bottom=12),
            bgcolor=ft.colors.GREY_50,
        )

    def export_guide(self, e):
        """匯出 Markdown"""
        self.file_picker.save_file(
            dialog_title="儲存寫作引用導引",
            file_name="writing_guide.md",
            allowed_extensions=["md"],
        )

    def on_export_path_selected(self, e):
        if not e.path or not self._last_guides or not self.service:
            return
        try:
            self.service.export_guide_to_markdown(self._last_guides, e.path)
            self.status_text.value = f"已匯出到：{e.path}"
        except Exception as ex:
            self.status_text.value = f"匯出失敗：{ex}"
        self.page.update()
