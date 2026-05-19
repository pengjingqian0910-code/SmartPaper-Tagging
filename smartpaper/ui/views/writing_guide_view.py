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
        # ── 左側：輸入區 ────────────────────────────────────────────────
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
        self.find_btn    = self._step_btn(1, "搜尋候選論文", "search",         self.run_find_candidates)
        self.analyze_btn = self._step_btn(2, "AI 分析引用",  "auto_awesome",   self.run_analyze,   disabled=True)
        self.enrich_btn  = self._step_btn(3, "缺口補強 + 寫作範例", "lightbulb", self.run_enrichment, disabled=True)

        self.export_btn = ft.TextButton(
            "匯出 Markdown", icon="download",
            on_click=self.export_guide, visible=False,
            style=ft.ButtonStyle(color=_C_META),
        )

        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self.on_export_path_selected
        self.page.overlay.append(self.file_picker)

        self.progress_ring = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)
        self.status_text   = ft.Text("", size=12, color=_C_META)

        if not GEMINI_API_KEY:
            self.status_text.value = "未設定 Gemini API Key — AI 功能停用"
            self.status_text.color = ft.colors.ORANGE_700

        left_panel = ft.Container(
            content=ft.Column([
                ft.Text("寫作引用導引", size=20, weight=ft.FontWeight.BOLD, color=_C_TITLE),
                ft.Text("輸入大綱，逐步取得引用建議與缺口分析", size=12, color=_C_META),
                ft.Divider(height=8, color=_C_BORDER),
                self.outline_input,
                ft.Divider(height=4, color=_C_BORDER),
                self.n_candidates_dropdown,
                ft.Column([
                    self.find_btn,
                    self.analyze_btn,
                    self.enrich_btn,
                ], spacing=8),
                ft.Row([self.progress_ring, self.status_text], spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.export_btn,
            ], spacing=12, expand=True),
            width=330,
            padding=ft.padding.only(left=16, right=12, top=16, bottom=16),
        )

        # ── 右側：結果區 ────────────────────────────────────────────────
        self.results_container = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=12,
        )

        self._results_placeholder = ft.Container(
            content=ft.Column([
                ft.Icon("edit_document", size=48, color="#CBD5E1"),
                ft.Text("結果將顯示在此", size=14, color="#CBD5E1"),
                ft.Text("請先在左側輸入大綱，依序執行步驟", size=12, color="#CBD5E1"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            alignment=ft.alignment.center,
            expand=True,
        )
        self.results_container.controls.append(self._results_placeholder)

        right_panel = ft.Container(
            content=self.results_container,
            expand=True,
            padding=ft.padding.only(left=8, right=16, top=16, bottom=16),
            border=ft.border.only(left=ft.BorderSide(1, _C_BORDER)),
        )

        return ft.Row([left_panel, right_panel], expand=True, spacing=0)

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

    def run_find_candidates(self, e):
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
                    ft.Text("找不到相關論文", size=11, color=_C_META, italic=True),
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
                        paper.title[:80] + ("…" if len(paper.title) > 80 else ""),
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

    def run_analyze(self, e):
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
            tiles.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("article", size=13, color="#2563EB"),
                        ft.Text(
                            c.paper.title[:75] + ("…" if len(c.paper.title) > 75 else ""),
                            size=12, weight=ft.FontWeight.W_600, expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(c.cite_position, size=10, color=pos_fg),
                            bgcolor=pos_bg, border_radius=10,
                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                        ),
                    ], spacing=8),
                    ft.Row([
                        ft.Text("引用時機：", size=11, color=_C_META,
                                weight=ft.FontWeight.W_600),
                        ft.Text(c.cite_reason, size=11, color=_C_TITLE, expand=True),
                    ]),
                    ft.Row([
                        ft.Text("引用概念：", size=11, color="#0D9488",
                                weight=ft.FontWeight.W_600),
                        ft.Text(c.key_concept, size=11, color="#0F766E", expand=True),
                    ]),
                    *(
                        [ft.Row([
                            _chip(tag, "#64748B") for tag in (c.paper.tags or [])[:4]
                        ], spacing=4)]
                        if c.paper.tags else []
                    ),
                ], spacing=4),
                padding=10,
                border=ft.border.all(1, "#BFDBFE"),
                border_radius=6, bgcolor="#FFFFFF",
            ))

        if not tiles:
            tiles.append(ft.Container(
                content=ft.Text(
                    "未找到相關引用，建議補充文獻或調整段落描述。",
                    size=12, color=_C_META, italic=True,
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

    def run_enrichment(self, e):
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
                    self._build_enrichment_card(enrichment)
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

    def _build_enrichment_card(self, enrichment: OutlineEnrichment) -> ft.Control:
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
            if gap.paper:
                paper_row = ft.Container(
                    content=ft.Row([
                        ft.Icon("menu_book", size=13, color="#065F46"),
                        ft.Text("對應論文：", size=11, color="#065F46",
                                weight=ft.FontWeight.W_600),
                        ft.Text(
                            gap.paper.title[:60] + ("…" if len(gap.paper.title) > 60 else ""),
                            size=11, color="#047857", expand=True,
                        ),
                        ft.Text(f"({gap.paper.year or '?'})", size=10, color=_C_META),
                    ], spacing=6),
                    bgcolor="#ECFDF5", border_radius=6,
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                )
            else:
                paper_row = ft.Container(
                    content=ft.Row([
                        ft.Icon("warning_amber", size=13, color="#B45309"),
                        ft.Text("文獻庫無對應論文，建議補充外部文獻",
                                size=11, color="#92400E"),
                    ], spacing=6),
                    bgcolor="#FFFBEB", border_radius=6,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                )

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
                                selectable=True, italic=True,
                            ),
                            bgcolor="#EFF6FF",
                            border=ft.border.only(left=ft.BorderSide(3, "#3B82F6")),
                            padding=ft.padding.only(left=12, top=8, bottom=8, right=10),
                            border_radius=4,
                        ),
                        *(
                            [ft.Row([
                                ft.Icon("place", size=12, color="#7C3AED"),
                                ft.Text(tip_text, size=11, color="#6D28D9", italic=True),
                            ], spacing=4)]
                            if tip_text else []
                        ),
                    ], spacing=6),
                )

            # ── 外部論文建議區（Semantic Scholar + arXiv）──────────────
            external_ctrl = ft.Container()
            if gap.external_suggestions:
                ext_rows = []
                for ext in gap.external_suggestions:
                    ext_title   = ext.get("title", "")
                    ext_year    = ext.get("year") or ""
                    ext_url     = ext.get("url", "")
                    ext_abs     = ext.get("abstract", "")
                    ext_authors = ext.get("authors", [])
                    ext_source  = ext.get("source", "arXiv")
                    src_color   = "#2563EB" if ext_source == "Semantic Scholar" else "#7C3AED"

                    def _make_import_handler(e_ext=ext):
                        def _import(e):
                            self._import_arxiv_paper(e_ext, e.control)
                        return _import

                    ext_rows.append(ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Icon("open_in_new", size=12, color=src_color),
                                ft.Text(
                                    ext_title[:70] + ("…" if len(ext_title) > 70 else ""),
                                    size=12, weight=ft.FontWeight.W_500,
                                    color=src_color, expand=True,
                                    tooltip=ext_url or ext_title,
                                ),
                                ft.Container(
                                    content=ft.Text(ext_source, size=9, color=src_color),
                                    bgcolor="#EFF6FF" if ext_source == "Semantic Scholar" else "#F5F3FF",
                                    border_radius=4,
                                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                                ),
                                ft.Text(str(ext_year), size=10, color=_C_META),
                            ], spacing=6),
                            ft.Text(
                                (", ".join(ext_authors[:2]) + (" 等" if len(ext_authors) > 2 else ""))
                                if ext_authors else "",
                                size=10, color=_C_META,
                            ),
                            ft.Row([
                                ft.Text(
                                    (ext_abs[:120] + "…") if len(ext_abs) > 120 else ext_abs,
                                    size=11, color="#374151", expand=True,
                                ),
                                ft.TextButton(
                                    "加入文獻庫",
                                    icon="add_circle_outline",
                                    on_click=_make_import_handler(),
                                    style=ft.ButtonStyle(
                                        color="#7C3AED",
                                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    ),
                                ),
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
                        ], spacing=4),
                        bgcolor="#EFF6FF" if ext_source == "Semantic Scholar" else "#F5F3FF",
                        border=ft.border.all(1, "#BFDBFE" if ext_source == "Semantic Scholar" else "#DDD6FE"),
                        border_radius=6,
                        padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    ))

                external_ctrl = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("travel_explore", size=13, color="#7C3AED"),
                            ft.Text("外部論文建議", size=11,
                                    weight=ft.FontWeight.W_600, color="#5B21B6"),
                            _chip(f"{len(gap.external_suggestions)} 篇", "#7C3AED"),
                        ], spacing=6),
                        *ext_rows,
                    ], spacing=6),
                )

            gap_tiles.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Text(gap.concept, size=11, color="#FFFFFF",
                                            weight=ft.FontWeight.W_600),
                            bgcolor=color, border_radius=8,
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        ),
                        ft.Container(expand=True),
                        ft.Text(f"→ {gap.suggested_section[:35]}",
                                size=10, color=_C_META, italic=True),
                    ], spacing=8),
                    ft.Text(gap.reason, size=11, color=_C_META),
                    paper_row,
                    example_ctrl,
                    external_ctrl,
                ], spacing=6),
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
                ft.Text("補充這些概念可讓大綱更全面，附有文獻庫對應論文、寫作範例，以及 Semantic Scholar / arXiv 外部推薦（可一鍵加入文獻庫）",
                        size=11, color=_C_META),
                *gap_tiles,
            ], spacing=10)

        return ft.Container(
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
        )

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

    def export_guide(self, e):
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
