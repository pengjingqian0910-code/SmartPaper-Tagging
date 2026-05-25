"""
寫作引用導引視圖 — 左右分欄布局
左側：大綱輸入 + 步驟控制
右側：結果展示（大空間）
"""

import threading
import flet as ft
from typing import Optional

from ...database.sqlite_db import SQLiteDB
from ...database.vector_db import VectorDB
from ...models import Paper
from ...services.writing_guide import (
    WritingGuideService, SectionGuide, OutlineEnrichment,
)
from ...services.text_polish import TextPolishService, PolishResult, EvaluationResult
from ...config import GEMINI_API_KEY

# ── 色彩 ──────────────────────────────────────────────────────────────────
_C_BORDER = "#E2E8F0"
_C_BG     = "#F8FAFC"
_C_TITLE  = "#1E293B"
_C_META   = "#64748B"

_STEP_COLORS = [
    ("#6366F1", "#EEF2FF", "#C7D2FE"),   # Step 1 — indigo
    ("#0D9488", "#F0FDFA", "#99F6E4"),   # Step 2 — teal
    ("#7C3AED", "#F5F3FF", "#DDD6FE"),   # Step 3 — violet
]

_POS_COLORS = {
    "段落開頭": ("#DCFCE7", "#15803D"),
    "中間論述": ("#DBEAFE", "#1D4ED8"),
    "結尾總結": ("#F3E8FF", "#7E22CE"),
}


