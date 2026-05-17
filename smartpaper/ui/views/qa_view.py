"""
問論文（Ask Your Papers）視圖
左欄：來源選擇 / 跨論文比較 / PDF 管理
右欄：聊天區 + 輸入列
"""

import threading
import flet as ft
from typing import Optional

from ...services.qa_service import QAService, ChatMessage, QAResult, SourceChunk
from ...services.pdf_ingestion import PDFIngestionService
from ...services.pdf_import_service import PDFImportService, ExtractedMeta
from ...services.paper_compare import PaperCompareService
from ...database.sqlite_db import SQLiteDB
from ...config import GEMINI_API_KEY


COLOR_USER_BG       = "#E3F2FD"
COLOR_ASST_BG       = "#F3E5F5"
COLOR_SOURCE_BG     = "#FAFAFA"
COLOR_BORDER        = "#E0E0E0"
COLOR_FULLTEXT_BADGE = "#1B5E20"
COLOR_ABSTRACT_BADGE = "#1565C0"
COLOR_TABLE_BADGE   = "#E65100"

_SIDEBAR_W = 340

_FOLLOWUP_WORDS = {"那", "這", "他", "她", "它", "前面", "上面", "剛才", "那篇", "這篇",
                   "作者", "年份", "詳細", "繼續", "還有", "呢", "再說", "多說"}


def _is_followup(question: str) -> bool:
    q = question.strip()
    if len(q) <= 15:
        return True
    return any(w in q for w in _FOLLOWUP_WORDS)


def _fmt_apa(paper) -> str:
    authors = paper.authors or []
    if not authors:
        author_str = "Unknown"
    elif len(authors) == 1:
        author_str = authors[0]
    elif len(authors) <= 6:
        author_str = ", ".join(authors[:-1]) + ", & " + authors[-1]
    else:
        author_str = ", ".join(authors[:6]) + ", et al."
    year  = f"({paper.year})" if paper.year else "(n.d.)"
    venue = f" {paper.venue}." if paper.venue else ""
    doi   = f" https://doi.org/{paper.doi}" if paper.doi else ""
    return f"{author_str} {year}. {paper.title}.{venue}{doi}"


def _fmt_mla(paper) -> str:
    authors = paper.authors or []
    if not authors:
        author_str = "Unknown"
    elif len(authors) == 1:
        author_str = authors[0]
    else:
        first = authors[0].rsplit(" ", 1)
        author_str = (f"{first[-1]}, {first[0]}, et al." if len(first) == 2
                      else authors[0] + ", et al.")
    year  = f" {paper.year}." if paper.year else ""
    venue = f' "{paper.venue}."' if paper.venue else ""
    doi   = f" doi:{paper.doi}" if paper.doi else ""
    return f'{author_str}. "{paper.title}."{venue}{year}{doi}'


def _sec_label(text: str, color: str = "#1E293B") -> ft.Text:
    return ft.Text(text, size=11, weight=ft.FontWeight.W_600, color=color)


def _sidebar_card(title: str, icon: str, icon_color: str,
                  content: ft.Control, bgcolor: str = "#FFFFFF",
                  border_color: str = "#E2E8F0") -> ft.Container:
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(icon, color=icon_color, size=14),
                _sec_label(title, icon_color),
            ], spacing=6),
            ft.Divider(height=4, color=border_color),
            content,
        ], spacing=6),
        bgcolor=bgcolor,
        border=ft.border.all(1, border_color),
        border_radius=10,
        padding=10,
    )


