"""
首頁視圖 — Bento Grid 佈局
"""

import flet as ft
from pathlib import Path
from typing import Optional
import threading

from ...services.pipeline import Pipeline
from ...services.ingestion import XLSXIngestion
from ...services.quick_import import QuickImportService
from ...services.pdf_ingestion import PDFIngestionService
from ...services.pdf_import_service import PDFImportService, ExtractedMeta
from ...database.sqlite_db import SQLiteDB
from ...models import ProcessingStatus
from .. import theme as T


class HomeView:
    def __init__(self, page: ft.Page):
        self.page = page
        self.pipeline = Pipeline()
        self._quick_importer: Optional[QuickImportService] = None
        self._pdf_ingestor: Optional[PDFIngestionService] = None
        self._pdf_importer: Optional[PDFImportService] = None
        self._sqlite = SQLiteDB()
        self._pdf_status: Optional[ft.Text] = None
        self._pdf_queue: list[dict] = []
        self._pdf_queue_col: Optional[ft.Column] = None
        self.selected_file: Optional[str] = None
        self.is_processing = False
        self._headers: list[tuple[int, str]] = []
        self._col_options: list[ft.dropdown.Option] = []

        self.file_path_text: Optional[ft.Text] = None
        self.progress_bar: Optional[ft.ProgressBar] = None
        self.progress_text: Optional[ft.Text] = None
        self.process_btn = None
        self.stats_row: Optional[ft.Row] = None
        self.status_text: Optional[ft.Text] = None
        self.column_panel: Optional[ft.Container] = None
        self.dd_title: Optional[ft.Dropdown] = None
        self.dd_abstract: Optional[ft.Dropdown] = None
        self.dd_doi: Optional[ft.Dropdown] = None
        self.dd_tags: Optional[ft.Dropdown] = None
        self.dd_authors: Optional[ft.Dropdown] = None
        self.dd_venue: Optional[ft.Dropdown] = None
        self.dd_year: Optional[ft.Dropdown] = None

    # ── Build ─────────────────────────────────────────────────────────

    def build(self) -> ft.Column:
        self.file_picker = ft.FilePicker()

        self.file_picker.on_result = self.on_file_picked
        self.page.overlay.append(self.file_picker)

        self.file_path_text = ft.Text("尚未選擇檔案", size=13, color=T.TEXT_M)
        self.progress_bar = ft.ProgressBar(
            value=0,
            visible=False,
            color=T.ACCENT,
            bgcolor=T.ACCENT_SOFT,
            border_radius=4,
        )
        self.progress_text = ft.Text("", size=12, color=T.TEXT_M, visible=False)
        self.status_text = ft.Text("", size=13, color=T.GREEN)

        self.process_btn = T.pill_btn(
            "開始處理",
            "play_arrow",
            self.on_process_click,
            filled=True,
            disabled=True,
        )

        # 欄位選擇面板
        self.dd_title = self._make_dd("標題欄位（必要）")
        self.dd_abstract = self._make_dd("摘要欄位（選填）")
        self.dd_doi = self._make_dd("DOI 欄位（選填）")
        self.dd_tags = self._make_dd("標籤欄位（選填）")
        self.dd_authors = self._make_dd("作者欄位（選填）")
        self.dd_venue = self._make_dd("期刊/會議欄位（選填）")
        self.dd_year = self._make_dd("年份欄位（選填）")
        self.update_checkbox = ft.Checkbox(
            label="同時更新已有論文的作者 / 期刊 / 年份（只補空缺，不覆蓋）",
            value=True,
        )

        self.column_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row([
                        T.icon_badge("table_chart", T.TEAL, size=15, bg_size=32),
                        T.h3("欄位對應設定", color=T.TEXT_H),
                    ], spacing=10),
                    T.muted("系統已自動偵測欄位，請確認或調整對應關係"),
                    ft.Container(height=4),
                    ft.Row([self.dd_title, self.dd_abstract], spacing=16, wrap=True),
                    ft.Row([self.dd_doi, self.dd_tags], spacing=16, wrap=True),
                    ft.Row([self.dd_authors, self.dd_venue, self.dd_year], spacing=16, wrap=True),
                    self.update_checkbox,
                ],
                spacing=10,
            ),
            padding=20,
            border_radius=16,
            bgcolor=T.alpha(T.TEAL, 0.06),
            border=ft.border.all(1, T.alpha(T.TEAL, 0.20)),
            visible=False,
        )

        stats = self._get_stats()
        self.stats_row = self._build_stats_row(stats)

        return ft.Column(
            [
                # Row 1: Hero + mini summary
                ft.Row(
                    [
                        self._build_hero_card(),
                        self._build_quick_guide_card(),
                    ],
                    spacing=16,
                ),

                # Row 2: Stat cards
                self.stats_row,

                # Row 3: Upload card
                self._build_upload_card(),

                # Row 4: Quick import card (DOI / arXiv)
                self._build_quick_import_card(),

                # Row 5: PDF full-text upload card
                self._build_pdf_card(),

                # Row 6: Bookmarklet install card
                self._build_bookmarklet_card(),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    # ── Hero card ─────────────────────────────────────────────────────

    def _build_hero_card(self) -> ft.Container:
        return T.gradient_card(
            ft.Column(
                [
                    ft.Row([
                        ft.Container(
                            content=ft.Icon("auto_awesome", color="#FFFFFF", size=20),
                            width=40,
                            height=40,
                            border_radius=12,
                            bgcolor="#40FFFFFF",   # 25% white
                            alignment=ft.alignment.center,
                        ),
                        ft.Column(
                            [
                                ft.Text("SmartPaper", size=22, weight=ft.FontWeight.BOLD,
                                        color="#FFFFFF"),
                                ft.Text("智能學術文獻標籤管理系統", size=12,
                                        color="#CCFFFFFF"),   # 80% white
                            ],
                            spacing=2,
                            tight=True,
                        ),
                    ], spacing=12),
                    ft.Container(height=16),
                    ft.Row(
                        [
                            _feature_pill("語意搜尋"),
                            _feature_pill("AI 標籤"),
                            _feature_pill("RAG 問答"),
                            _feature_pill("圖譜分析"),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=0,
            ),
            colors=[T.ACCENT, T.VIOLET],
            expand=3,
            height=160,
        )

    # ── Quick guide card ──────────────────────────────────────────────

    def _build_quick_guide_card(self) -> ft.Container:
        steps = [
            ("upload_file",    "選擇 XLSX / CSV 檔案"),
            ("table_chart",    "對應欄位（標題、摘要）"),
            ("rocket_launch",  "點擊開始處理"),
            ("auto_awesome",   "AI 自動生成標籤"),
        ]
        return T.card(
            ft.Column(
                [
                    T.section_label("快速入門"),
                    ft.Container(height=8),
                    *[
                        ft.Row([
                            T.icon_badge(icon, T.ACCENT, size=13, bg_size=28),
                            ft.Text(text, size=12, color=T.TEXT_B),
                        ], spacing=10)
                        for icon, text in steps
                    ],
                ],
                spacing=8,
            ),
            expand=2,
            height=160,
            padding=20,
        )

    # ── Stats row ─────────────────────────────────────────────────────

    def _build_stats_row(self, stats: dict) -> ft.Row:
        data = [
            ("總論文數", stats.get("total_papers", 0), "article",       T.STAT_PALETTES[0]),
            ("標籤數量", stats.get("unique_tags", 0),  "label",         T.STAT_PALETTES[1]),
            ("有摘要",  stats.get("with_abstract", 0), "description",   T.STAT_PALETTES[2]),
            ("向量數",  stats.get("total_vectors", 0), "hub",           T.STAT_PALETTES[3]),
        ]
        return ft.Row(
            [self._stat_card(label, val, icon, palette) for label, val, icon, palette in data],
            spacing=16,
        )

    def _stat_card(self, label: str, value, icon, palette: tuple) -> ft.Container:
        bg, accent = palette
        return T.card(
            ft.Column(
                [
                    ft.Row([
                        T.icon_badge(icon, accent, size=16, bg_size=36),
                        ft.Container(expand=True),
                        ft.Container(
                            content=ft.Text("↑", size=10, color=accent),
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            border_radius=6,
                            bgcolor=T.alpha(accent, 0.12),
                        ),
                    ]),
                    ft.Container(height=8),
                    ft.Text(str(value), size=30, weight=ft.FontWeight.BOLD, color=T.TEXT_H),
                    ft.Text(label, size=12, color=T.TEXT_M),
                ],
                spacing=0,
            ),
            bg=bg,
            border_color=T.alpha(accent, 0.30),
            shadow_color=T.alpha(accent, 0.08),
            padding=20,
            expand=True,
            height=130,
        )

    # ── Upload card ───────────────────────────────────────────────────

    def _build_upload_card(self) -> ft.Container:
        return T.card(
            ft.Column(
                [
                    ft.Row([
                        T.icon_badge("upload_file", T.ACCENT, size=16, bg_size=36),
                        T.h3("匯入論文清單"),
                    ], spacing=12),
                    T.soft_divider(),
                    ft.Row(
                        [
                            T.pill_btn(
                                "選擇檔案",
                                "folder_open",
                                lambda _: self.file_picker.pick_files(
                                    allowed_extensions=["xlsx", "xls", "csv"],
                                    dialog_title="選擇論文清單檔案",
                                ),
                                filled=False,
                            ),
                            self.file_path_text,
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.column_panel,
                    ft.Row(
                        [self.process_btn, self.status_text],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.progress_bar,
                    self.progress_text,
                ],
                spacing=14,
            ),
            padding=24,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _make_dd(self, label: str) -> ft.Dropdown:
        return ft.Dropdown(
            label=label,
            width=280,
            options=[],
            value=None,
            border_radius=12,
            text_size=13,
        )

    def _get_stats(self) -> dict:
        try:
            return self.pipeline.get_statistics()
        except Exception:
            return {"total_papers": 0, "unique_tags": 0, "with_abstract": 0, "total_vectors": 0}

    # ── Events ────────────────────────────────────────────────────────

    def on_file_picked(self, e):
        if not (e.files and len(e.files) > 0):
            self.selected_file = None
            self.file_path_text.value = "尚未選擇檔案"
            self.process_btn.disabled = True
            self.column_panel.visible = False
            self.page.update()
            return

        self.selected_file = e.files[0].path
        filename = Path(self.selected_file).name
        self.file_path_text.value = f"📄 {filename}"
        self._detect_and_show_columns()
        self.page.update()

    def _detect_and_show_columns(self):
        try:
            with XLSXIngestion(self.selected_file) as ing:
                self._headers = ing.get_headers()
                detected = ing.detect_columns()

            if not self._headers:
                self.status_text.value = "警告：找不到欄位表頭"
                self.process_btn.disabled = False
                return

            none_opt = ft.dropdown.Option("__none__", "（不使用）")
            self._col_options = [none_opt] + [
                ft.dropdown.Option(str(idx), name) for idx, name in self._headers
            ]

            for dd in [self.dd_title, self.dd_abstract, self.dd_doi, self.dd_tags,
                       self.dd_authors, self.dd_venue, self.dd_year]:
                dd.options = self._col_options

            self.dd_title.value = str(detected.get("title", self._headers[0][0]))
            self.dd_abstract.value = str(detected["abstract"]) if "abstract" in detected else "__none__"
            self.dd_doi.value = str(detected["doi"]) if "doi" in detected else "__none__"
            self.dd_tags.value = str(detected["tags"]) if "tags" in detected else "__none__"
            self.dd_authors.value = str(detected["authors"]) if "authors" in detected else "__none__"
            self.dd_venue.value = str(detected["venue"]) if "venue" in detected else "__none__"
            self.dd_year.value = str(detected["year"]) if "year" in detected else "__none__"

            self.column_panel.visible = True
            self.process_btn.disabled = False

            found = [k for k in ["title", "abstract", "doi", "tags", "authors", "venue", "year"] if k in detected]
            self.status_text.value = f"偵測到 {len(self._headers)} 個欄位，自動對應：{', '.join(found)}"
            self.status_text.color = T.ACCENT

        except Exception as ex:
            self.status_text.value = f"讀取欄位失敗：{ex}"
            self.status_text.color = T.ROSE
            self.process_btn.disabled = False

    def on_process_click(self, e):
        if not self.selected_file or self.is_processing:
            return

        if self.column_panel.visible:
            if not self.dd_title.value or self.dd_title.value == "__none__":
                self.status_text.value = "請選擇標題欄位"
                self.status_text.color = T.ROSE
                self.page.update()
                return

        self.is_processing = True
        self.process_btn.disabled = True
        self.progress_bar.visible = True
        self.progress_text.visible = True
        self.progress_bar.value = 0
        self.status_text.value = ""
        self.page.update()

        threading.Thread(target=self.process_file).start()

    def process_file(self):
        try:
            if self.column_panel.visible and self._headers:
                title_col = int(self.dd_title.value)
                abstract_col = int(self.dd_abstract.value) if self.dd_abstract.value != "__none__" else -1
                doi_col = int(self.dd_doi.value) if self.dd_doi.value != "__none__" else -1
                tags_col = int(self.dd_tags.value) if self.dd_tags.value != "__none__" else -1
                authors_col = int(self.dd_authors.value) if self.dd_authors.value != "__none__" else -1
                venue_col = int(self.dd_venue.value) if self.dd_venue.value != "__none__" else -1
                year_col = int(self.dd_year.value) if self.dd_year.value != "__none__" else -1

                with XLSXIngestion(self.selected_file) as ing:
                    papers = ing.read_papers_by_index(
                        title_col=title_col,
                        abstract_col=abstract_col,
                        doi_col=doi_col,
                        tags_col=tags_col,
                        authors_col=authors_col,
                        venue_col=venue_col,
                        year_col=year_col,
                    )

                status = self.pipeline.process_papers_list(
                    papers=papers,
                    skip_existing=True,
                    generate_tags=True,
                    fetch_missing=(abstract_col == -1),
                    progress_callback=self.on_progress_update,
                )

                # 更新已有論文的作者 / 期刊 / 年份
                if self.update_checkbox.value and (authors_col >= 0 or venue_col >= 0 or year_col >= 0):
                    self.pipeline.update_metadata_from_list(papers)
            else:
                status = self.pipeline.process_xlsx(
                    file_path=self.selected_file,
                    title_column="A",
                    skip_existing=True,
                    generate_tags=True,
                    progress_callback=self.on_progress_update,
                )

            self.status_text.value = f"處理完成！成功：{status.success}，失敗：{status.failed}"
            self.status_text.color = T.GREEN

            new_stats = self._get_stats()
            self.stats_row.controls = self._build_stats_row(new_stats).controls

        except Exception as ex:
            self.status_text.value = f"處理失敗：{ex}"
            self.status_text.color = T.ROSE

        finally:
            self.is_processing = False
            self.process_btn.disabled = False
            self.progress_bar.visible = False
            self.progress_text.visible = False
            self.page.update()

    def on_progress_update(self, status: ProcessingStatus):
        self.progress_bar.value = status.progress / 100
        self.progress_text.value = (
            f"處理中… {status.processed}/{status.total} "
            f"（成功：{status.success}，失敗：{status.failed}）"
        )
        self.page.update()

    # ── Quick Import Card ─────────────────────────────────────────────

    def _build_quick_import_card(self) -> ft.Container:
        self._qi_field = ft.TextField(
            hint_text="貼上 DOI（如 10.1145/xxx）或 arXiv ID/URL（如 2301.12345）",
            prefix_icon="link",
            expand=True,
            height=42,
            border_radius=10,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=0),
            filled=True,
            fill_color="#FFFFFF",
            on_submit=self._on_quick_import,
        )
        self._qi_status = ft.Text("", size=12, color=T.GREEN)
        self._qi_btn = T.pill_btn("匯入", "download", self._on_quick_import, filled=True)

        return T.card(
            ft.Column([
                ft.Row([
                    T.icon_badge("bolt", T.VIOLET, size=16, bg_size=36),
                    T.h3("快速匯入（DOI / arXiv）"),
                ], spacing=12),
                T.soft_divider(),
                ft.Text(
                    "直接貼上 DOI 或 arXiv 連結，自動取得標題、作者、摘要並生成標籤",
                    size=12, color=T.TEXT_M,
                ),
                ft.Row([self._qi_field, self._qi_btn], spacing=12,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self._qi_status,
            ], spacing=10),
            padding=24,
        )

    def _on_quick_import(self, e):
        raw = (self._qi_field.value or "").strip()
        if not raw:
            return
        self._qi_status.value = "⏳ 查詢中..."
        self._qi_status.color = T.ACCENT
        self._qi_btn.disabled = True
        self.page.update()

        def run():
            if not self._quick_importer:
                self._quick_importer = QuickImportService()

            def prog(msg):
                self._qi_status.value = f"⏳ {msg}"
                self._qi_status.color = T.ACCENT
                self.page.update()

            paper, err = self._quick_importer.import_from_text(raw, progress_callback=prog)
            if err:
                self._qi_status.value = f"❌ {err}"
                self._qi_status.color = T.ROSE
            else:
                self._qi_status.value = (
                    f"✅ 已新增：{paper.title[:60]}"
                    + (f"（{paper.year}）" if paper.year else "")
                    + (f"，標籤：{', '.join(paper.tags[:4])}" if paper.tags else "")
                )
                self._qi_status.color = T.GREEN
                self._qi_field.value = ""
                # 更新統計數字
                new_stats = self._get_stats()
                self.stats_row.controls = self._build_stats_row(new_stats).controls

            self._qi_btn.disabled = False
            self.page.update()

        threading.Thread(target=run, daemon=True).start()

    # ── PDF Full-text Card ────────────────────────────────────────────

    def _build_pdf_card(self) -> ft.Container:
        self._pdf_status = ft.Text("", size=12, color=T.GREEN)
        self._pdf_queue_col = ft.Column(spacing=6)

        pick_btn = T.pill_btn(
            "選擇 PDF（可多選）", "upload_file",
            self._on_pick_pdfs, filled=False,
        )
        import_all_btn = T.pill_btn(
            "一鍵匯入全部", "cloud_upload",
            self._on_import_pdfs, filled=True,
        )
        new_paper_btn = ft.OutlinedButton(
            "從 PDF 自動建立新論文",
            icon="auto_awesome",
            on_click=self._on_pick_pdf_new,
            style=ft.ButtonStyle(color="#6A1B9A"),
        )

        return T.card(
            ft.Column([
                ft.Row([
                    T.icon_badge("picture_as_pdf", "#C62828", size=16, bg_size=36),
                    T.h3("上傳 PDF 全文"),
                ], spacing=12),
                T.soft_divider(),
                ft.Text(
                    "上傳 PDF 後可用「問論文」功能進行章節級精準問答",
                    size=12, color=T.TEXT_M,
                ),
                # 操作列
                ft.Row([pick_btn, import_all_btn, new_paper_btn],
                       spacing=10, wrap=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                # 佇列（選完 PDF 後顯示）
                self._pdf_queue_col,
                self._pdf_status,
            ], spacing=10),
            padding=24,
        )

    def _on_pick_pdfs(self, e):
        """選擇多個 PDF，加入佇列等待指定論文"""
        def on_result(result):
            if not result.files:
                return
            papers = self._sqlite.get_all(limit=500)
            opts = [
                ft.dropdown.Option(
                    str(p.id),
                    f"[{p.id}] {p.title[:50]}{'…' if len(p.title) > 50 else ''}"
                    + (f" ({p.year})" if p.year else ""),
                )
                for p in papers
            ]
            for f in result.files:
                if not f.path:
                    continue
                dd = ft.Dropdown(
                    hint_text="選擇對應論文",
                    options=opts,
                    expand=True,
                    dense=True,
                )
                entry = {"path": f.path, "name": f.name, "dd": dd}
                self._pdf_queue.append(entry)

                def _remove(e, en=entry):
                    self._pdf_queue = [x for x in self._pdf_queue if x is not en]
                    if "row" in en and en["row"] in self._pdf_queue_col.controls:
                        self._pdf_queue_col.controls.remove(en["row"])
                    self.page.update()

                row = ft.Row([
                    ft.Icon("picture_as_pdf", color=ft.colors.RED_400, size=16),
                    ft.Text(f.name, size=11, width=160, overflow=ft.TextOverflow.ELLIPSIS),
                    dd,
                    ft.IconButton(icon="close", icon_size=16, on_click=_remove),
                ], spacing=6)
                entry["row"] = row
                self._pdf_queue_col.controls.append(row)
            self.page.update()

        picker = ft.FilePicker()
        picker.on_result = on_result
        self.page.overlay.append(picker)
        self.page.update()
        picker.pick_files(
            dialog_title="選擇 PDF 論文（可多選）",
            allowed_extensions=["pdf"],
            allow_multiple=True,
        )

    def _on_import_pdfs(self, e):
        """把佇列裡有指定論文的 PDF 全部匯入"""
        pending = [en for en in self._pdf_queue if en.get("dd") and en["dd"].value]
        if not pending:
            self._pdf_status.value = "⚠️ 請先選擇 PDF 並為每個檔案指定對應論文"
            self._pdf_status.color = T.ROSE
            self.page.update()
            return

        self._pdf_status.value = f"⏳ 匯入 {len(pending)} 個 PDF..."
        self._pdf_status.color = T.ACCENT
        self.page.update()

        def run():
            if not self._pdf_ingestor:
                self._pdf_ingestor = PDFIngestionService()
            ok, fail = 0, 0
            for en in pending:
                pid = int(en["dd"].value)
                def _prog(msg, name=en["name"]):
                    self._pdf_status.value = f"⏳ [{name}] {msg}"
                    self._pdf_status.color = T.ACCENT
                    self.page.update()
                res = self._pdf_ingestor.ingest(en["path"], pid,
                                                replace_existing=True,
                                                progress_callback=_prog)
                if res.success:
                    ok += 1
                else:
                    fail += 1

            self._pdf_queue.clear()
            self._pdf_queue_col.controls.clear()
            self._pdf_status.value = f"✅ 完成：{ok} 成功，{fail} 失敗"
            self._pdf_status.color = T.GREEN if fail == 0 else T.ROSE
            # 更新統計
            new_stats = self._get_stats()
            self.stats_row.controls = self._build_stats_row(new_stats).controls
            self.page.update()

        threading.Thread(target=run, daemon=True).start()

    def _on_pick_pdf_new(self, e):
        """選一個 PDF，AI 萃取 metadata 後彈出確認對話框新增論文"""
        def on_result(result):
            if not result.files or not result.files[0].path:
                return
            f = result.files[0]
            self._pdf_status.value = f"⏳ AI 分析中：{f.name}..."
            self._pdf_status.color = "#6A1B9A"
            self.page.update()

            def run():
                def _prog(msg):
                    self._pdf_status.value = f"⏳ {msg}"
                    self._pdf_status.color = "#6A1B9A"
                    self.page.update()

                if not self._pdf_importer:
                    self._pdf_importer = PDFImportService()
                meta = self._pdf_importer.extract_meta(f.path, progress_callback=_prog)
                self._pdf_status.value = "完成分析，請確認論文資訊"
                self._pdf_status.color = T.GREEN
                self._show_new_paper_dialog(f.path, f.name, meta)
                self.page.update()

            threading.Thread(target=run, daemon=True).start()

        picker = ft.FilePicker()
        picker.on_result = on_result
        self.page.overlay.append(picker)
        self.page.update()
        picker.pick_files(
            dialog_title="選擇要匯入的 PDF 論文",
            allowed_extensions=["pdf"],
            allow_multiple=False,
        )

    def _show_new_paper_dialog(self, pdf_path: str, filename: str, meta: ExtractedMeta):
        title_f = ft.TextField(label="標題 *", value=meta.title, multiline=True,
                               min_lines=1, max_lines=3)
        authors_f = ft.TextField(label="作者（逗號分隔）",
                                 value=", ".join(meta.authors))
        year_f = ft.TextField(label="年份", value=str(meta.year) if meta.year else "",
                              width=100)
        venue_f = ft.TextField(label="期刊/會議", value=meta.venue, expand=True)
        doi_f = ft.TextField(label="DOI（選填）", value=meta.doi, expand=True)
        abstract_f = ft.TextField(label="摘要", value=meta.abstract,
                                  multiline=True, min_lines=3, max_lines=6)
        tags_f = ft.TextField(label="標籤（逗號分隔）",
                              value=", ".join(meta.tags))
        status_t = ft.Text("", size=12)

        def _collect() -> ExtractedMeta:
            authors = [a.strip() for a in (authors_f.value or "").split(",") if a.strip()]
            try:
                year = int(year_f.value.strip()) if year_f.value and year_f.value.strip() else None
            except ValueError:
                year = None
            tags = [t.strip() for t in (tags_f.value or "").split(",") if t.strip()]
            return ExtractedMeta(
                title=(title_f.value or "").strip(),
                authors=authors, year=year,
                venue=(venue_f.value or "").strip(),
                doi=(doi_f.value or "").strip(),
                abstract=(abstract_f.value or "").strip(),
                tags=tags,
            )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"確認論文資訊：{filename}", size=15,
                          weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    title_f,
                    ft.Row([authors_f, year_f], spacing=8),
                    ft.Row([venue_f, doi_f], spacing=8),
                    abstract_f, tags_f, status_t,
                ], spacing=10, scroll=ft.ScrollMode.AUTO),
                width=680, height=480,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dlg(dlg)),
                ft.ElevatedButton(
                    "確認匯入", icon="save",
                    style=ft.ButtonStyle(bgcolor="#6A1B9A", color=ft.colors.WHITE),
                    on_click=lambda e: self._do_import_new(dlg, pdf_path, _collect, status_t),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    # ── Bookmarklet Card ──────────────────────────────────────────────

    _BOOKMARKLET = (
        "javascript:(function(){"
        "var d=null,ax=null,ms=document.querySelectorAll('meta');"
        "for(var m of ms){"
        "var n=(m.getAttribute('name')||m.getAttribute('property')||'').toLowerCase(),"
        "c=m.getAttribute('content')||'';"
        "if((n.includes('doi')||n==='dc.identifier')&&/^10\\./.test(c)){d=c;break;}}"
        "if(!d){var u=location.href.match(/doi\\.org\\/(10\\.[^&\\s#?]+)/);if(u)d=u[1];}"
        "if(!d){var a=document.querySelector('a[href*=\"doi.org/10.\"]');"
        "if(a){var am=a.href.match(/doi\\.org\\/(10\\.[^&\\s#?]+)/);if(am)d=am[1];}}"
        "var ax2=location.href.match(/arxiv\\.org\\/(?:abs|pdf)\\/(\\d{4}\\.\\d{4,5})/);if(ax2)ax=ax2[1];"
        "if(!d&&!ax){alert('SmartPaper: 找不到 DOI 或 arXiv ID，請在論文頁面使用');return;}"
        "var p=d?'doi='+encodeURIComponent(d):'arxiv='+encodeURIComponent(ax);"
        "fetch('http://localhost:7878/import?'+p)"
        ".then(function(r){return r.json();})"
        ".then(function(j){"
        "if(j.success)alert('✅ SmartPaper：已加入「'+j.title+'」');"
        "else alert('❌ SmartPaper：'+j.error);})"
        ".catch(function(){alert('❌ 無法連接 SmartPaper，請確認應用程式已開啟');});"
        "})()"
    )

    def _build_bookmarklet_card(self) -> ft.Container:
        bm_status = ft.Text("", size=12)

        def _copy_js(e):
            self.page.set_clipboard(self._BOOKMARKLET)
            bm_status.value = "✅ 已複製！請在瀏覽器中新增書籤，將網址欄貼上此程式碼"
            bm_status.color = T.GREEN
            self.page.update()

        steps = [
            ("1", "在 Chrome/Edge 開啟書籤列（Ctrl+Shift+B）"),
            ("2", "點「新增書籤」，名稱填「SmartPaper」"),
            ("3", "網址欄貼上下方複製的程式碼"),
            ("4", "在任意論文頁面點書籤，即可一鍵加入文獻庫"),
        ]

        return T.card(
            ft.Column([
                ft.Row([
                    T.icon_badge("bookmark_add", "#0369A1", size=16, bg_size=36),
                    T.h3("瀏覽器 Bookmarklet"),
                    ft.Container(expand=True),
                    ft.Container(
                        content=ft.Text("需開啟 SmartPaper", size=10, color="#0369A1"),
                        bgcolor="#E0F2FE",
                        border_radius=50,
                        padding=ft.padding.symmetric(horizontal=8, vertical=3),
                    ),
                ], spacing=12),
                T.soft_divider(),
                ft.Text(
                    "在瀏覽器中一鍵將論文加入 SmartPaper，支援 Google Scholar、arXiv、Springer、Nature 等",
                    size=12, color=T.TEXT_M,
                ),
                ft.Container(height=4),
                # 步驟說明
                ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Text(n, size=10, color="white",
                                            weight=ft.FontWeight.BOLD),
                            width=20, height=20, border_radius=10,
                            bgcolor="#0369A1",
                            alignment=ft.alignment.center,
                        ),
                        ft.Text(txt, size=12, color=T.TEXT_B, expand=True),
                    ], spacing=10)
                    for n, txt in steps
                ], spacing=8),
                ft.Container(height=4),
                # 複製按鈕
                ft.Row([
                    ft.ElevatedButton(
                        "複製 Bookmarklet 程式碼",
                        icon="content_copy",
                        on_click=_copy_js,
                        style=ft.ButtonStyle(
                            bgcolor="#0369A1", color="white",
                            shape=ft.RoundedRectangleBorder(radius=10),
                        ),
                    ),
                    ft.Text("支援 Chrome · Edge · Firefox · Safari",
                            size=11, color=T.TEXT_M, italic=True),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bm_status,
                ft.Container(
                    content=ft.Column([
                        ft.Text("支援自動偵測的來源：", size=11,
                                weight=ft.FontWeight.W_600, color=T.TEXT_M),
                        ft.Row([
                            _source_chip("Google Scholar"),
                            _source_chip("arXiv"),
                            _source_chip("Springer"),
                            _source_chip("Nature"),
                            _source_chip("IEEE Xplore"),
                            _source_chip("ACM DL"),
                            _source_chip("PubMed"),
                            _source_chip("Semantic Scholar"),
                        ], spacing=6, wrap=True),
                    ], spacing=6),
                    bgcolor="#F0F9FF",
                    border_radius=8,
                    border=ft.border.all(1, "#BAE6FD"),
                    padding=10,
                ),
            ], spacing=10),
            padding=24,
        )

    def _close_dlg(self, dlg):
        dlg.open = False
        self.page.update()

    def _do_import_new(self, dlg, pdf_path: str, collect_fn, status_t: ft.Text):
        confirmed = collect_fn()
        if not confirmed.title.strip():
            status_t.value = "⚠️ 標題不能為空"
            status_t.color = T.ROSE
            self.page.update()
            return

        status_t.value = "⏳ 匯入中..."
        status_t.color = T.ACCENT
        self.page.update()

        def run():
            def _prog(msg):
                status_t.value = f"⏳ {msg}"
                status_t.color = T.ACCENT
                self.page.update()

            if not self._pdf_importer:
                self._pdf_importer = PDFImportService()
            res = self._pdf_importer.import_from_pdf(pdf_path, confirmed,
                                                     progress_callback=_prog)
            if res.success:
                dlg.open = False
                self._pdf_status.value = (
                    f"✅ 已建立：{confirmed.title[:50]}"
                    + (f"，{res.total_chunks} chunks" if res.total_chunks else "")
                )
                self._pdf_status.color = T.GREEN
                new_stats = self._get_stats()
                self.stats_row.controls = self._build_stats_row(new_stats).controls
            else:
                status_t.value = f"❌ {res.error}"
                status_t.color = T.ROSE
            self.page.update()

        threading.Thread(target=run, daemon=True).start()


# ── Module-level helpers ──────────────────────────────────────────────

def _source_chip(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=10, color="#0369A1"),
        padding=ft.padding.symmetric(horizontal=8, vertical=3),
        border_radius=50,
        bgcolor="#E0F2FE",
        border=ft.border.all(1, "#BAE6FD"),
    )


def _feature_pill(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, color="#FFFFFF", weight=ft.FontWeight.W_500),
        padding=ft.padding.symmetric(horizontal=12, vertical=5),
        border_radius=50,
        bgcolor="#38FFFFFF",   # 22% white
        border=ft.border.all(1, "#4DFFFFFF"),  # 30% white
    )