class WritingGuideView:

    def __init__(self, page: ft.Page):
        self.page = page
        self.service: Optional[WritingGuideService] = None
        self._last_guides: list[SectionGuide] = []
        self._section_candidates: dict[str, list[dict]] = {}
        self._candidate_checks: dict[str, dict[int, ft.Checkbox]] = {}
        self._enrichment_result: Optional[OutlineEnrichment] = None
        self._sqlite_db = SQLiteDB()
        self._vector_db = VectorDB()

    def build(self) -> ft.Control:
        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self.on_export_path_selected
        self.page.overlay.append(self.file_picker)

        return ft.Tabs(
            selected_index=0,
            animation_duration=200,
            tabs=[
                ft.Tab(
                    tab_content=ft.Row([
                        ft.Icon("edit_note", size=14),
                        ft.Text("引用導引", size=13),
                    ], spacing=6),
                    content=ft.Container(
                        content=self._build_citation_tab(),
                        expand=True,
                    ),
                ),
                ft.Tab(
                    tab_content=ft.Row([
                        ft.Icon("auto_fix_high", size=14),
                        ft.Text("文稿潤色", size=13),
                    ], spacing=6),
                    content=ft.Container(
                        content=self._build_polish_tab(),
                        expand=True,
                    ),
                ),
            ],
            expand=True,
        )

    # ── Tab 0：引用導引（原有功能）────────────────────────────────────
    def _build_citation_tab(self) -> ft.Control:
        self.outline_input = ft.TextField(
            label="寫作大綱（每行一個段落）",
            hint_text=(
                "例如：\n"
                "引言：深度學習在醫療影像的背景\n"
                "相關工作：現有方法與局限\n"
                "方法：提出的模型架構\n"
                "實驗：評測結果與分析"
            ),
            multiline=True, min_lines=8, max_lines=20,
            expand=True,
            text_size=13,
        )

        self.n_candidates_dropdown = ft.Dropdown(
            label="每段候選論文數",
            value="8",
            options=[
                ft.dropdown.Option("5",  "5 篇（快速）"),
                ft.dropdown.Option("8",  "8 篇（推薦）"),
                ft.dropdown.Option("12", "12 篇（完整）"),
            ],
        )

        self._step_handlers = [
            self.run_find_candidates,
            self.run_analyze,
            self.run_enrichment,
        ]
        self.find_btn    = self._step_btn(1, "搜尋候選論文", "search",           self.run_find_candidates)
        self.analyze_btn = self._step_btn(2, "AI 分析引用",  "auto_awesome",     self.run_analyze,    disabled=True)
        self.enrich_btn  = self._step_btn(3, "缺口補強 + 寫作範例", "lightbulb", self.run_enrichment, disabled=True)

        self.export_btn = ft.TextButton(
            "匯出 Markdown", icon="download",
            on_click=self.export_guide, visible=False,
            style=ft.ButtonStyle(color=_C_META),
        )

        self.progress_ring = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)
        self.status_text   = ft.Text("", size=12, color=_C_META)

        if not GEMINI_API_KEY:
            self.status_text.value = "未設定 Gemini API Key — AI 功能停用"
            self.status_text.color = ft.colors.ORANGE_700

        left_panel = ft.Container(
            content=ft.Column([
                ft.Text("引用導引", size=18, weight=ft.FontWeight.BOLD, color=_C_TITLE),
                ft.Text("輸入大綱，逐步取得引用建議與缺口分析", size=12, color=_C_META),
                ft.Divider(height=8, color=_C_BORDER),
                self.outline_input,
                ft.Divider(height=4, color=_C_BORDER),
                self.n_candidates_dropdown,
                ft.Column([self.find_btn, self.analyze_btn, self.enrich_btn], spacing=8),
                ft.Row([self.progress_ring, self.status_text], spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.export_btn,
            ], spacing=12, expand=True),
            width=330,
            padding=ft.padding.only(left=16, right=12, top=16, bottom=16),
        )

        self.results_container = ft.Column(
            scroll=ft.ScrollMode.AUTO, expand=True, spacing=12,
        )
        self._results_placeholder = ft.Container(
            content=ft.Column([
                ft.Icon("edit_document", size=48, color="#CBD5E1"),
                ft.Text("結果將顯示在此", size=14, color="#CBD5E1"),
                ft.Text("請先在左側輸入大綱，依序執行步驟", size=12, color="#CBD5E1"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            alignment=ft.alignment.center, expand=True,
        )
        self.results_container.controls.append(self._results_placeholder)

        right_panel = ft.Container(
            content=self.results_container,
            expand=True,
            padding=ft.padding.only(left=8, right=16, top=16, bottom=16),
            border=ft.border.only(left=ft.BorderSide(1, _C_BORDER)),
        )

        return ft.Row([left_panel, right_panel], expand=True, spacing=0)

    # ── Tab 1：文稿潤色 ───────────────────────────────────────────────
    def _build_polish_tab(self) -> ft.Control:
        self._polish_service: Optional[TextPolishService] = None
        self._polish_result: Optional[PolishResult] = None

        # ── 左側輸入 ──────────────────────────────────────────────────
        self._polish_input = ft.TextField(
            label="貼入草稿段落",
            hint_text=(
                "貼入你已寫好的段落或句子，AI 將：\n"
                "• 改寫為學術英文語氣\n"
                "• 逐句批注改動理由\n"
                "• 從文獻庫推薦可插入的引用\n"
                "• 偵測現有引用並推薦文庫中更佳的替代論文"
            ),
            multiline=True, min_lines=10, max_lines=25,
            expand=True, text_size=13,
        )

        self._polish_progress = ft.ProgressRing(
            visible=False, width=18, height=18, stroke_width=2,
        )
        self._polish_status = ft.Text("", size=12, color=_C_META)

        self._eval_btn = ft.ElevatedButton(
            "評估草稿",
            icon="assessment",
            on_click=self._run_evaluate,
            style=ft.ButtonStyle(bgcolor="#6366F1", color="#FFFFFF"),
        )
        # 「確認，開始潤色」按鈕只在評估完成後顯示
        self._confirm_polish_btn = ft.ElevatedButton(
            "確認，開始潤色",
            icon="auto_fix_high",
            on_click=self._run_polish,
            visible=False,
            style=ft.ButtonStyle(bgcolor="#7C3AED", color="#FFFFFF"),
        )

        left_panel = ft.Container(
            content=ft.Column([
                ft.Text("文稿潤色", size=18, weight=ft.FontWeight.BOLD, color=_C_TITLE),
                ft.Text("提升學術語氣，自動插入引用，偵測現有引用並推薦更佳替代", size=12, color=_C_META),
                ft.Divider(height=8, color=_C_BORDER),
                self._polish_input,
                ft.Divider(height=4, color=_C_BORDER),
                self._eval_btn,
                self._confirm_polish_btn,
                ft.Row([self._polish_progress, self._polish_status], spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12, expand=True),
            width=330,
            padding=ft.padding.only(left=16, right=12, top=16, bottom=16),
        )

        # ── 右側結果 ──────────────────────────────────────────────────
        self._polish_results = ft.Column(
            scroll=ft.ScrollMode.AUTO, expand=True, spacing=14,
        )
        self._polish_placeholder = ft.Container(
            content=ft.Column([
                ft.Icon("auto_fix_high", size=48, color="#CBD5E1"),
                ft.Text("潤色結果將顯示在此", size=14, color="#CBD5E1"),
                ft.Text("在左側貼入草稿後點擊「分析並潤色」", size=12, color="#CBD5E1"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            alignment=ft.alignment.center, expand=True,
        )
        self._polish_results.controls.append(self._polish_placeholder)

        right_panel = ft.Container(
            content=self._polish_results,
            expand=True,
            padding=ft.padding.only(left=8, right=16, top=16, bottom=16),
            border=ft.border.only(left=ft.BorderSide(1, _C_BORDER)),
        )

        return ft.Row([left_panel, right_panel], expand=True, spacing=0)

    # ── 執行評估 ──────────────────────────────────────────────────────
    def _run_evaluate(self, _e):
        text = (self._polish_input.value or "").strip()
        if not text:
            self._polish_status.value = "請先貼入草稿文字"
            self.page.update()
            return

        self._polish_progress.visible = True
        self._polish_status.value = "AI 評估草稿中…"
        self._confirm_polish_btn.visible = False
        self._polish_results.controls.clear()
        self.page.update()

        def _run():
            try:
                if self._polish_service is None:
                    self._polish_service = TextPolishService(
                        sqlite_db=self._sqlite_db,
                        vector_db=self._vector_db,
                    )
                result = self._polish_service.evaluate(text)
                self._polish_results.controls.clear()
                self._polish_results.controls.append(
                    self._build_evaluation_card(result)
                )
                self._confirm_polish_btn.visible = True
                self._polish_status.value = "評估完成，確認後可開始潤色"
            except Exception as ex:
                self._polish_status.value = f"評估失敗：{ex}"
            finally:
                self._polish_progress.visible = False
                self.page.update()

        threading.Thread(target=_run, daemon=True).start()

    def _build_evaluation_card(self, ev: EvaluationResult) -> ft.Control:
        def _score_bar(label: str, score: int, color: str) -> ft.Control:
            filled = max(0, min(10, score))
            bar_color = (
                "#16A34A" if filled >= 7 else
                "#D97706" if filled >= 4 else
                "#DC2626"
            )
            return ft.Row([
                ft.Text(label, size=11, color=_C_META, width=110),
                ft.Row(
                    [
                        ft.Container(
                            width=18, height=10,
                            bgcolor=bar_color if i < filled else "#E5E7EB",
                            border_radius=2,
                        )
                        for i in range(10)
                    ],
                    spacing=2,
                ),
                ft.Text(f"{filled}/10", size=11, color=bar_color,
                        weight=ft.FontWeight.W_600),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        def _list_section(icon: str, title: str, items: list[str],
                          icon_color: str, bg: str, border: str) -> ft.Control:
            if not items:
                return ft.Container()
            rows = [
                ft.Row([
                    ft.Icon(icon, size=12, color=icon_color),
                    ft.Text(item, size=11, color=_C_TITLE, expand=True),
                ], spacing=6)
                for item in items
            ]
            return ft.Container(
                content=ft.Column([
                    ft.Text(title, size=11, weight=ft.FontWeight.W_600,
                            color=icon_color),
                    *rows,
                ], spacing=5),
                bgcolor=bg,
                border=ft.border.all(1, border),
                border_radius=8,
                padding=10,
            )

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("assessment", size=15, color="#6366F1"),
                    ft.Text("Draft Evaluation Report", size=13,
                            weight=ft.FontWeight.W_600, color="#4338CA"),
                ], spacing=6),
                ft.Text(ev.overall_summary, size=12, color=_C_TITLE),
                ft.Divider(height=4, color="#C7D2FE"),
                _score_bar("Academic Tone",    ev.academic_score,  "#6366F1"),
                _score_bar("Clarity",          ev.clarity_score,   "#6366F1"),
                _score_bar("Citation Adequacy", ev.citation_score, "#6366F1"),
                ft.Divider(height=4, color="#C7D2FE"),
                _list_section(
                    "check_circle", "Strengths", ev.strengths,
                    "#16A34A", "#F0FDF4", "#BBF7D0",
                ),
                _list_section(
                    "warning_amber", "Issues Found", ev.issues,
                    "#DC2626", "#FEF2F2", "#FECACA",
                ),
                _list_section(
                    "auto_fix_high", "What Polish Will Improve",
                    ev.expected_improvements,
                    "#7C3AED", "#F5F3FF", "#DDD6FE",
                ),
            ], spacing=10),
            padding=16,
            border=ft.border.all(2, "#C7D2FE"),
            border_radius=12,
            bgcolor="#EEF2FF",
        )

    # ── 執行潤色 ──────────────────────────────────────────────────────
    def _run_polish(self, _e):
        text = (self._polish_input.value or "").strip()
        if not text:
            self._polish_status.value = "請先貼入草稿文字"
            self.page.update()
            return

        self._polish_progress.visible = True
        self._polish_status.value = "潤色中…"
        self._confirm_polish_btn.visible = False
        self._polish_results.controls.clear()
        self.page.update()

        def _run():
            try:
                if self._polish_service is None:
                    self._polish_service = TextPolishService(
                        sqlite_db=self._sqlite_db,
                        vector_db=self._vector_db,
                    )

                def prog(msg: str):
                    self._polish_status.value = msg
                    self.page.update()

                result = self._polish_service.polish(text, progress_callback=prog)
                self._polish_result = result
                self._polish_results.controls.clear()
                self._polish_results.controls.append(
                    self._build_polish_result_card(text, result)
                )
            except Exception as ex:
                self._polish_status.value = f"失敗：{ex}"
                self._polish_results.controls.clear()
                self._polish_results.controls.append(
                    self._polish_placeholder
                )
            finally:
                self._polish_progress.visible = False
                self.page.update()

        threading.Thread(target=_run, daemon=True).start()

    def _build_polish_result_card(self, original: str, result: PolishResult) -> ft.Control:
        violet = "#7C3AED"
        violet_bg = "#F5F3FF"
        violet_border = "#DDD6FE"
        teal = "#0D9488"
        teal_bg = "#F0FDFA"
        teal_border = "#99F6E4"

        # ── 1. 對照顯示（原文 vs 潤色版）────────────────────────────
        comparison = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("compare_arrows", size=14, color=violet),
                    ft.Text("Before / After", size=13,
                            weight=ft.FontWeight.W_600, color=violet),
                ], spacing=6),
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Original Draft", size=11,
                                    color=_C_META, weight=ft.FontWeight.W_600),
                            ft.Container(
                                content=ft.Text(original, size=12, color="#374151",
                                                selectable=True),
                                bgcolor="#F9FAFB",
                                border=ft.border.only(left=ft.BorderSide(3, "#9CA3AF")),
                                padding=ft.padding.only(left=10, top=8, bottom=8, right=8),
                                border_radius=4,
                            ),
                        ], spacing=6),
                        expand=True,
                    ),
                    ft.Container(width=12),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Polished Version", size=11,
                                    color=violet, weight=ft.FontWeight.W_600),
                            ft.Container(
                                content=ft.Text(result.polished_text, size=12,
                                                color="#1E1B4B", selectable=True),
                                bgcolor=violet_bg,
                                border=ft.border.only(left=ft.BorderSide(3, violet)),
                                padding=ft.padding.only(left=10, top=8, bottom=8, right=8),
                                border_radius=4,
                            ),
                        ], spacing=6),
                        expand=True,
                    ),
                ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.START),
            ], spacing=10),
            padding=14,
            border=ft.border.all(1, violet_border),
            border_radius=12,
            bgcolor="#FAFAFA",
        )

        # ── 2. 逐句批注 ───────────────────────────────────────────────
        annotation_ctrl = ft.Container()
        if result.sentence_notes:
            note_rows = []
            for note in result.sentence_notes:
                note_rows.append(ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("remove_circle_outline", size=11, color="#DC2626"),
                            ft.Text(note.original, size=11, color="#7F1D1D",
                                    selectable=True, expand=True),
                        ], spacing=6),
                        ft.Row([
                            ft.Icon("add_circle_outline", size=11, color="#16A34A"),
                            ft.Text(note.polished, size=11, color="#14532D",
                                    selectable=True, expand=True),
                        ], spacing=6),
                        ft.Row([
                            ft.Icon("info_outline", size=11, color=_C_META),
                            ft.Text(note.comment, size=10, color=_C_META,
                                    expand=True),
                        ], spacing=6),
                    ], spacing=4),
                    padding=10,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=6,
                ))

            annotation_ctrl = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("rate_review", size=14, color=violet),
                        ft.Text("Sentence-Level Annotations", size=13,
                                weight=ft.FontWeight.W_600, color=violet),
                        _chip(f"{len(result.sentence_notes)} notes", violet),
                    ], spacing=6),
                    ft.Text("Red = original  ·  Green = improved  ·  Grey = reason",
                            size=10, color=_C_META),
                    *note_rows,
                ], spacing=8),
                padding=14,
                border=ft.border.all(1, violet_border),
                border_radius=12,
                bgcolor=violet_bg,
            )

        # ── 3. 引用建議（從文庫） ─────────────────────────────────────
        cite_ctrl = ft.Container()
        if result.citation_suggestions:
            cite_rows = []
            for cs in result.citation_suggestions:
                auth = (cs.paper.authors[0] + " et al."
                        if (cs.paper.authors and len(cs.paper.authors) > 1)
                        else (cs.paper.authors[0] if cs.paper.authors else "?"))
                cite_rows.append(ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("menu_book", size=12, color=teal),
                            ft.Text(cs.paper.title, size=12,
                                    weight=ft.FontWeight.W_600,
                                    color="#0F766E", expand=True),
                            ft.Text(f"({cs.paper.year or '?'})",
                                    size=10, color=_C_META),
                        ], spacing=6),
                        ft.Row([
                            ft.Text("Where:", size=10, color=_C_META,
                                    weight=ft.FontWeight.W_600),
                            ft.Text(cs.location_hint, size=10,
                                    color=_C_TITLE, expand=True),
                        ], spacing=4),
                        ft.Row([
                            ft.Text("Tags:", size=10, color=_C_META,
                                    weight=ft.FontWeight.W_600),
                            ft.Text(cs.relevance_reason, size=10,
                                    color=_C_META, expand=True),
                        ], spacing=4),
                    ], spacing=4),
                    padding=10,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, teal_border),
                    border_radius=6,
                ))

            cite_ctrl = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("add_link", size=14, color=teal),
                        ft.Text("Citation Suggestions from Library", size=13,
                                weight=ft.FontWeight.W_600, color=teal),
                        _chip(f"{len(result.citation_suggestions)} papers", teal),
                    ], spacing=6),
                    ft.Text("Papers in your library relevant to this text's key topics",
                            size=10, color=_C_META),
                    *cite_rows,
                ], spacing=8),
                padding=14,
                border=ft.border.all(1, teal_border),
                border_radius=12,
                bgcolor=teal_bg,
            )

        # ── 4. 現有引用替代推薦 ───────────────────────────────────────
        alt_ctrl = ft.Container()
        if result.alternative_papers:
            alt_rows = []
            for alt in result.alternative_papers:
                alt_rows.append(ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("You cited:", size=10, color=_C_META,
                                    weight=ft.FontWeight.W_600),
                            ft.Container(
                                content=ft.Text(alt.cited_ref, size=10,
                                                color="#92400E"),
                                bgcolor="#FEF3C7", border_radius=4,
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            ),
                        ], spacing=6),
                        ft.Row([
                            ft.Icon("swap_horiz", size=12, color="#D97706"),
                            ft.Text("Library alternative:", size=10,
                                    color=_C_META, weight=ft.FontWeight.W_600),
                            ft.Text(
                                f"{alt.paper.title[:55]}{'…' if len(alt.paper.title) > 55 else ''} ({alt.paper.year or '?'})",
                                size=11, color="#92400E", expand=True,
                                weight=ft.FontWeight.W_500,
                            ),
                        ], spacing=6),
                        ft.Text(alt.reason, size=10, color=_C_META),
                    ], spacing=4),
                    padding=10,
                    bgcolor="#FFFBEB",
                    border=ft.border.all(1, "#FDE68A"),
                    border_radius=6,
                ))

            alt_ctrl = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("swap_horiz", size=14, color="#D97706"),
                        ft.Text("Library Alternatives for Detected Citations", size=13,
                                weight=ft.FontWeight.W_600, color="#92400E"),
                        _chip(f"{len(result.alternative_papers)} found", "#D97706"),
                    ], spacing=6),
                    ft.Text("Citations detected in your draft — your library may have better-fit papers",
                            size=10, color=_C_META),
                    *alt_rows,
                ], spacing=8),
                padding=14,
                border=ft.border.all(1, "#FDE68A"),
                border_radius=12,
                bgcolor="#FFFBEB",
            )

        return ft.Column([
            comparison,
            annotation_ctrl,
            cite_ctrl,
            alt_ctrl,
        ], spacing=14)

    # ── 步驟按鈕工廠 ────────────────────────────────────────────────────

    def _step_btn(self, step: int, label: str, icon: str,
                  on_click, disabled: bool = False) -> ft.Control:
        color, bg, border_c = _STEP_COLORS[step - 1]
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text(str(step), size=12, weight=ft.FontWeight.BOLD,
                                    color="#FFFFFF"),
                    bgcolor=color if not disabled else "#94A3B8",
                    width=24, height=24, border_radius=12,
                    alignment=ft.alignment.center,
                ),
                ft.Icon(icon, size=15, color=color if not disabled else "#94A3B8"),
                ft.Text(label, size=13, weight=ft.FontWeight.W_500,
                        color=color if not disabled else "#94A3B8"),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=bg if not disabled else "#F8FAFC",
            border=ft.border.all(1, border_c if not disabled else "#E2E8F0"),
            border_radius=8,
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            on_click=on_click if not disabled else None,
            ink=not disabled,
        )

    def _refresh_step_btn(self, btn_container: ft.Container, step: int, disabled: bool):
        color, bg, border_c = _STEP_COLORS[step - 1]
        row = btn_container.content
        circle, icon_ctrl, label_ctrl = row.controls
        circle.bgcolor        = "#94A3B8" if disabled else color
        icon_ctrl.color       = "#94A3B8" if disabled else color
        label_ctrl.color      = "#94A3B8" if disabled else color
        btn_container.bgcolor = "#F8FAFC" if disabled else bg
        btn_container.border  = ft.border.all(1, "#E2E8F0" if disabled else border_c)
        btn_container.on_click = None if disabled else self._step_handlers[step - 1]
        btn_container.ink      = not disabled

    # ── 工具 ────────────────────────────────────────────────────────────

    def _parse_outline(self) -> list[str]:
        raw = self.outline_input.value or ""
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _set_busy(self, msg: str):
        self.progress_ring.visible = True
        self.status_text.value = msg
        self._disable_steps(True, True, True)
        self.page.update()

    def _set_idle(self):
        self.progress_ring.visible = False
        self.page.update()

    def _disable_steps(self, s1: bool, s2: bool, s3: bool):
        for btn, step, disabled in [
            (self.find_btn,    1, s1),
            (self.analyze_btn, 2, s2),
            (self.enrich_btn,  3, s3),
        ]:
            self._refresh_step_btn(btn, step, disabled)

    def _clear_placeholder(self):
        if self._results_placeholder in self.results_container.controls:
            self.results_container.controls.remove(self._results_placeholder)

    # ── Step 1：搜尋候選論文 ──────────────────────────────────────────

    def run_find_candidates(self, _e):
        sections = self._parse_outline()
        if not sections:
            self.status_text.value = "請輸入至少一個段落描述"
            self.page.update()
            return

        self._set_busy("搜尋候選論文中…")
        self.export_btn.visible = False
        self.results_container.controls.clear()
        self.results_container.controls.append(self._results_placeholder)
        self._section_candidates.clear()
        self._candidate_checks.clear()
        self._last_guides = []
        self._enrichment_result = None
        self.page.update()

        def _run():
            try:
                n = int(self.n_candidates_dropdown.value or "8")
                self.service = WritingGuideService()

                self._clear_placeholder()
                for idx, section in enumerate(sections, 1):
                    self.status_text.value = f"搜尋 {idx}/{len(sections)}：{section[:28]}…"
                    self.page.update()
                    candidates = self.service.find_section_candidates(section, n)
                    self._section_candidates[section] = candidates
                    card, checks = self._build_confirm_card(idx, section, candidates)
                    self._candidate_checks[section] = checks
                    self.results_container.controls.append(card)
                    self.page.update()

                total = sum(len(v) for v in self._section_candidates.values())
                self.status_text.value = (
                    f"找到 {total} 篇候選（{len(sections)} 段）。確認後執行步驟 2。"
                )
                self._disable_steps(False, total == 0, True)
            except Exception as ex:
                self.status_text.value = f"搜尋失敗：{ex}"
                self._disable_steps(False, True, True)
            finally:
                self._set_idle()

        threading.Thread(target=_run, daemon=True).start()

    def _build_confirm_card(self, index, section, candidates):
        checks: dict[int, ft.Checkbox] = {}

        if not candidates:
            return ft.Container(
                content=ft.Row([
                    _step_badge(str(index), "#94A3B8"),
                    ft.Text(section, size=13, weight=ft.FontWeight.W_600, expand=True),
                    ft.Text("找不到相關論文", size=11, color=_C_META),
                ], spacing=8),
                padding=12, border=ft.border.all(1, _C_BORDER),
                border_radius=8, bgcolor=_C_BG,
            ), checks

        rows = []
        for c in candidates:
            paper = c["paper"]
            score = c.get("rerank_score", c.get("score", 0.0))
            cb = ft.Checkbox(value=True)
            checks[paper.id] = cb
            rows.append(ft.Row([
                cb,
                ft.Column([
                    ft.Text(
                        paper.title,
                        size=12, weight=ft.FontWeight.W_500,
                    ),
                    ft.Row([
                        _chip(f"{score:.2f}", "#6366F1"),
                        _chip(str(paper.year or ""), _C_META),
                        _chip((paper.venue or "")[:24], _C_META),
                        *([_chip(paper.tags[0], "#0D9488")] if paper.tags else []),
                    ], spacing=4),
                ], spacing=2, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        def _toggle_all(e, _c=checks):
            for cb in _c.values():
                cb.value = e.control.value
            self.page.update()

        color, bg, border_c = _STEP_COLORS[0]
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    _step_badge(str(index), color),
                    ft.Text(section, size=13, weight=ft.FontWeight.W_600,
                            expand=True, color=_C_TITLE),
                    ft.Text(f"{len(candidates)} 篇", size=11, color=_C_META),
                    ft.Checkbox(value=True, label="全選", on_change=_toggle_all),
                ], spacing=8),
                ft.Divider(height=2, color=border_c),
                *rows,
            ], spacing=6),
            padding=14, border=ft.border.all(1, border_c),
            border_radius=10, bgcolor=bg,
        ), checks

    # ── Step 2：AI 分析引用 ───────────────────────────────────────────

    def run_analyze(self, _e):
        if not self._section_candidates:
            self.status_text.value = "請先執行步驟 1"
            self.page.update()
            return

        self._set_busy("AI 分析引用中…")
        self.results_container.controls.clear()
        self.export_btn.visible = False
        self.page.update()

        def _run():
            try:
                guides = []
                sections = list(self._section_candidates.keys())
                for idx, section in enumerate(sections, 1):
                    self.status_text.value = f"AI 分析 {idx}/{len(sections)}：{section[:28]}…"
                    self.page.update()

                    checks = self._candidate_checks.get(section, {})
                    all_c  = self._section_candidates[section]
                    selected = [c for c in all_c
                                if checks.get(c["paper"].id, ft.Checkbox(value=True)).value]
                    if not selected:
                        selected = all_c

                    guide = self.service.analyze_from_candidates(section, selected)
                    guides.append(guide)
                    self.results_container.controls.append(
                        self._build_section_card(idx, guide)
                    )
                    self.page.update()

                self._last_guides = guides
                cited = sum(len(g.citations) for g in guides)
                self.status_text.value = (
                    f"分析完成：{len(guides)} 個段落，共 {cited} 篇引用。可繼續執行步驟 3。"
                )
                self.export_btn.visible = True
                self._disable_steps(False, False, len(guides) == 0)
            except Exception as ex:
                self.status_text.value = f"AI 分析失敗：{ex}"
                self._disable_steps(False, False, True)
            finally:
                self._set_idle()

        threading.Thread(target=_run, daemon=True).start()

    def _build_section_card(self, index: int, guide: SectionGuide) -> ft.Control:
        color, bg, border_c = _STEP_COLORS[1]

        hint_ctrl = ft.Container()
        if guide.writing_hint:
            hint_ctrl = ft.Container(
                content=ft.Row([
                    ft.Icon("lightbulb_outline", size=13, color="#B45309"),
                    ft.Text(guide.writing_hint, size=12, color="#92400E", expand=True),
                ], spacing=6),
                bgcolor="#FFFBEB", border_radius=6,
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
            )

        tiles = []
        for c in (guide.citations or []):
            pos_bg, pos_fg = _POS_COLORS.get(c.cite_position, ("#F1F5F9", "#475569"))
            example_body = c.writing_example or (
                f"[{c.cite_position}] {c.key_concept} — {c.cite_reason}"
            )
            tiles.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("article", size=13, color="#2563EB"),
                        ft.Text(
                            c.paper.title,
                            size=12, weight=ft.FontWeight.W_600, expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(c.cite_position, size=10, color=pos_fg),
                            bgcolor=pos_bg, border_radius=10,
                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                        ),
                    ], spacing=8),
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Icon("edit_note", size=13, color="#1D4ED8"),
                                ft.Text("Writing Example", size=11, color="#1E40AF",
                                        weight=ft.FontWeight.W_600),
                            ], spacing=4),
                            ft.Container(
                                content=ft.Text(
                                    example_body,
                                    size=12, color="#1E3A5F",
                                    selectable=True,
                                ),
                                bgcolor="#EFF6FF",
                                border=ft.border.only(left=ft.BorderSide(3, "#3B82F6")),
                                padding=ft.padding.only(left=12, top=8, bottom=8, right=10),
                                border_radius=4,
                            ),
                        ], spacing=6),
                    ),
                    *(
                        [ft.Row([
                            _chip(tag, "#64748B") for tag in (c.paper.tags or [])[:4]
                        ], spacing=4)]
                        if c.paper.tags else []
                    ),
                ], spacing=6),
                padding=10,
                border=ft.border.all(1, "#BFDBFE"),
                border_radius=6, bgcolor="#FFFFFF",
            ))

        if not tiles:
            tiles.append(ft.Container(
                content=ft.Text(
                    "未找到相關引用，建議補充文獻或調整段落描述。",
                    size=12, color=_C_META,
                ),
                padding=ft.padding.symmetric(horizontal=4, vertical=6),
            ))

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    _step_badge(str(index), color),
                    ft.Text(guide.section, size=14, weight=ft.FontWeight.W_600,
                            expand=True, color=_C_TITLE),
                    ft.Text(f"{len(guide.citations)} 篇引用", size=11, color=_C_META),
                ], spacing=10),
                hint_ctrl,
                *tiles,
            ], spacing=8),
            padding=14, border=ft.border.all(1, border_c),
            border_radius=10, bgcolor=bg,
        )

    # ── Step 3：缺口補強 ──────────────────────────────────────────────

    def run_enrichment(self, _e):
        if not self._last_guides:
            self.status_text.value = "請先完成步驟 2"
            self.page.update()
            return

        sections = self._parse_outline()
        self._set_busy("AI 分析大綱缺口…")
        self.page.update()

        def _run():
            try:
                def prog(msg):
                    self.status_text.value = msg
                    self.page.update()

                enrichment = self.service.generate_enrichment(
                    sections=sections,
                    guides=self._last_guides,
                    progress_callback=prog,
                )
                self._enrichment_result = enrichment
                self.results_container.controls.append(
                    self._build_enrichment_card(enrichment, self._last_guides)
                )
                self.page.update()
                n_q = len(enrichment.follow_up_questions)
                n_g = len(enrichment.concept_gaps)
                self.status_text.value = (
                    f"完成：{n_q} 個追問建議，{n_g} 個概念缺口"
                    if (n_q or n_g) else "缺口補強完成"
                )
                self.export_btn.visible = True
                self._disable_steps(False, False, False)
            except Exception as ex:
                self.status_text.value = f"步驟 3 失敗：{ex}"
                self._disable_steps(False, False, False)
            finally:
                self._set_idle()

        threading.Thread(target=_run, daemon=True).start()

    def _build_synthesis_section(
        self, guides: list[SectionGuide],
    ) -> ft.Control:
        """Step 3 頂部：每個段落的綜述段落（整合所有引用論文，非重複個別範例）"""
        color, bg, border_c = _STEP_COLORS[1]  # teal
        cards = []

        for idx, guide in enumerate(guides, 1):
            if not guide.citations or not guide.synthesis_paragraph:
                continue

            paper_chips = ft.Row([
                _chip(
                    c.paper.title[:28] + ("…" if len(c.paper.title) > 28 else ""),
                    "#0D9488",
                ) for c in guide.citations
            ], spacing=4, wrap=True)

            cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        _step_badge(str(idx), color),
                        ft.Text(guide.section, size=13,
                                weight=ft.FontWeight.W_600,
                                color=_C_TITLE, expand=True),
                        _chip(f"{len(guide.citations)} papers", color),
                    ], spacing=8),
                    paper_chips,
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Icon("auto_stories", size=13, color="#0F766E"),
                                ft.Text("Synthesized Paragraph", size=11,
                                        color="#0F766E",
                                        weight=ft.FontWeight.W_600),
                            ], spacing=4),
                            ft.Container(
                                content=ft.Text(
                                    guide.synthesis_paragraph,
                                    size=12, color="#134E4A",
                                    selectable=True,
                                ),
                                bgcolor="#F0FDFA",
                                border=ft.border.only(
                                    left=ft.BorderSide(3, "#0D9488")),
                                padding=ft.padding.only(
                                    left=12, top=8, bottom=8, right=10),
                                border_radius=4,
                            ),
                        ], spacing=6),
                    ),
                ], spacing=8),
                padding=12,
                border=ft.border.all(1, border_c),
                border_radius=10,
                bgcolor=bg,
            ))

        if not cards:
            return ft.Container()

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("auto_stories", color=color, size=15),
                    ft.Text("Synthesized Literature Review",
                            size=13, weight=ft.FontWeight.W_600, color="#0D9488"),
                    ft.Text("— all cited papers woven into cohesive paragraphs",
                            size=11, color=_C_META),
                ], spacing=6),
                *cards,
            ], spacing=10),
            padding=14,
            border=ft.border.all(2, border_c),
            border_radius=12,
            bgcolor=bg,
        )

    def _build_enrichment_card(
        self, enrichment: OutlineEnrichment, guides: list[SectionGuide],
    ) -> ft.Control:
        color, bg, border_c = _STEP_COLORS[2]

        # ── 追問區 ──────────────────────────────────────────────────────
        followup_section = ft.Container()
        if enrichment.follow_up_questions:
            q_rows = [
                ft.Row([
                    _step_badge(str(i), color),
                    ft.Text(q, size=12, color="#3B1D8E", expand=True),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
                for i, q in enumerate(enrichment.follow_up_questions, 1)
            ]
            followup_section = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("help_outline", color=color, size=15),
                        ft.Text("追問建議", size=13, weight=ft.FontWeight.W_600,
                                color="#5B21B6"),
                        _chip(f"{len(enrichment.follow_up_questions)} 個", color),
                    ], spacing=6),
                    ft.Text("這些問題指出大綱目前論述不足或需要深化的地方",
                            size=11, color=_C_META),
                    ft.Divider(height=4, color=border_c),
                    *q_rows,
                ], spacing=8),
                bgcolor=bg, border=ft.border.all(1, border_c),
                border_radius=10, padding=14,
            )

        # ── 缺口補強區 ────────────────────────────────────────────────
        gap_tiles = []
        for gap in enrichment.concept_gaps:

            example_ctrl = ft.Container()
            if gap.writing_example:
                parts = gap.writing_example.split("\n💡 ")
                example_text = parts[0]
                tip_text = parts[1] if len(parts) > 1 else ""
                example_ctrl = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("edit_note", size=13, color="#1D4ED8"),
                            ft.Text("寫作範例", size=11, color="#1E40AF",
                                    weight=ft.FontWeight.W_600),
                        ], spacing=4),
                        ft.Container(
                            content=ft.Text(
                                example_text, size=12, color="#1E3A5F",
                                selectable=True,
                            ),
                            bgcolor="#EFF6FF",
                            border=ft.border.only(left=ft.BorderSide(3, "#3B82F6")),
                            padding=ft.padding.only(left=12, top=8, bottom=8, right=10),
                            border_radius=4,
                        ),
                        *(
                            [ft.Row([
                                ft.Icon("place", size=12, color="#7C3AED"),
                                ft.Text(tip_text, size=11, color="#6D28D9"),
                            ], spacing=4)]
                            if tip_text else []
                        ),
                    ], spacing=6),
                )

            # ── 外部論文建議區（arXiv 優先）─────────────────────────────
            external_ctrl = ft.Container()
            if gap.external_suggestions:
                ext_rows = []
                for ext in gap.external_suggestions:
                    ext_title   = ext.get("title", "")
                    ext_year    = ext.get("year") or ""
                    ext_url     = ext.get("url", "")
                    ext_abs     = (ext.get("abstract") or "")[:220]
                    ext_authors = ext.get("authors", [])
                    ext_source  = ext.get("source", "arXiv")
                    src_color   = "#2563EB" if ext_source == "Semantic Scholar" else "#7C3AED"
                    src_bg      = "#EFF6FF" if ext_source == "Semantic Scholar" else "#F5F3FF"
                    src_border  = "#BFDBFE" if ext_source == "Semantic Scholar" else "#DDD6FE"

                    def _make_import_handler(e_ext=ext):
                        def _import(e):
                            self._import_arxiv_paper(e_ext, e.control)
                        return _import

                    add_btn = ft.OutlinedButton(
                        "加入文獻庫",
                        icon="add_circle_outline",
                        on_click=_make_import_handler(),
                        style=ft.ButtonStyle(
                            color=src_color,
                            side=ft.BorderSide(1, src_color),
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        ),
                        height=30,
                    )

                    author_str = (
                        ", ".join(ext_authors[:2]) + (" 等" if len(ext_authors) > 2 else "")
                        if ext_authors else ""
                    )

                    ext_rows.append(ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Icon("open_in_new", size=12, color=src_color),
                                ft.Text(
                                    ext_title,
                                    size=12, weight=ft.FontWeight.W_600,
                                    color=src_color, expand=True,
                                    tooltip=ext_url or ext_title,
                                ),
                                ft.Container(
                                    content=ft.Text(ext_source, size=9, color=src_color),
                                    bgcolor=src_bg, border_radius=4,
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                ),
                                ft.Text(str(ext_year), size=10, color=_C_META),
                                add_btn,
                            ], spacing=6,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            *(
                                [ft.Text(author_str, size=10, color=_C_META)]
                                if author_str else []
                            ),
                            ft.Text(ext_abs, size=11, color="#374151"),
                        ], spacing=3),
                        bgcolor=src_bg,
                        border=ft.border.all(1, src_border),
                        border_radius=6,
                        padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    ))

                external_ctrl = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("travel_explore", size=13, color="#7C3AED"),
                            ft.Text("外部高相關論文", size=12,
                                    weight=ft.FontWeight.W_600, color="#5B21B6"),
                            _chip(f"{len(gap.external_suggestions)} 篇", "#7C3AED"),
                            ft.Text("— 點擊右側按鈕可加入文獻庫",
                                    size=10, color=_C_META),
                        ], spacing=6),
                        *ext_rows,
                    ], spacing=6),
                    bgcolor="#FAFAFA",
                    border=ft.border.all(1, "#DDD6FE"),
                    border_radius=8,
                    padding=10,
                )

            gap_tiles.append(ft.Container(
                content=ft.Column([
                    # 概念標頭
                    ft.Row([
                        ft.Container(
                            content=ft.Text(gap.concept, size=11, color="#FFFFFF",
                                            weight=ft.FontWeight.W_600),
                            bgcolor=color, border_radius=8,
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        ),
                        ft.Container(expand=True),
                        ft.Text(f"→ {gap.suggested_section[:35]}",
                                size=10, color=_C_META),
                    ], spacing=8),
                    ft.Text(gap.reason, size=12, color="#374151"),
                    # 1. 外部論文（arXiv/SS 搜尋，可加入文獻庫）
                    external_ctrl,
                    # 2. AI 生成寫作範例（只引用上方外部論文）
                    example_ctrl,
                ], spacing=8),
                padding=12, border=ft.border.all(1, border_c),
                border_radius=8, bgcolor="#FFFFFF",
            ))

        gaps_section = ft.Container()
        if gap_tiles:
            gaps_section = ft.Column([
                ft.Row([
                    ft.Icon("extension", color=color, size=15),
                    ft.Text("概念缺口補強", size=13, weight=ft.FontWeight.W_600,
                            color="#5B21B6"),
                    _chip(f"{len(enrichment.concept_gaps)} 個", color),
                ], spacing=8),
                ft.Text("外部高相關論文（arXiv/SS）→ AI 根據外部文獻生成完整寫作範例（括號引用僅來自上方論文）→ 可一鍵加入文獻庫",
                        size=11, color=_C_META),
                *gap_tiles,
            ], spacing=10)

        synthesis_section = self._build_synthesis_section(guides)

        return ft.Column([
            # ── 綜述段落（整合 Step 2 所有引用，取代重複的個別範例）
            synthesis_section,
            # ── 缺口補強分析
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("auto_fix_high", color=color, size=16),
                        ft.Text("缺口補強分析", size=15, weight=ft.FontWeight.BOLD,
                                color=color),
                    ], spacing=8),
                    followup_section,
                    gaps_section,
                ], spacing=12),
                padding=14,
                border=ft.border.all(2, border_c),
                border_radius=12,
                bgcolor=bg,
            ),
        ], spacing=14)

    # ── 匯入 arXiv 論文 ────────────────────────────────────────────────

    def _import_arxiv_paper(self, ext: dict, btn: ft.Control):
        """將 arXiv 論文加入本地文獻庫（SQLite + ChromaDB）"""
        btn.disabled = True
        btn.text = "匯入中…"
        self.page.update()

        def _run():
            try:
                paper = Paper(
                    title=ext.get("title", ""),
                    abstract=ext.get("abstract"),
                    doi=None,
                    tags=[],
                    authors=ext.get("authors", []),
                    source="arxiv",
                    venue=None,
                    year=ext.get("year"),
                )
                paper_id = self._sqlite_db.insert(paper)
                if paper.abstract:
                    self._vector_db.add(
                        paper_id=paper_id,
                        abstract=paper.abstract,
                        metadata={
                            "title": paper.title,
                            "year": paper.year,
                            "source": "arxiv",
                        },
                    )
                btn.text = "已加入"
                btn.icon = "check_circle"
                btn.style = ft.ButtonStyle(color="#059669")
            except Exception as ex:
                btn.text = "失敗"
                btn.tooltip = str(ex)
            finally:
                self.page.update()

        threading.Thread(target=_run, daemon=True).start()

    # ── 匯出 ────────────────────────────────────────────────────────────

    def export_guide(self, _e):
        self.file_picker.save_file(
            dialog_title="儲存寫作導引",
            file_name="writing_guide.md",
            allowed_extensions=["md"],
        )

    def on_export_path_selected(self, e):
        if not e.path or not self._last_guides or not self.service:
            return
        try:
            self.service.export_guide_to_markdown(self._last_guides, e.path)
            self.status_text.value = f"已匯出：{e.path}"
        except Exception as ex:
            self.status_text.value = f"匯出失敗：{ex}"
        self.page.update()


# ── 共用小元件 ────────────────────────────────────────────────────────────

def _step_badge(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
        bgcolor=color, width=24, height=24,
        border_radius=12, alignment=ft.alignment.center,
    )


def _chip(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=10, color=color),
        padding=ft.padding.symmetric(horizontal=6, vertical=2),
        border=ft.border.all(1, color),
        border_radius=10,
    )