class QAView:
    """問論文聊天介面（含 PDF 管理 / 跨論文比較）"""

    def __init__(self, page: ft.Page):
        self.page = page
        self._qa_service: Optional[QAService] = None
        self._ingestor: Optional[PDFIngestionService] = None
        self._sqlite = SQLiteDB()
        self._history: list[ChatMessage] = []
        self._chat_column: Optional[ft.Column] = None
        self._input: Optional[ft.TextField] = None
        self._send_btn: Optional[ft.ElevatedButton] = None
        self._top_k = 5
        self._loading = False
        self._pdf_status_text: Optional[ft.Text] = None
        self._source_paper_ids: Optional[set[int]] = None
        self._source_checkboxes: dict[int, ft.Checkbox] = {}
        self._paper_list_col: Optional[ft.Column] = None
        self._source_status: Optional[ft.Text] = None
        self._upload_queue: list[dict] = []
        self._queue_col: Optional[ft.Column] = None
        self._importer: Optional[PDFImportService] = None
        self._last_result: Optional[QAResult] = None
        self._comparer: Optional[PaperCompareService] = None
        self._compare_checkboxes: dict[int, ft.Checkbox] = {}
        self._compare_col: Optional[ft.Column] = None
        self._compare_status: Optional[ft.Text] = None
        self._compare_q: Optional[ft.TextField] = None
        # PDF 管理面板 折疊狀態
        self._pdf_mgmt_visible = False
        self._pdf_mgmt_content: Optional[ft.Column] = None
        self._pdf_toggle_btn: Optional[ft.TextButton] = None

    # ── 懶載入 ────────────────────────────────────────────────────────────

    def _get_qa_service(self) -> Optional[QAService]:
        if self._qa_service:
            return self._qa_service
        if not GEMINI_API_KEY:
            return None
        try:
            self._qa_service = QAService()
        except Exception:
            return None
        return self._qa_service

    def _get_ingestor(self) -> PDFIngestionService:
        if not self._ingestor:
            self._ingestor = PDFIngestionService()
        return self._ingestor

    def _get_importer(self) -> PDFImportService:
        if not self._importer:
            self._importer = PDFImportService()
        return self._importer

    def _get_comparer(self) -> PaperCompareService:
        if not self._comparer:
            self._comparer = PaperCompareService()
        return self._comparer

    # ── 主要建構 ──────────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        self._history = []

        # ── 右側：聊天區 ──────────────────────────────────────────────
        self._chat_column = ft.Column(
            spacing=12, scroll=ft.ScrollMode.AUTO, expand=True,
        )
        self._chat_column.controls.append(self._welcome_card())

        self._input = ft.TextField(
            hint_text="輸入你的問題... （Shift+Enter 換行，Enter 送出）",
            multiline=True, min_lines=2, max_lines=4, expand=True,
            on_submit=self._on_send, shift_enter=True,
        )
        self._send_btn = ft.ElevatedButton(
            text="送出", icon="send", on_click=self._on_send,
            style=ft.ButtonStyle(bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE),
        )
        clear_btn = ft.OutlinedButton(
            text="清除對話", icon="delete_outline", on_click=self._on_clear,
        )

        right_col = ft.Column([
            ft.Container(
                content=self._chat_column,
                expand=True,
                border=ft.border.all(1, COLOR_BORDER),
                border_radius=8,
                padding=14,
            ),
            ft.Container(height=6),
            ft.Row([self._input, self._send_btn, clear_btn],
                   vertical_alignment=ft.CrossAxisAlignment.END),
        ], expand=True, spacing=0)

        # ── 左側：側邊欄 ─────────────────────────────────────────────
        left_col = ft.Container(
            content=ft.Column([
                self._build_source_panel(),
                self._build_compare_panel(),
                self._build_pdf_panel(),
            ], spacing=10, scroll=ft.ScrollMode.AUTO),
            width=_SIDEBAR_W,
            padding=ft.padding.only(right=10, top=2),
        )

        return ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("問論文", size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("根據論文庫回答問題，有全文的論文提供章節級引用",
                            size=11, color=ft.colors.GREY_600),
                ], spacing=2),
            ]),
            ft.Divider(height=1, color=COLOR_BORDER),
            ft.Row([left_col, right_col], expand=True, spacing=0,
                   vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True, spacing=8)

    # ── 側邊欄 Section 1：問答來源選擇 ──────────────────────────────────

    def _build_source_panel(self) -> ft.Control:
        self._source_status = ft.Text(
            "（全部論文）", size=10, color=ft.colors.GREY_600, italic=True,
        )
        self._paper_list_col = ft.Column(spacing=3, scroll=ft.ScrollMode.AUTO)
        self._rebuild_paper_list()
        self._on_source_changed()

        confirm_btn = ft.ElevatedButton(
            "確認", icon="check_circle", height=32,
            on_click=self._on_confirm_source,
            style=ft.ButtonStyle(bgcolor="#1565C0", color=ft.colors.WHITE),
        )

        content = ft.Column([
            ft.Row([
                ft.TextButton("全選",
                    on_click=lambda e: self._toggle_all_sources(True)),
                ft.TextButton("全不選",
                    on_click=lambda e: self._toggle_all_sources(False)),
                ft.Container(expand=True),
                confirm_btn,
            ], spacing=4),
            self._source_status,
            ft.Container(
                content=self._paper_list_col,
                height=200,
                border=ft.border.all(1, "#BFDBFE"),
                border_radius=6,
                padding=6,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ),
        ], spacing=6)

        return _sidebar_card(
            "問答來源選擇", "library_books", "#1565C0",
            content, bgcolor="#EFF6FF", border_color="#BFDBFE",
        )

    def _rebuild_paper_list(self):
        if self._paper_list_col is None:
            return
        self._paper_list_col.controls.clear()
        self._source_checkboxes.clear()

        ingestor = self._get_ingestor()
        fulltext_ids = set(ingestor.papers_with_fulltext())
        papers = self._sqlite.get_all(limit=500)

        if not papers:
            self._paper_list_col.controls.append(
                ft.Text("（論文庫是空的）", size=11, color=ft.colors.GREY_500, italic=True)
            )
            return

        for p in papers:
            has_ft = p.id in fulltext_ids
            cb = ft.Checkbox(
                value=has_ft, scale=0.82,
                on_change=lambda e: self._on_source_changed(),
            )
            self._source_checkboxes[p.id] = cb

            badge = ft.Container(
                content=ft.Text("全文" if has_ft else "摘要",
                                size=9, color=ft.colors.WHITE),
                bgcolor=ft.colors.GREEN_700 if has_ft else "#78909C",
                border_radius=8,
                padding=ft.padding.symmetric(horizontal=5, vertical=1),
            )

            title = p.title[:45] + "…" if len(p.title) > 45 else p.title
            year = f" ({p.year})" if p.year else ""

            if has_ft:
                action_btn = ft.IconButton(
                    icon="delete_outline", icon_size=14,
                    tooltip="刪除全文", icon_color=ft.colors.RED_400,
                    on_click=lambda e, pid=p.id: self._on_delete_one(pid),
                )
            else:
                action_btn = ft.IconButton(
                    icon="upload_file", icon_size=14,
                    tooltip="上傳全文", icon_color=ft.colors.GREEN_700,
                    on_click=lambda e, pid=p.id: self._pick_single_pdf(pid),
                )

            self._paper_list_col.controls.append(
                ft.Row([
                    cb, badge,
                    ft.Text(title + year, size=10, expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                    action_btn,
                ], spacing=3, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )

    def _on_source_changed(self):
        selected = {pid for pid, cb in self._source_checkboxes.items() if cb.value}
        all_ids  = set(self._source_checkboxes.keys())
        if not self._source_status:
            return
        if not selected:
            self._source_paper_ids = set()
            self._source_status.value = "⚠️ 未選任何論文"
            self._source_status.color = ft.colors.RED_700
        elif selected == all_ids:
            self._source_paper_ids = None
            self._source_status.value = "（全部論文）"
            self._source_status.color = ft.colors.GREY_600
        else:
            self._source_paper_ids = selected
            self._source_status.value = f"✓ 已選 {len(selected)}/{len(all_ids)} 篇"
            self._source_status.color = ft.colors.GREEN_700
        try:
            if self._source_status.page:
                self._source_status.update()
        except Exception:
            pass

    def _toggle_all_sources(self, value: bool):
        for cb in self._source_checkboxes.values():
            cb.value = value
        self._on_source_changed()
        self.page.update()

    def _on_confirm_source(self, e):
        self._on_source_changed()
        self.page.update()

    # ── 側邊欄 Section 2：跨論文比較 ────────────────────────────────────

    def _build_compare_panel(self) -> ft.Control:
        self._compare_status = ft.Text("", size=11)
        self._compare_q = ft.TextField(
            hint_text="比較問題（選填）",
            multiline=False, height=38,
            border_radius=8,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=0),
        )
        self._compare_col = ft.Column(spacing=3, scroll=ft.ScrollMode.AUTO)
        self._rebuild_compare_list()

        compare_btn = ft.ElevatedButton(
            "分析比較", icon="compare_arrows", height=34,
            style=ft.ButtonStyle(bgcolor="#0277BD", color=ft.colors.WHITE),
            on_click=self._on_compare,
        )

        content = ft.Column([
            ft.Text("勾選 2–6 篇，AI 比較方法異同、數據差異、研究缺口",
                    size=10, color=ft.colors.GREY_600),
            ft.Row([
                ft.TextButton("全選",
                    on_click=lambda e: self._toggle_all_compare(True)),
                ft.TextButton("全不選",
                    on_click=lambda e: self._toggle_all_compare(False)),
            ], spacing=4),
            ft.Container(
                content=self._compare_col,
                height=200,
                border=ft.border.all(1, "#B3E5FC"),
                border_radius=6,
                padding=6,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ),
            self._compare_q,
            ft.Row([compare_btn, self._compare_status], spacing=8,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=6)

        return _sidebar_card(
            "跨論文比較分析", "compare_arrows", "#0277BD",
            content, bgcolor="#E1F5FE", border_color="#81D4FA",
        )

    def _rebuild_compare_list(self):
        if self._compare_col is None:
            return
        self._compare_col.controls.clear()
        self._compare_checkboxes.clear()
        for p in self._sqlite.get_all(limit=500):
            cb = ft.Checkbox(value=False, scale=0.82)
            self._compare_checkboxes[p.id] = cb
            title = p.title[:45] + "…" if len(p.title) > 45 else p.title
            year  = f" ({p.year})" if p.year else ""
            self._compare_col.controls.append(
                ft.Row([
                    cb,
                    ft.Text(title + year, size=10, expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                ], spacing=4)
            )

    def _toggle_all_compare(self, value: bool):
        for cb in self._compare_checkboxes.values():
            cb.value = value
        self.page.update()

    def _on_compare(self, e):
        selected_ids = [pid for pid, cb in self._compare_checkboxes.items() if cb.value]
        if len(selected_ids) < 2:
            self._compare_status.value = "⚠️ 請至少選 2 篇"
            self._compare_status.color = ft.colors.ORANGE_700
            self.page.update()
            return
        if len(selected_ids) > 6:
            self._compare_status.value = "⚠️ 最多 6 篇"
            self._compare_status.color = ft.colors.ORANGE_700
            self.page.update()
            return

        question = (self._compare_q.value or "").strip()
        self._compare_status.value = f"⏳ 分析 {len(selected_ids)} 篇..."
        self._compare_status.color = ft.colors.BLUE_700
        self.page.update()

        def run():
            def prog(msg):
                self._compare_status.value = f"⏳ {msg}"
                self._compare_status.color = ft.colors.BLUE_700
                self.page.update()

            comparer = self._get_comparer()
            result   = comparer.compare(selected_ids, question=question,
                                        progress_callback=prog)

            if not result.success:
                self._compare_status.value = f"❌ {result.error}"
                self._compare_status.color = ft.colors.RED_700
                self.page.update()
                return

            self._compare_status.value = "✅ 完成，結果在右側對話"
            self._compare_status.color = ft.colors.GREEN_700
            titles = "、".join(p.title[:15] + "…" for p in result.papers)
            self._append_compare_result(result, titles)
            self.page.update()

        threading.Thread(target=run, daemon=True).start()

    def _append_compare_result(self, result, titles: str):
        sections = []
        if result.differences:
            sections.append(("方法差異",   result.differences,   "#E53935"))
        if result.similarities:
            sections.append(("共同點",     result.similarities,  "#43A047"))
        if result.research_gaps:
            sections.append(("研究缺口",   result.research_gaps, "#FB8C00"))
        if result.recommendation:
            sections.append(("綜合建議",   result.recommendation, "#5E35B1"))
        if not sections:
            sections = [("比較分析", result.raw_answer, "#0277BD")]

        inner = [
            ft.Row([
                ft.Icon("compare_arrows", size=15, color="#0277BD"),
                ft.Text(f"跨論文比較：{titles}", size=12,
                        weight=ft.FontWeight.W_600, color="#0277BD", expand=True),
            ], spacing=6),
        ]
        for label, content, color in sections:
            inner.append(ft.Container(
                content=ft.Column([
                    ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=color),
                    ft.Text(content, size=12, selectable=True,
                            color=ft.colors.GREY_800),
                ], spacing=4),
                bgcolor="#FAFAFA",
                border=ft.border.only(left=ft.BorderSide(3, color)),
                padding=ft.padding.only(left=10, top=6, bottom=6, right=8),
                border_radius=4,
            ))

        self._chat_column.controls.append(
            ft.Container(
                content=ft.Column(inner, spacing=8),
                bgcolor="#E1F5FE",
                border=ft.border.all(1, "#81D4FA"),
                border_radius=8,
                padding=14,
            )
        )

    # ── 側邊欄 Section 3：PDF 管理（可折疊） ─────────────────────────────

    def _build_pdf_panel(self) -> ft.Control:
        self._pdf_status_text = ft.Text("", size=11)
        self._queue_col = ft.Column(spacing=6)

        add_pdf_btn = ft.ElevatedButton(
            "選擇 PDF", icon="upload_file", height=32,
            on_click=self._pick_multiple_pdfs,
        )
        import_all_btn = ft.ElevatedButton(
            "一鍵匯入", icon="cloud_upload", height=32,
            on_click=self._on_import_all,
            style=ft.ButtonStyle(bgcolor=ft.colors.GREEN_700, color=ft.colors.WHITE),
        )
        new_from_pdf_btn = ft.ElevatedButton(
            "從 PDF 建立新論文", icon="auto_awesome", height=32,
            on_click=self._pick_pdf_for_new_paper,
            style=ft.ButtonStyle(bgcolor="#6A1B9A", color=ft.colors.WHITE),
        )

        self._pdf_mgmt_content = ft.Column([
            ft.Text("為現有論文匯入全文 PDF，或從 PDF 自動建立新論文",
                    size=10, color=ft.colors.GREY_600),
            ft.Row([add_pdf_btn, import_all_btn], spacing=6),
            self._queue_col,
            ft.Divider(height=4),
            new_from_pdf_btn,
            self._pdf_status_text,
        ], spacing=6, visible=False)

        self._pdf_toggle_btn = ft.TextButton(
            text="▶ 展開 PDF 管理",
            on_click=self._toggle_pdf_mgmt,
            style=ft.ButtonStyle(color="#1B5E20"),
        )

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("picture_as_pdf", color="#1B5E20", size=14),
                    _sec_label("PDF 管理", "#1B5E20"),
                    ft.Container(expand=True),
                    self._pdf_toggle_btn,
                ], spacing=6),
                ft.Divider(height=4, color="#C8E6C9"),
                self._pdf_mgmt_content,
            ], spacing=6),
            bgcolor="#F1F8E9",
            border=ft.border.all(1, "#C8E6C9"),
            border_radius=10,
            padding=10,
        )

    def _toggle_pdf_mgmt(self, e):
        self._pdf_mgmt_visible = not self._pdf_mgmt_visible
        self._pdf_mgmt_content.visible = self._pdf_mgmt_visible
        self._pdf_toggle_btn.text = (
            "▼ 收起 PDF 管理" if self._pdf_mgmt_visible else "▶ 展開 PDF 管理"
        )
        self.page.update()

    # ── PDF 上傳事件 ──────────────────────────────────────────────────────

    def _make_paper_options(self) -> list[ft.dropdown.Option]:
        return [
            ft.dropdown.Option(
                str(p.id),
                f"[{p.id}] {p.title[:45]}{'…' if len(p.title) > 45 else ''} ({p.year or '?'})",
            )
            for p in self._sqlite.get_all(limit=500)
        ]

    def _pick_multiple_pdfs(self, e):
        def on_result(result):
            if not result.files:
                return
            opts = self._make_paper_options()
            for f in result.files:
                if not f.path:
                    continue
                dd = ft.Dropdown(hint_text="對應論文", options=opts,
                                 expand=True, dense=True)
                entry = {"path": f.path, "name": f.name, "dd": dd}
                self._upload_queue.append(entry)
                remove_btn = ft.IconButton(
                    icon="close", icon_size=14,
                    on_click=lambda e, en=entry: self._remove_from_queue(en),
                )
                row = ft.Row([
                    ft.Icon("picture_as_pdf", color=ft.colors.RED_400, size=14),
                    ft.Text(f.name, size=10, width=100,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    dd, remove_btn,
                ], spacing=4)
                entry["row"] = row
                self._queue_col.controls.append(row)
            self.page.update()

        picker = ft.FilePicker()
        picker.on_result = on_result
        self.page.overlay.append(picker)
        self.page.update()
        picker.pick_files(dialog_title="選擇 PDF（可多選）",
                          allowed_extensions=["pdf"], allow_multiple=True)

    def _remove_from_queue(self, entry: dict):
        self._upload_queue = [e for e in self._upload_queue if e is not entry]
        if "row" in entry and entry["row"] in self._queue_col.controls:
            self._queue_col.controls.remove(entry["row"])
        self.page.update()

    def _on_import_all(self, e):
        pending = [en for en in self._upload_queue if en.get("dd") and en["dd"].value]
        if not pending:
            self._pdf_status_text.value = "⚠️ 請先為每個 PDF 選擇對應論文"
            self._pdf_status_text.color = ft.colors.ORANGE_700
            self.page.update()
            return

        self._pdf_status_text.value = f"⏳ 匯入 {len(pending)} 個 PDF..."
        self._pdf_status_text.color = ft.colors.ORANGE_700
        self.page.update()

        def run():
            ingestor = self._get_ingestor()
            ok, fail, msgs = 0, 0, []
            for en in pending:
                pid = int(en["dd"].value)
                def _prog(msg, name=en["name"]):
                    self._pdf_status_text.value = f"[{name}] {msg}"
                    self.page.update()
                res = ingestor.ingest(en["path"], pid, replace_existing=True,
                                     progress_callback=_prog)
                if res.success:
                    ok  += 1
                    msgs.append(f"✅ {en['name']}：{res.total_chunks} chunks")
                else:
                    fail += 1
                    msgs.append(f"❌ {en['name']}：{res.error}")
            self._upload_queue.clear()
            self._queue_col.controls.clear()
            self._pdf_status_text.value = (
                f"完成：{ok} 成功，{fail} 失敗\n" + "\n".join(msgs[:6])
            )
            self._pdf_status_text.color = (
                ft.colors.GREEN_700 if fail == 0 else ft.colors.ORANGE_700
            )
            self._rebuild_paper_list()
            self.page.update()

        threading.Thread(target=run, daemon=True).start()

    def _pick_single_pdf(self, paper_id: int):
        def on_result(result):
            if not result.files or not result.files[0].path:
                return
            f = result.files[0]
            self._pdf_status_text.value = f"⏳ 解析 {f.name}..."
            self._pdf_status_text.color = ft.colors.ORANGE_700
            self.page.update()

            def run():
                ingestor = self._get_ingestor()
                def _prog(msg):
                    self._pdf_status_text.value = f"⏳ {msg}"
                    self.page.update()
                res = ingestor.ingest(f.path, paper_id, replace_existing=True,
                                     progress_callback=_prog)
                if res.success:
                    self._pdf_status_text.value = (
                        f"✅ {f.name}：{res.total_chunks} chunks，{res.total_pages} 頁"
                    )
                    self._pdf_status_text.color = ft.colors.GREEN_700
                else:
                    self._pdf_status_text.value = f"❌ 匯入失敗：{res.error}"
                    self._pdf_status_text.color = ft.colors.RED_700
                self._rebuild_paper_list()
                self.page.update()
            threading.Thread(target=run, daemon=True).start()

        picker = ft.FilePicker()
        picker.on_result = on_result
        self.page.overlay.append(picker)
        self.page.update()
        picker.pick_files(dialog_title="選擇 PDF",
                          allowed_extensions=["pdf"], allow_multiple=False)

    def _on_delete_one(self, paper_id: int):
        ingestor = self._get_ingestor()
        deleted = ingestor.delete_fulltext(paper_id)
        self._pdf_status_text.value = f"已刪除 {deleted} 個 chunks"
        self._pdf_status_text.color = ft.colors.GREY_700
        self._rebuild_paper_list()
        self.page.update()

    # ── 從 PDF 建立新論文 ─────────────────────────────────────────────────

    def _pick_pdf_for_new_paper(self, e):
        def on_result(result):
            if not result.files or not result.files[0].path:
                return
            f = result.files[0]
            self._pdf_status_text.value = f"⏳ AI 分析：{f.name}..."
            self._pdf_status_text.color = ft.colors.PURPLE_700
            self.page.update()

            def run():
                def _prog(msg):
                    self._pdf_status_text.value = f"⏳ {msg}"
                    self._pdf_status_text.color = ft.colors.PURPLE_700
                    self.page.update()
                importer = self._get_importer()
                meta = importer.extract_meta(f.path, progress_callback=_prog)
                self._pdf_status_text.value = "完成分析，請確認論文資訊"
                self._pdf_status_text.color = ft.colors.GREEN_700
                self._show_meta_dialog(f.path, f.name, meta)
                self.page.update()
            threading.Thread(target=run, daemon=True).start()

        picker = ft.FilePicker()
        picker.on_result = on_result
        self.page.overlay.append(picker)
        self.page.update()
        picker.pick_files(dialog_title="選擇論文 PDF",
                          allowed_extensions=["pdf"], allow_multiple=False)

    async def _show_meta_dialog(self, pdf_path: str, filename: str, meta: ExtractedMeta):
        title_f = ft.TextField(label="標題 *", value=meta.title,
                               multiline=True, min_lines=1, max_lines=3)
        authors_f = ft.TextField(label="作者（逗號分隔）",
                                 value=", ".join(meta.authors))
        year_f = ft.TextField(label="年份",
                              value=str(meta.year) if meta.year else "", width=100)
        venue_f  = ft.TextField(label="期刊/會議", value=meta.venue, expand=True)
        doi_f    = ft.TextField(label="DOI（選填）", value=meta.doi, expand=True)
        abstract_f = ft.TextField(label="摘要", value=meta.abstract,
                                  multiline=True, min_lines=4, max_lines=8)
        tags_f = ft.TextField(label="標籤（逗號分隔）",
                              value=", ".join(meta.tags))
        status_text = ft.Text("", size=12)

        def _collect_meta() -> ExtractedMeta:
            authors = [a.strip() for a in (authors_f.value or "").split(",") if a.strip()]
            try:
                year = int(year_f.value.strip()) if year_f.value else None
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
            title=ft.Text(f"確認論文資訊：{filename}", size=14,
                          weight=ft.FontWeight.W_600),
            content=ft.Container(
                content=ft.Column([
                    title_f,
                    ft.Row([authors_f, year_f], spacing=8),
                    ft.Row([venue_f, doi_f], spacing=8),
                    abstract_f,
                    tags_f,
                    ft.Container(
                        content=ft.Column([
                            ft.Text("PDF 文字預覽（前 600 字）：", size=11,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.colors.GREY_700),
                            ft.Text(meta.raw_text_preview or "（無預覽）",
                                    size=10, color=ft.colors.GREY_600,
                                    selectable=True),
                        ], spacing=4),
                        bgcolor="#F5F5F5", border_radius=6, padding=8,
                    ),
                    status_text,
                ], spacing=10, scroll=ft.ScrollMode.AUTO),
                width=700, height=520,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog(dlg)),
                ft.ElevatedButton(
                    "確認匯入", icon="save",
                    style=ft.ButtonStyle(bgcolor="#6A1B9A", color=ft.colors.WHITE),
                    on_click=lambda e: self._do_import(
                        dlg, pdf_path, _collect_meta, status_text),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def _close_dialog(self, dlg: ft.AlertDialog):
        dlg.open = False
        self.page.update()

    def _do_import(self, dlg, pdf_path, collect_meta_fn, status_text):
        confirmed_meta = collect_meta_fn()
        if not confirmed_meta.title.strip():
            status_text.value = "⚠️ 標題不能為空"
            status_text.color = ft.colors.RED_700
            self.page.update()
            return
        status_text.value = "⏳ 匯入中..."
        status_text.color = ft.colors.ORANGE_700
        self.page.update()

        def run():
            def _prog(msg):
                status_text.value = f"⏳ {msg}"
                status_text.color = ft.colors.ORANGE_700
                self.page.update()
            importer = self._get_importer()
            result = importer.import_from_pdf(pdf_path, confirmed_meta,
                                              progress_callback=_prog)
            if result.success:
                dlg.open = False
                self._pdf_status_text.value = (
                    f"✅ 已建立 [ID={result.paper_id}]：{confirmed_meta.title[:40]}"
                    + (f"，{result.total_chunks} chunks" if result.total_chunks else "")
                )
                self._pdf_status_text.color = ft.colors.GREEN_700
                self._rebuild_paper_list()
                self._on_source_changed()
            else:
                status_text.value = f"❌ {result.error}"
                status_text.color = ft.colors.RED_700
            self.page.update()
        threading.Thread(target=run, daemon=True).start()

    # ── 聊天事件 ──────────────────────────────────────────────────────────

    def _on_clear(self, e):
        self._history.clear()
        self._last_result = None
        svc = self._get_qa_service()
        if svc:
            svc.memory.clear()
        self._chat_column.controls.clear()
        self._chat_column.controls.append(self._welcome_card())
        self.page.update()

    def _on_send(self, e):
        if self._loading:
            return
        question = (self._input.value or "").strip()
        if not question:
            return

        service = self._get_qa_service()
        if not service:
            self._append_error("未設定 GEMINI_API_KEY，無法使用問答功能。")
            return
        if isinstance(self._source_paper_ids, set) and len(self._source_paper_ids) == 0:
            self._append_error("請先在左側勾選至少一篇參與問答的論文。")
            return

        self._input.value = ""
        self._input.update()
        self._append_user_msg(question)

        loading_ctrl = self._loading_bubble()
        self._chat_column.controls.append(loading_ctrl)
        self._chat_column.update()
        self._set_loading(True)

        context_paper_ids: Optional[set[int]] = None
        if self._last_result and _is_followup(question):
            prev_ids = {sc.paper.id for sc in self._last_result.source_chunks
                        if sc.paper.id}
            if prev_ids:
                context_paper_ids = prev_ids

        def run():
            try:
                result = service.ask(
                    question=question,
                    history=self._history,
                    top_k=self._top_k,
                    filter_paper_ids=self._source_paper_ids,
                    context_paper_ids=context_paper_ids,
                )
                self._history.append(ChatMessage(role="user", content=question))
                self._history.append(ChatMessage(role="assistant",
                                                 content=result.answer))
                self._last_result = result
            except Exception as ex:
                result = QAResult(answer=f"⚠️ 發生錯誤：{ex}", query=question)

            self._chat_column.controls.remove(loading_ctrl)
            self._append_assistant_msg(result)
            self._set_loading(False)
            self._chat_column.update()

        threading.Thread(target=run, daemon=True).start()

    # ── UI 元件工廠 ───────────────────────────────────────────────────────

    def _welcome_card(self) -> ft.Control:
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("auto_awesome", color=ft.colors.BLUE_600),
                    ft.Text("歡迎使用「問論文」！", size=14,
                            weight=ft.FontWeight.W_600),
                ], spacing=6),
                ft.Text(
                    "你可以用自然語言問關於論文庫的任何問題，例如：\n"
                    "• 這些論文最常用什麼研究方法？\n"
                    "• transformer 和 CNN 在這些研究中有什麼差異？\n"
                    "• 左側可勾選要參與問答的論文，或進行跨論文比較",
                    size=12, color=ft.colors.GREY_700,
                ),
            ], spacing=8),
            bgcolor="#E8F4FD", border_radius=8, padding=16,
        )

    def _append_user_msg(self, text: str):
        self._chat_column.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("person", size=14, color=ft.colors.BLUE_700),
                        ft.Text("你", size=11, weight=ft.FontWeight.W_600,
                                color=ft.colors.BLUE_700),
                    ], spacing=4),
                    ft.Text(text, size=13, selectable=True),
                ], spacing=4),
                bgcolor=COLOR_USER_BG, border_radius=8, padding=12,
            )
        )
        self._chat_column.update()

    def _append_assistant_msg(self, result: QAResult):
        source_controls = self._build_source_controls(result.source_chunks)
        self._chat_column.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("smart_toy", size=14, color=ft.colors.PURPLE_700),
                        ft.Text("AI 助理", size=11, weight=ft.FontWeight.W_600,
                                color=ft.colors.PURPLE_700),
                    ], spacing=4),
                    ft.Text(result.answer, size=13, selectable=True),
                    *([ft.Divider(height=6, color=COLOR_BORDER)] + source_controls
                      if source_controls else []),
                ], spacing=6),
                bgcolor=COLOR_ASST_BG, border_radius=8, padding=12,
            )
        )

    def _build_source_controls(self, source_chunks: list[SourceChunk]) -> list[ft.Control]:
        if not source_chunks:
            return []
        controls = [
            ft.Text("引用來源", size=11, color=ft.colors.GREY_600,
                    weight=ft.FontWeight.W_600)
        ]
        paper_sections: dict[int, list] = {}
        for i, sc in enumerate(source_chunks, 1):
            paper_sections.setdefault(sc.paper.id, []).append((i, sc))

        for citation_num, (pid, chunks) in enumerate(paper_sections.items(), 1):
            paper = chunks[0][1].paper
            year_str = f" ({paper.year})" if paper.year else ""
            title = paper.title[:50] + "…" if len(paper.title) > 50 else paper.title

            section_badges = []
            for idx, sc in chunks:
                badge_color = (
                    COLOR_TABLE_BADGE if sc.is_table
                    else COLOR_FULLTEXT_BADGE if sc.is_fulltext
                    else COLOR_ABSTRACT_BADGE
                )
                label = sc.section
                if sc.page_num and sc.is_fulltext:
                    label += f" p.{sc.page_num}"
                section_badges.append(ft.Container(
                    content=ft.Text(label, size=9, color=ft.colors.WHITE),
                    bgcolor=badge_color,
                    border_radius=8,
                    padding=ft.padding.symmetric(horizontal=5, vertical=2),
                ))

            apa_text = _fmt_apa(paper)
            mla_text = _fmt_mla(paper)

            controls.append(ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Text(str(citation_num), size=10,
                                        color=ft.colors.WHITE,
                                        weight=ft.FontWeight.BOLD),
                        bgcolor=ft.colors.PURPLE_400, border_radius=10,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    ),
                    ft.Text(f"{title}{year_str}", size=11,
                            color=ft.colors.GREY_800, expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                    ft.Row(section_badges, spacing=3),
                    ft.Tooltip(
                        message=f"複製 APA：\n{apa_text}",
                        content=ft.TextButton(
                            "APA",
                            style=ft.ButtonStyle(
                                color=ft.colors.INDIGO_600,
                                padding=ft.padding.symmetric(horizontal=6, vertical=0),
                            ),
                            on_click=lambda e, t=apa_text: self.page.set_clipboard(t),
                        ),
                    ),
                    ft.Tooltip(
                        message=f"複製 MLA：\n{mla_text}",
                        content=ft.TextButton(
                            "MLA",
                            style=ft.ButtonStyle(
                                color=ft.colors.TEAL_600,
                                padding=ft.padding.symmetric(horizontal=6, vertical=0),
                            ),
                            on_click=lambda e, t=mla_text: self.page.set_clipboard(t),
                        ),
                    ),
                ], spacing=6),
                bgcolor=COLOR_SOURCE_BG,
                border=ft.border.all(1, COLOR_BORDER),
                border_radius=6,
                padding=ft.padding.symmetric(horizontal=8, vertical=5),
            ))

        controls.append(ft.Row([
            ft.Container(width=10, height=10, bgcolor=COLOR_FULLTEXT_BADGE, border_radius=3),
            ft.Text("全文", size=10, color=ft.colors.GREY_600),
            ft.Container(width=10, height=10, bgcolor=COLOR_TABLE_BADGE, border_radius=3),
            ft.Text("表格", size=10, color=ft.colors.GREY_600),
            ft.Container(width=10, height=10, bgcolor=COLOR_ABSTRACT_BADGE, border_radius=3),
            ft.Text("摘要", size=10, color=ft.colors.GREY_600),
        ], spacing=4))
        return controls

    def _loading_bubble(self) -> ft.Control:
        return ft.Container(
            content=ft.Row([
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                ft.Text("AI 助理正在查閱論文中...", size=12,
                        color=ft.colors.GREY_600, italic=True),
            ], spacing=10),
            bgcolor=COLOR_ASST_BG, border_radius=8, padding=12,
        )

    def _append_error(self, msg: str):
        self._chat_column.controls.append(
            ft.Container(content=ft.Text(msg, size=12, color=ft.colors.RED_700),
                         bgcolor="#FFEBEE", border_radius=8, padding=12)
        )
        self._chat_column.update()

    def _set_loading(self, loading: bool):
        self._loading = loading
        self._send_btn.disabled = loading
        self._send_btn.update()
