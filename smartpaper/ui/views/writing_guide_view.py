"""
寫作引用導引視圖
Step 1：搜尋候選論文
Step 2：AI 分析引用建議 + 追問 + 缺口提示
Step 3：缺口補強 — 文獻庫搜尋 + 具體寫作範例
"""

import threading
import flet as ft
from typing import Optional

from ...services.writing_guide import (
    WritingGuideService, SectionGuide, OutlineEnrichment,
)
from ...config import GEMINI_API_KEY

# ── 色彩常數 ──────────────────────────────────────────────────────────────
_C_BORDER  = "#E2E8F0"
_C_BG      = "#F8FAFC"
_C_TITLE   = "#1E293B"
_C_META    = "#64748B"

_POS_COLORS = {
    "段落開頭": ("#DCFCE7", "#15803D"),
    "中間論述": ("#DBEAFE", "#1D4ED8"),
    "結尾總結": ("#F3E8FF", "#7E22CE"),
}


class WritingGuideView:
    """寫作引用導引視圖"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.service: Optional[WritingGuideService] = None
        self.results_container: Optional[ft.Column] = None
        self._last_guides: list[SectionGuide] = []
        self._section_candidates: dict[str, list[dict]] = {}
        self._candidate_checks: dict[str, dict[int, ft.Checkbox]] = {}
        self._enrichment_result: Optional[OutlineEnrichment] = None

    def build(self) -> ft.Control:
        self.outline_input = ft.TextField(
            label="寫作大綱（每行一個段落）",
            hint_text=(
                "例如：\n"
                "1. 引言：深度學習在醫療影像的背景\n"
                "2. 相關工作：現有方法與局限\n"
                "3. 方法：提出的模型架構\n"
                "4. 實驗：評測結果與分析"
            ),
            multiline=True, min_lines=5, max_lines=12, expand=True,
        )

        self.n_candidates_dropdown = ft.Dropdown(
            label="候選論文數", value="8",
            options=[
                ft.dropdown.Option("5",  "5 篇（快速）"),
                ft.dropdown.Option("8",  "8 篇（推薦）"),
                ft.dropdown.Option("12", "12 篇（完整）"),
            ],
            width=160,
        )

        self.find_btn = ft.ElevatedButton(
            "Step 1：搜尋候選論文", icon="search",
            on_click=self.run_find_candidates,
            style=ft.ButtonStyle(bgcolor=ft.colors.INDIGO_600, color=ft.colors.WHITE),
        )
        self.analyze_btn = ft.ElevatedButton(
            "Step 2：AI 分析引用", icon="auto_awesome",
            on_click=self.run_analyze, disabled=True,
            style=ft.ButtonStyle(bgcolor=ft.colors.TEAL_700, color=ft.colors.WHITE),
            tooltip="完成 Step 1 後可執行",
        )
        self.enrich_btn = ft.ElevatedButton(
            "Step 3：缺口補強 + 寫作範例", icon="lightbulb",
            on_click=self.run_enrichment, disabled=True,
            style=ft.ButtonStyle(bgcolor="#7C3AED", color=ft.colors.WHITE),
            tooltip="完成 Step 2 後可執行",
        )
        self.export_btn = ft.OutlinedButton(
            "匯出 Markdown", icon="download",
            on_click=self.export_guide, visible=False,
        )

        self.file_picker = ft.FilePicker()
        self.file_picker.on_result = self.on_export_path_selected
        self.page.overlay.append(self.file_picker)

        self.progress_ring = ft.ProgressRing(visible=False, width=20, height=20,
                                             stroke_width=2)
        self.status_text = ft.Text("", size=12, color=ft.colors.GREY_600)

        if not GEMINI_API_KEY:
            self.status_text.value = "未設定 Gemini API Key — AI 功能停用"
            self.status_text.color = ft.colors.ORANGE_700

        self.results_container = ft.Column(
            scroll=ft.ScrollMode.AUTO, expand=True, spacing=10,
        )

        return ft.Column([
            ft.Text("寫作引用導引", size=24, weight=ft.FontWeight.BOLD, color=_C_TITLE),
            ft.Text(
                "Step 1 搜尋候選→Step 2 AI 引用分析→Step 3 缺口補強 + 寫作範例",
                size=12, color=_C_META,
            ),
            ft.Divider(height=1, color=_C_BORDER),
            self.outline_input,
            ft.Row([
                self.n_candidates_dropdown,
                self.find_btn,
                self.analyze_btn,
                self.enrich_btn,
                self.export_btn,
                self.progress_ring,
                self.status_text,
            ], spacing=10, wrap=True,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=1, color=_C_BORDER),
            ft.Container(
                content=self.results_container,
                expand=True,
                border=ft.border.all(1, _C_BORDER),
                border_radius=8,
                padding=14,
            ),
        ], spacing=10, expand=True)

    # ── 工具 ────────────────────────────────────────────────────────────

    def _parse_outline(self) -> list[str]:
        raw = self.outline_input.value or ""
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _set_busy(self, msg: str):
        self.progress_ring.visible = True
        self.status_text.value = msg
        self.find_btn.disabled = True
        self.analyze_btn.disabled = True
        self.enrich_btn.disabled = True
        self.page.update()

    def _set_idle(self):
        self.progress_ring.visible = False
        self.find_btn.disabled = False
        self.page.update()

    # ── Step 1：搜尋候選論文 ──────────────────────────────────────────

    def run_find_candidates(self, e):
        sections = self._parse_outline()
        if not sections:
            self.status_text.value = "請輸入至少一個段落描述"
            self.page.update()
            return

        self._set_busy("搜尋候選論文中...")
        self.export_btn.visible = False
        self.results_container.controls.clear()
        self._section_candidates.clear()
        self._candidate_checks.clear()
        self._last_guides = []
        self._enrichment_result = None
        self.page.update()

        def _run():
            try:
                n = int(self.n_candidates_dropdown.value or "8")
                self.service = WritingGuideService()

                for idx, section in enumerate(sections, 1):
                    self.status_text.value = (
                        f"搜尋 [{idx}/{len(sections)}] {section[:30]}..."
                    )
                    self.page.update()
                    candidates = self.service.find_section_candidates(section, n)
                    self._section_candidates[section] = candidates
                    card, checks = self._build_confirm_card(idx, section, candidates)
                    self._candidate_checks[section] = checks
                    self.results_container.controls.append(card)

                total = sum(len(v) for v in self._section_candidates.values())
                self.status_text.value = (
                    f"找到 {total} 篇候選（{len(sections)} 段落）。"
                    "確認後點 Step 2 執行 AI 分析。"
                )
                self.analyze_btn.disabled = not bool(total)
            except Exception as ex:
                self.status_text.value = f"搜尋失敗：{ex}"
            finally:
                self._set_idle()
        threading.Thread(target=_run, daemon=True).start()

    def _build_confirm_card(self, index, section, candidates):
        checks: dict[int, ft.Checkbox] = {}

        if not candidates:
            return ft.Container(
                content=ft.Row([
                    _badge(str(index), "#94A3B8"),
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
                        paper.title[:72] + ("…" if len(paper.title) > 72 else ""),
                        size=12, weight=ft.FontWeight.W_500,
                    ),
                    ft.Row([
                        ft.Text(f"相關度 {score:.2f}", size=10, color="#6366F1"),
                        ft.Text(f"  {paper.year or ''}", size=10, color=_C_META),
                        ft.Text(f"  {(paper.venue or '')[:28]}", size=10, color=_C_META),
                        *([ft.Text("  " + "  ".join(paper.tags[:3]), size=10,
                                   color="#0D9488")] if paper.tags else []),
                    ], spacing=0),
                ], spacing=2, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        def _toggle_all(e, _c=checks):
            for cb in _c.values():
                cb.value = e.control.value
            self.page.update()

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    _badge(str(index), "#6366F1"),
                    ft.Text(section, size=13, weight=ft.FontWeight.W_600, expand=True),
                    ft.Text(f"{len(candidates)} 篇", size=11, color=_C_META),
                    ft.Checkbox(value=True, label="全選", on_change=_toggle_all),
                ], spacing=8),
                ft.Divider(height=4, color=_C_BORDER),
                *rows,
            ], spacing=5),
            padding=12, border=ft.border.all(1, "#C7D2FE"),
            border_radius=8, bgcolor="#EEF2FF",
        ), checks

    # ── Step 2：AI 分析引用 ───────────────────────────────────────────

    def run_analyze(self, e):
        if not self._section_candidates:
            self.status_text.value = "請先執行 Step 1"
            self.page.update()
            return

        self._set_busy("AI 分析引用中...")
        self.results_container.controls.clear()
        self.export_btn.visible = False
        self.page.update()

        def _run():
            try:
                guides = []
                sections = list(self._section_candidates.keys())
                for idx, section in enumerate(sections, 1):
                    self.status_text.value = (
                        f"AI 分析 [{idx}/{len(sections)}] {section[:30]}..."
                    )
                    self.page.update()

                    checks = self._candidate_checks.get(section, {})
                    all_c  = self._section_candidates[section]
                    selected = [c for c in all_c if checks.get(c["paper"].id,
                                ft.Checkbox(value=True)).value]
                    if not selected:
                        selected = all_c

                    guide = self.service.analyze_from_candidates(section, selected)
                    guides.append(guide)
                    self.results_container.controls.append(
                        self._build_section_card(idx, guide)
                    )
                    self.page.update()

                self._last_guides = guides
                self.status_text.value = (
                    f"Step 2 完成：{len(guides)} 個段落。"
                    "可繼續執行 Step 3 缺口補強。"
                )
                self.export_btn.visible = True
                self.enrich_btn.disabled = not bool(guides)
            except Exception as ex:
                self.status_text.value = f"AI 分析失敗：{ex}"
            finally:
                self._set_idle()
                self.analyze_btn.disabled = False
        threading.Thread(target=_run, daemon=True).start()

    def _build_section_card(self, index: int, guide: SectionGuide) -> ft.Control:
        # 寫作建議橫幅
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
            bg, fg = _POS_COLORS.get(c.cite_position, ("#F1F5F9", "#475569"))
            tiles.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("article", size=13, color="#2563EB"),
                        ft.Text(
                            c.paper.title[:68] + ("…" if len(c.paper.title) > 68 else ""),
                            size=12, weight=ft.FontWeight.W_600, expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(c.cite_position, size=10, color=fg),
                            bgcolor=bg, border_radius=10,
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
                    ft.Row([
                        ft.Text(tag, size=10, color=_C_META)
                        for tag in (c.paper.tags or [])[:4]
                    ], spacing=6) if c.paper.tags else ft.Container(),
                ], spacing=4),
                padding=10,
                border=ft.border.all(1, "#BFDBFE"),
                border_radius=6, bgcolor="#FFFFFF",
            ))

        if not tiles:
            tiles.append(ft.Text(
                "未找到相關論文，建議補充文獻或調整段落描述。",
                size=12, color=_C_META, italic=True,
            ))

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    _badge(str(index), "#2563EB"),
                    ft.Text(guide.section, size=14, weight=ft.FontWeight.W_600,
                            expand=True, color=_C_TITLE),
                    ft.Text(f"{len(guide.citations)} 篇引用",
                            size=11, color=_C_META),
                ], spacing=10),
                hint_ctrl,
                *tiles,
            ], spacing=6),
            padding=14, border=ft.border.all(1, _C_BORDER),
            border_radius=10, bgcolor=_C_BG,
        )

    # ── Step 3：缺口補強 + 寫作範例 ──────────────────────────────────

    def run_enrichment(self, e):
        if not self._last_guides:
            self.status_text.value = "請先完成 Step 2"
            self.page.update()
            return

        sections = self._parse_outline()
        self._set_busy("Step 3：AI 分析大綱缺口...")
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
                self.status_text.value = (
                    f"Step 3 完成：{len(enrichment.follow_up_questions)} 個追問，"
                    f"{len(enrichment.concept_gaps)} 個概念缺口"
                )
                self.export_btn.visible = True
            except Exception as ex:
                self.status_text.value = f"Step 3 失敗：{ex}"
            finally:
                self._set_idle()
                self.analyze_btn.disabled = False
                self.enrich_btn.disabled = False
        threading.Thread(target=_run, daemon=True).start()

    def _build_enrichment_card(self, enrichment: OutlineEnrichment) -> ft.Control:
        # ── 追問區 ──────────────────────────────────────────────────
        q_controls = [
            ft.Row([
                ft.Container(
                    content=ft.Text(str(i), size=10, color="#FFFFFF",
                                    weight=ft.FontWeight.BOLD),
                    bgcolor="#7C3AED", border_radius=10, width=22, height=22,
                    alignment=ft.alignment.center,
                ),
                ft.Text(q, size=12, color="#3B1D8E", expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
            for i, q in enumerate(enrichment.follow_up_questions, 1)
        ]

        followup_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("help_outline", color="#7C3AED", size=16),
                    ft.Text("追問 Follow-up Questions", size=13,
                            weight=ft.FontWeight.W_600, color="#5B21B6"),
                ], spacing=6),
                ft.Text("這些問題指出大綱目前論述不足或需要深化的地方",
                        size=11, color=_C_META),
                ft.Divider(height=4, color="#DDD6FE"),
                *q_controls,
            ], spacing=8),
            bgcolor="#F5F3FF", border=ft.border.all(1, "#DDD6FE"),
            border_radius=10, padding=14,
        ) if enrichment.follow_up_questions else ft.Container()

        # ── 概念缺口區 ───────────────────────────────────────────────
        gap_tiles = []
        for gap in enrichment.concept_gaps:
            paper_row = ft.Container()
            if gap.paper:
                paper_row = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("menu_book", size=13, color="#065F46"),
                            ft.Text("文獻庫對應論文：", size=11, color="#065F46",
                                    weight=ft.FontWeight.W_600),
                            ft.Text(
                                gap.paper.title[:55] + ("…" if len(gap.paper.title) > 55 else ""),
                                size=11, color="#047857", expand=True,
                            ),
                            ft.Text(f"({gap.paper.year or '?'})",
                                    size=10, color=_C_META),
                        ], spacing=6),
                    ], spacing=3),
                    bgcolor="#ECFDF5", border_radius=6,
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                )
            else:
                paper_row = ft.Container(
                    content=ft.Row([
                        ft.Icon("warning_amber", size=13, color="#B45309"),
                        ft.Text("文獻庫中無對應論文，建議補充外部文獻",
                                size=11, color="#92400E"),
                    ], spacing=6),
                    bgcolor="#FFFBEB", border_radius=6,
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                )

            # 寫作範例
            example_ctrl = ft.Container()
            if gap.writing_example:
                lines = gap.writing_example.split("\n💡 ")
                example_text = lines[0]
                tip_text = lines[1] if len(lines) > 1 else ""
                example_ctrl = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("edit_note", size=13, color="#1D4ED8"),
                            ft.Text("寫作範例", size=11, color="#1E40AF",
                                    weight=ft.FontWeight.W_600),
                        ], spacing=4),
                        ft.Container(
                            content=ft.Text(
                                example_text,
                                size=12, color="#1E3A5F",
                                selectable=True, italic=True,
                            ),
                            bgcolor="#EFF6FF",
                            border=ft.border.only(
                                left=ft.BorderSide(3, "#3B82F6")),
                            padding=ft.padding.only(left=12, top=8,
                                                    bottom=8, right=10),
                            border_radius=4,
                        ),
                        ft.Row([
                            ft.Icon("place", size=12, color="#7C3AED"),
                            ft.Text(tip_text, size=11, color="#6D28D9",
                                    italic=True),
                        ], spacing=4) if tip_text else ft.Container(),
                    ], spacing=6),
                )

            gap_tiles.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Text(gap.concept, size=11,
                                            color="#FFFFFF",
                                            weight=ft.FontWeight.W_600),
                            bgcolor="#7C3AED", border_radius=8,
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        ),
                        ft.Container(expand=True),
                        ft.Text(f"→ {gap.suggested_section[:35]}",
                                size=10, color=_C_META, italic=True),
                    ], spacing=8),
                    ft.Text(gap.reason, size=11, color=_C_META),
                    paper_row,
                    example_ctrl,
                ], spacing=6),
                padding=12, border=ft.border.all(1, "#DDD6FE"),
                border_radius=8, bgcolor="#FFFFFF",
            ))

        gaps_section = ft.Column([
            ft.Row([
                ft.Icon("extension", color="#7C3AED", size=16),
                ft.Text("概念缺口補強", size=13, weight=ft.FontWeight.W_600,
                        color="#5B21B6"),
                ft.Container(
                    content=ft.Text(f"{len(enrichment.concept_gaps)} 個缺口",
                                    size=10, color="#FFFFFF"),
                    bgcolor="#7C3AED", border_radius=10,
                    padding=ft.padding.symmetric(horizontal=8, vertical=2),
                ),
            ], spacing=8),
            ft.Text("補充這些概念可讓你的大綱更全面，右側提供文獻庫對應論文與寫作範例",
                    size=11, color=_C_META),
            *gap_tiles,
        ], spacing=10) if enrichment.concept_gaps else ft.Container()

        return ft.Container(
            content=ft.Column([
                # 標題
                ft.Container(
                    content=ft.Row([
                        ft.Icon("auto_fix_high", color="#FFFFFF", size=18),
                        ft.Text("Step 3：缺口補強分析", size=15,
                                weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                    ], spacing=8),
                    bgcolor="#7C3AED", border_radius=8,
                    padding=ft.padding.symmetric(horizontal=14, vertical=10),
                ),
                followup_card,
                gaps_section,
            ], spacing=12),
            padding=14,
            border=ft.border.all(2, "#7C3AED"),
            border_radius=12,
            bgcolor="#FAFAFA",
        )

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

def _badge(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=12, weight=ft.FontWeight.BOLD,
                        color="#FFFFFF"),
        bgcolor=color, width=26, height=26,
        border_radius=13, alignment=ft.alignment.center,
    )
