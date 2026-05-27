"""
問論文（Ask Your Papers）視圖
左欄：來源選擇 / PDF 管理
右欄：聊天區 + 輸入列
"""

import threading
import uuid as _uuid
import flet as ft
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from ...services.qa_service import QAService, ChatMessage, QAResult, SourceChunk
from ...services.qa_service_fc import FunctionCallingQAService
from ...services.pdf_ingestion import PDFIngestionService
from ...services.pdf_import_service import PDFImportService, ExtractedMeta
from ...database.sqlite_db import SQLiteDB
from ...config import GEMINI_API_KEY


MAX_SESSIONS = 5

COLOR_USER_BG        = "#D1FAE5"   # emerald-100，使用者泡泡
COLOR_ASST_BG        = "#F5FDF8"   # 帶綠調的白，助手泡泡
COLOR_SOURCE_BG      = "#F0FDF4"
COLOR_BORDER         = "#6EE7B7"   # emerald-300
COLOR_FULLTEXT_BADGE = "#065F46"   # emerald-900
COLOR_ABSTRACT_BADGE = "#0D9488"   # teal-600
COLOR_TABLE_BADGE    = "#92400E"   # amber-800

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
    """問論文聊天介面（含 PDF 管理）"""

    def __init__(self, page: ft.Page):
        self.page = page
        self._qa_service: Optional[QAService] = None
        self._fc_service: Optional[FunctionCallingQAService] = None
        self._use_fc: bool = False          # Function Calling 模式開關
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
        # Session 管理
        self._sessions: list[dict] = []
        self._current_session_idx: int = 0
        self._session_counter: int = 0
        self._session_bar: Optional[ft.Row] = None
        # 歷史對話面板
        self._history_panel_col: Optional[ft.Column] = None
        # PDF 管理面板 折疊狀態
        self._pdf_mgmt_visible = False
        self._pdf_mgmt_content: Optional[ft.Column] = None
        self._pdf_toggle_btn: Optional[ft.TextButton] = None
        # FilePicker 實例（重用，避免 overlay 累積）
        self._multi_picker: Optional[ft.FilePicker] = None
        self._single_picker: Optional[ft.FilePicker] = None
        self._new_paper_picker: Optional[ft.FilePicker] = None
        self._export_picker: Optional[ft.FilePicker] = None
        # 暫存待寫入的 Markdown 內容（FilePicker on_result 中寫檔）
        self._pending_export_md: str = ""

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

    def _get_fc_service(self) -> Optional[FunctionCallingQAService]:
        if self._fc_service:
            return self._fc_service
        if not GEMINI_API_KEY:
            return None
        try:
            self._fc_service = FunctionCallingQAService()
        except Exception:
            return None
        return self._fc_service

    def _get_active_service(self):
        """回傳當前啟用的 QA 服務（Classic RAG 或 Function Calling）。"""
        if self._use_fc:
            return self._get_fc_service()
        return self._get_qa_service()

    def _get_ingestor(self) -> PDFIngestionService:
        if not self._ingestor:
            self._ingestor = PDFIngestionService()
        return self._ingestor

    def _get_importer(self) -> PDFImportService:
        if not self._importer:
            self._importer = PDFImportService()
        return self._importer

    # ── 主要建構 ──────────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        self._history = []
        # 初始化第一個 session
        self._session_counter = 0
        self._sessions = []
        self._current_session_idx = 0
        first = self._new_session_data()
        self._sessions.append(first)

        # 建立並註冊 FilePicker（各功能重用同一個，不重複加到 overlay）
        self._multi_picker = ft.FilePicker()
        self._single_picker = ft.FilePicker()
        self._new_paper_picker = ft.FilePicker()
        self._export_picker = ft.FilePicker()
        self._export_picker.on_result = self._on_export_picker_result
        self.page.overlay.extend([
            self._multi_picker, self._single_picker,
            self._new_paper_picker, self._export_picker,
        ])

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

        self._session_bar = self._build_session_bar()

        right_col = ft.Column([
            self._session_bar,
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
        ], expand=True, spacing=4)

        # ── 左側：側邊欄 ─────────────────────────────────────────────
        left_col = ft.Container(
            content=ft.Column([
                self._build_history_panel(),
                self._build_source_panel(),
                self._build_pdf_panel(),
            ], spacing=10, scroll=ft.ScrollMode.AUTO),
            width=_SIDEBAR_W,
            padding=ft.padding.only(right=10, top=2),
        )

        self._fc_switch = ft.Switch(
            label="Function Calling 模式",
            value=False,
            active_color="#7C3AED",
            label_style=ft.TextStyle(size=11, color="#7C3AED"),
            on_change=self._on_fc_toggle,
        )

        # ℹ️ 模式說明面板（預設隱藏，點 info 按鈕切換）
        self._mode_info_panel = self._build_mode_info_panel()
        self._mode_info_panel.visible = False

        info_btn = ft.IconButton(
            icon=ft.icons.INFO_OUTLINE,
            icon_color="#7C3AED",
            icon_size=18,
            tooltip="查看兩種模式的差異說明",
            on_click=self._on_toggle_mode_info,
        )

        return ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("問論文", size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("根據論文庫回答問題，有全文的論文提供章節級引用",
                            size=11, color=ft.colors.GREY_600),
                ], spacing=2, expand=True),
                ft.Row([self._fc_switch, info_btn], spacing=0,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self._mode_info_panel,
            ft.Divider(height=1, color=COLOR_BORDER),
            ft.Row([left_col, right_col], expand=True, spacing=0,
                   vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True, spacing=8)

    # ── 側邊欄 Section 0：歷史對話 ───────────────────────────────────────

    def _build_history_panel(self) -> ft.Control:
        new_btn = ft.ElevatedButton(
            "新對話", icon="add", height=30,
            on_click=self._on_new_session,
            style=ft.ButtonStyle(bgcolor="#6D28D9", color=ft.colors.WHITE),
        )
        self._history_panel_col = ft.Column(spacing=3, scroll=ft.ScrollMode.AUTO)
        self._refresh_history_panel()

        return _sidebar_card(
            "歷史對話", "history", "#6D28D9",
            ft.Column([
                new_btn,
                ft.Container(
                    content=self._history_panel_col,
                    height=220,
                    border=ft.border.all(1, "#DDD6FE"),
                    border_radius=6,
                    padding=ft.padding.symmetric(horizontal=6, vertical=4),
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ),
            ], spacing=6),
            bgcolor="#F5F3FF",
            border_color="#DDD6FE",
        )

    def _date_group(self, updated_at_str: str) -> str:
        try:
            dt = datetime.fromisoformat(updated_at_str).date()
            today = date.today()
            if dt == today:
                return "今天"
            if dt == today - timedelta(days=1):
                return "昨天"
            if dt >= today - timedelta(days=7):
                return "本週"
            return datetime.fromisoformat(updated_at_str).strftime("%Y/%m")
        except Exception:
            return "更早"

    def _refresh_history_panel(self):
        if self._history_panel_col is None:
            return
        self._history_panel_col.controls.clear()

        try:
            sessions = self._sqlite.get_chat_sessions()
        except Exception:
            sessions = []

        if not sessions:
            self._history_panel_col.controls.append(
                ft.Text("（還沒有歷史對話）", size=11,
                        color=ft.colors.GREY_500, italic=True)
            )
            return

        active_uuid = (
            self._sessions[self._current_session_idx].get("uuid", "")
            if self._sessions and self._current_session_idx < len(self._sessions)
            else ""
        )

        # Group by date label, preserving order
        groups: dict[str, list] = {}
        for s in sessions:
            label = self._date_group(s.get("updated_at", ""))
            groups.setdefault(label, []).append(s)

        group_order = ["今天", "昨天", "本週"]
        seen = set()
        for g in group_order:
            if g in groups:
                self._render_history_group(g, groups[g], active_uuid)
                seen.add(g)
        for g, items in groups.items():
            if g not in seen:
                self._render_history_group(g, items, active_uuid)

    def _render_history_group(self, label: str, sessions: list, active_uuid: str):
        self._history_panel_col.controls.append(
            ft.Text(label, size=9, weight=ft.FontWeight.W_600,
                    color=ft.colors.GREY_500)
        )
        for s in sessions:
            uuid = s["session_id"]
            is_active = (uuid == active_uuid)
            title = s["title"]
            display = title[:24] + ("…" if len(title) > 24 else "")
            self._history_panel_col.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(
                            display, size=11, expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                            weight=ft.FontWeight.W_600 if is_active
                                   else ft.FontWeight.NORMAL,
                            color="#6D28D9" if is_active else "#374151",
                        ),
                        ft.IconButton(
                            icon="delete_outline", icon_size=12,
                            icon_color=ft.colors.GREY_400,
                            tooltip="刪除此對話",
                            on_click=lambda e, uid=uuid: self._on_delete_history(uid),
                            style=ft.ButtonStyle(padding=ft.padding.all(0)),
                        ),
                    ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor="#EDE9FE" if is_active else "#FFFFFF",
                    border=ft.border.all(1, "#7C3AED" if is_active else "#E2E8F0"),
                    border_radius=6,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    on_click=lambda e, uid=uuid: self._on_load_history_session(uid),
                    ink=not is_active,
                )
            )

    def _on_load_history_session(self, session_uuid: str):
        """點擊歷史對話項目：若在記憶體中直接切換，否則從 SQLite 載入。"""
        for i, s in enumerate(self._sessions):
            if s.get("uuid") == session_uuid:
                self._switch_session(i)
                self._refresh_history_panel()
                try:
                    self._history_panel_col.update()
                except Exception:
                    self.page.update()
                return

        # 從 SQLite 載入
        self._save_current_session()
        try:
            all_sessions = self._sqlite.get_chat_sessions()
            info = next((x for x in all_sessions
                         if x["session_id"] == session_uuid), None)
            if not info:
                return
            db_msgs = self._sqlite.get_chat_messages(session_uuid)
        except Exception as ex:
            self._append_error(f"載入歷史對話失敗：{ex}")
            return

        self._session_counter += 1
        session = {
            "id":              self._session_counter,
            "uuid":            session_uuid,
            "title":           info["title"],
            "history":         [],
            "messages":        [],
            "source_paper_ids": None,
            "last_result":     None,
        }
        for msg in db_msgs:
            content = msg["content"]
            if msg["role"] == "user":
                session["history"].append(ChatMessage(role="user", content=content))
                session["messages"].append({"type": "user", "text": content})
            elif msg["role"] == "assistant":
                result = QAResult(answer=content, query="")
                session["history"].append(
                    ChatMessage(role="assistant", content=content))
                session["messages"].append({"type": "assistant", "result": result})

        # 若 tab 已滿，替換掉最舊的非當前 session
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = next(
                (i for i in range(len(self._sessions))
                 if i != self._current_session_idx),
                None,
            )
            if oldest is not None:
                self._sessions.pop(oldest)
                if oldest < self._current_session_idx:
                    self._current_session_idx -= 1

        self._sessions.append(session)
        self._current_session_idx = len(self._sessions) - 1
        self._history            = session["history"]
        self._source_paper_ids   = None
        self._last_result        = None
        self._restore_session(session)
        self._rebuild_session_bar()
        self._refresh_history_panel()
        self.page.update()

    def _on_delete_history(self, session_uuid: str):
        """從歷史面板刪除對話（SQLite + 記憶體）。"""
        try:
            self._sqlite.delete_chat_session(session_uuid)
        except Exception:
            pass

        for i, s in enumerate(self._sessions):
            if s.get("uuid") == session_uuid:
                self._delete_session(i)
                break

        self._refresh_history_panel()
        try:
            self._history_panel_col.update()
        except Exception:
            self.page.update()

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
                value=True,  # 預設全選，讓摘要論文也參與問答
                scale=0.82,
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

    # ── 側邊欄 Section 2：PDF 管理（可折疊） ─────────────────────────────

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

        self._multi_picker.on_result = on_result
        self._multi_picker.pick_files(dialog_title="選擇 PDF（可多選）",
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

        self._single_picker.on_result = on_result
        self._single_picker.pick_files(dialog_title="選擇 PDF",
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

        self._new_paper_picker.on_result = on_result
        self._new_paper_picker.pick_files(dialog_title="選擇論文 PDF",
                                          allowed_extensions=["pdf"], allow_multiple=False)

    def _show_meta_dialog(self, pdf_path: str, filename: str, meta: ExtractedMeta):
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

    # ── Session 管理 ──────────────────────────────────────────────────────

    def _new_session_data(self) -> dict:
        self._session_counter += 1
        session_uuid = str(_uuid.uuid4())
        title = f"對話 {self._session_counter}"
        try:
            self._sqlite.save_chat_session(session_uuid, title)
        except Exception:
            pass
        return {
            "id": self._session_counter,
            "uuid": session_uuid,
            "title": title,
            "history": [],
            "messages": [],   # list of {type, ...} for re-rendering
            "source_paper_ids": None,
            "last_result": None,
        }

    def _build_session_bar(self) -> ft.Row:
        tabs = [self._build_session_tab(i, s) for i, s in enumerate(self._sessions)]
        new_btn = ft.IconButton(
            icon="add_circle_outline",
            tooltip=f"新對話（最多 {MAX_SESSIONS} 個）",
            icon_color="#1D4ED8", icon_size=18,
            on_click=self._on_new_session,
        )
        export_btn = ft.IconButton(
            icon="download",
            tooltip="匯出目前對話為 Markdown",
            icon_color="#059669", icon_size=18,
            on_click=self._on_export_session,
        )
        return ft.Row(
            tabs + [new_btn, export_btn],
            spacing=4, scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_session_tab(self, idx: int, session: dict) -> ft.Container:
        is_active = (idx == self._current_session_idx)
        return ft.Container(
            content=ft.Row([
                ft.Text(
                    session["title"][:22] + ("…" if len(session["title"]) > 22 else ""),
                    size=12,
                    color="#1D4ED8" if is_active else "#64748B",
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                ),
                ft.IconButton(
                    icon="close", icon_size=13,
                    icon_color="#94A3B8",
                    tooltip="刪除此對話",
                    on_click=lambda e, i=idx: self._delete_session(i),
                    style=ft.ButtonStyle(
                        padding=ft.padding.all(0),
                    ),
                ),
            ], spacing=0, tight=True,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor="#DBEAFE" if is_active else "#F8FAFC",
            border=ft.border.all(1, "#3B82F6" if is_active else "#E2E8F0"),
            border_radius=6,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
            on_click=lambda e, i=idx: self._switch_session(i),
            ink=not is_active,
        )

    def _rebuild_session_bar(self):
        if self._session_bar is None:
            return
        tabs = [self._build_session_tab(i, s) for i, s in enumerate(self._sessions)]
        new_btn = ft.IconButton(
            icon="add_circle_outline",
            tooltip=f"新對話（最多 {MAX_SESSIONS} 個）",
            icon_color="#1D4ED8", icon_size=18,
            on_click=self._on_new_session,
        )
        export_btn = ft.IconButton(
            icon="download",
            tooltip="匯出目前對話為 Markdown",
            icon_color="#059669", icon_size=18,
            on_click=self._on_export_session,
        )
        self._session_bar.controls = tabs + [new_btn, export_btn]

    def _save_current_session(self):
        if not self._sessions:
            return
        s = self._sessions[self._current_session_idx]
        s["history"] = list(self._history)
        s["source_paper_ids"] = self._source_paper_ids
        s["last_result"] = self._last_result

    def _restore_session(self, session: dict):
        """清空聊天欄並從 session 紀錄重新渲染。"""
        self._chat_column.controls.clear()
        if not session["messages"]:
            self._chat_column.controls.append(self._welcome_card())
            return
        for msg in session["messages"]:
            if msg["type"] == "user":
                self._append_user_msg(msg["text"], _update=False)
            elif msg["type"] == "assistant":
                self._append_assistant_msg(msg["result"])
            elif msg["type"] == "chips":
                self._append_followup_chips(msg["suggestions"])

    def _switch_session(self, idx: int):
        if idx == self._current_session_idx:
            return
        self._save_current_session()
        self._current_session_idx = idx
        session = self._sessions[idx]
        self._history = session["history"]
        self._source_paper_ids = session["source_paper_ids"]
        self._last_result = session["last_result"]
        self._restore_session(session)
        self._on_source_changed()
        self._rebuild_session_bar()
        self.page.update()

    def _on_new_session(self, e):
        if len(self._sessions) >= MAX_SESSIONS:
            self._append_error(
                f"最多保留 {MAX_SESSIONS} 個對話，請先刪除不需要的對話。"
            )
            return
        self._save_current_session()
        new_s = self._new_session_data()
        self._sessions.append(new_s)
        self._current_session_idx = len(self._sessions) - 1
        self._history = new_s["history"]
        self._source_paper_ids = None
        self._last_result = None
        self._restore_session(new_s)
        self._rebuild_session_bar()
        self._refresh_history_panel()
        self.page.update()

    def _delete_session(self, idx: int):
        if len(self._sessions) == 1:
            # 最後一個 session：只清空，不刪除
            self._on_clear(None)
            return
        uuid_to_delete = self._sessions[idx].get("uuid", "")
        if uuid_to_delete:
            try:
                self._sqlite.delete_chat_session(uuid_to_delete)
            except Exception:
                pass
        self._sessions.pop(idx)
        new_idx = max(0, min(self._current_session_idx, len(self._sessions) - 1))
        if idx < self._current_session_idx:
            new_idx = self._current_session_idx - 1
        self._current_session_idx = new_idx
        session = self._sessions[new_idx]
        self._history = session["history"]
        self._source_paper_ids = session["source_paper_ids"]
        self._last_result = session["last_result"]
        self._restore_session(session)
        self._on_source_changed()
        self._rebuild_session_bar()
        self.page.update()

    # ── 聊天事件 ──────────────────────────────────────────────────────────

    def _on_clear(self, e):
        session = self._sessions[self._current_session_idx]
        session["history"].clear()
        session["messages"].clear()
        session["last_result"] = None
        self._history = session["history"]
        self._last_result = None
        svc = self._get_qa_service()
        if svc:
            svc.memory.clear()
        self._chat_column.controls.clear()
        self._chat_column.controls.append(self._welcome_card())
        if e is not None:
            self.page.update()

    def _build_mode_info_panel(self) -> ft.Container:
        def _row(icon, color, label, desc):
            return ft.Row([
                ft.Icon(icon, color=color, size=16),
                ft.Column([
                    ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=color),
                    ft.Text(desc, size=11, color="#374151"),
                ], spacing=2, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon("compare_arrows", color="#1D4ED8", size=16),
                    ft.Text("兩種問答模式說明", size=13, weight=ft.FontWeight.W_600,
                            color="#1D4ED8"),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon="close", icon_size=14, icon_color="#9CA3AF",
                        tooltip="關閉",
                        on_click=self._on_toggle_mode_info,
                    ),
                ], spacing=6),
                ft.Divider(height=4, color="#DBEAFE"),
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            _row("search", "#1565C0", "Classic RAG",
                                 "直接向量搜尋最相似段落，速度快，適合精準引用查詢"),
                            ft.Container(height=4),
                            ft.Text("優點：速度快、引用來源明確", size=10, color="#6B7280"),
                            ft.Text("適合：「這篇論文提到什麼方法？」", size=10, color="#6B7280"),
                        ], spacing=4),
                        expand=True,
                        bgcolor="#EFF6FF",
                        border=ft.border.all(1, "#BFDBFE"),
                        border_radius=8,
                        padding=10,
                    ),
                    ft.Container(
                        content=ft.Column([
                            _row("smart_toy", "#7C3AED", "Function Calling",
                                 "AI 自主決定呼叫哪些工具，可跨多篇論文整合分析"),
                            ft.Container(height=4),
                            ft.Text("優點：推理更靈活、可比較多篇", size=10, color="#6B7280"),
                            ft.Text("適合：「比較這幾篇論文的研究方法」", size=10, color="#6B7280"),
                        ], spacing=4),
                        expand=True,
                        bgcolor="#F5F3FF",
                        border=ft.border.all(1, "#DDD6FE"),
                        border_radius=8,
                        padding=10,
                    ),
                ], spacing=8),
            ], spacing=8),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, "#DBEAFE"),
            border_radius=10,
            padding=12,
        )

    def _on_toggle_mode_info(self, e):
        self._mode_info_panel.visible = not self._mode_info_panel.visible
        self.page.update()

    def _on_fc_toggle(self, e):
        self._use_fc = e.control.value
        mode = "Function Calling" if self._use_fc else "Classic RAG"
        self._fc_switch.label = f"{mode} 模式"
        self._fc_switch.update()
        # 在聊天中插入切換提示
        label = "Function Calling 模式" if self._use_fc else "Classic RAG 模式"
        color = "#7C3AED" if self._use_fc else "#1565C0"
        icon  = "smart_toy" if self._use_fc else "search"
        desc  = "AI 自主決定呼叫哪些工具進行推理" if self._use_fc else "向量搜尋直接返回相關段落"
        self._chat_column.controls.append(
            ft.Container(
                content=ft.Row([
                    ft.Icon(icon, color=color, size=14),
                    ft.Text(f"已切換至 {label}　·　{desc}",
                            size=11, color=color, italic=True),
                ], spacing=6),
                bgcolor="#F8F9FA",
                border=ft.border.all(1, "#E9ECEF"),
                border_radius=6,
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
            )
        )
        self._chat_column.update()

    def _on_send(self, e):
        if self._loading:
            return
        question = (self._input.value or "").strip()
        if not question:
            return

        service = self._get_active_service()
        if not service:
            self._append_error("未設定 GEMINI_API_KEY，無法使用問答功能。")
            return
        if isinstance(self._source_paper_ids, set) and len(self._source_paper_ids) == 0:
            self._append_error("請先在左側勾選至少一篇參與問答的論文。")
            return

        self._input.value = ""
        self._input.update()
        self._append_user_msg(question)

        # 儲存到 session，第一條問題自動命名 session
        session = self._sessions[self._current_session_idx]
        is_first_msg = len(session["messages"]) == 0
        session["messages"].append({"type": "user", "text": question})
        if is_first_msg:
            session["title"] = question[:22] + ("…" if len(question) > 22 else "")
            try:
                self._sqlite.update_chat_session_title(session["uuid"], session["title"])
            except Exception:
                pass
            self._rebuild_session_bar()
            self._session_bar.update()
            self._refresh_history_panel()

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
                # ── 串流模式（僅 QAService 支援，FC 模式仍用阻塞式）
                use_stream = not self._use_fc and hasattr(service, "ask_stream")
                if use_stream:
                    stream = service.ask_stream(
                        question=question,
                        history=self._history,
                        top_k=self._top_k,
                        filter_paper_ids=self._source_paper_ids,
                        context_paper_ids=context_paper_ids,
                    )
                    result = None
                    answer_text_ctrl: Optional[ft.Text] = None
                    answer_container: Optional[ft.Container] = None

                    for item in stream:
                        if item is None:
                            break
                        elif isinstance(item, QAResult):
                            # 第一個 yield：建立 UI 骨架（含 sources）
                            result = item
                            self._chat_column.controls.remove(loading_ctrl)
                            answer_text_ctrl, answer_container = \
                                self._append_assistant_msg_streaming(result)
                            self._chat_column.update()
                        elif isinstance(item, str) and answer_text_ctrl is not None:
                            # 後續 yield：逐 token 更新文字
                            answer_text_ctrl.value = (answer_text_ctrl.value or "") + item
                            answer_text_ctrl.update()

                    if result is None:
                        result = QAResult(answer="⚠️ 串流中斷", query=question)
                else:
                    result = service.ask(
                        question=question,
                        history=self._history,
                        top_k=self._top_k,
                        filter_paper_ids=self._source_paper_ids,
                        context_paper_ids=context_paper_ids,
                    )
                    self._chat_column.controls.remove(loading_ctrl)
                    self._append_assistant_msg(result)
                    self._chat_column.update()

                self._history.append(ChatMessage(role="user", content=question))
                self._history.append(ChatMessage(role="assistant", content=result.answer))
                self._last_result = result

                # SQLite 持久化
                try:
                    sess_uuid = self._sessions[self._current_session_idx].get("uuid", "")
                    if sess_uuid:
                        self._sqlite.save_chat_message(sess_uuid, "user", question)
                        sources_str = ",".join(
                            str(sc.paper.id) for sc in (result.source_chunks or [])
                        )
                        self._sqlite.save_chat_message(
                            sess_uuid, "assistant", result.answer,
                            intent_tag=result.intent or "",
                            is_cached=result.cache_hit,
                            sources=sources_str,
                        )
                except Exception:
                    pass

            except Exception as ex:
                result = QAResult(answer=f"⚠️ 發生錯誤：{ex}", query=question)
                self._chat_column.controls.remove(loading_ctrl)
                self._append_assistant_msg(result)
                self._chat_column.update()

            self._sessions[self._current_session_idx]["messages"].append(
                {"type": "assistant", "result": result}
            )
            self._sessions[self._current_session_idx]["last_result"] = result
            self._set_loading(False)

            # 追問建議
            captured_answer = result.answer
            def _suggest():
                try:
                    suggestions = service.suggest_followups(question, captured_answer)
                    if suggestions and not self._loading:
                        self._append_followup_chips(suggestions)
                        self._sessions[self._current_session_idx]["messages"].append(
                            {"type": "chips", "suggestions": suggestions}
                        )
                        self._chat_column.update()
                except Exception:
                    pass
            threading.Thread(target=_suggest, daemon=True).start()

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
                    "• 左側勾選論文後直接提問，AI 會根據所選文獻回答",
                    size=12, color=ft.colors.GREY_700,
                ),
            ], spacing=8),
            bgcolor="#E8F4FD", border_radius=8, padding=16,
        )

    def _append_user_msg(self, text: str, _update: bool = True):
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
        if _update:
            self._chat_column.update()

    def _intent_chip(self, result: QAResult) -> Optional[ft.Control]:
        """回傳意圖指示器 chip（None 表示無需顯示）。"""
        chips = []
        intent_map = {
            "qa":       ("search",    ft.colors.BLUE_700,   "Classic RAG"),
            "action":   ("bolt",      ft.colors.ORANGE_700, "操作指令"),
            "chitchat": ("chat",      ft.colors.GREY_600,   "閒聊"),
        }
        icon, color, label = intent_map.get(result.intent, ("help", ft.colors.GREY_500, result.intent))
        chips.append(ft.Container(
            content=ft.Row([
                ft.Icon(icon, color=color, size=11),
                ft.Text(f"{label} {result.intent_conf:.0%}", size=9, color=color),
            ], spacing=3, tight=True),
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            border_radius=50,
            bgcolor=ft.colors.with_opacity(0.08, color),
            border=ft.border.all(1, ft.colors.with_opacity(0.25, color)),
        ))
        if result.cache_hit:
            chips.append(ft.Container(
                content=ft.Row([
                    ft.Icon("flash_on", color="#0D9488", size=11),
                    ft.Text(f"快取命中", size=9, color="#0D9488"),
                ], spacing=3, tight=True),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=50,
                bgcolor="#F0FDFA",
                border=ft.border.all(1, "#99F6E4"),
            ))
        return ft.Row(chips, spacing=6) if chips else None

    def _append_assistant_msg(self, result: QAResult):
        source_controls = self._build_source_controls(result.source_chunks)
        intent_chip = self._intent_chip(result)
        header_row = ft.Row([
            ft.Icon("smart_toy", size=14, color=ft.colors.PURPLE_700),
            ft.Text("AI 助理", size=11, weight=ft.FontWeight.W_600,
                    color=ft.colors.PURPLE_700),
            ft.Container(expand=True),
            *([intent_chip] if intent_chip else []),
        ], spacing=4)
        self._chat_column.controls.append(
            ft.Container(
                content=ft.Column([
                    header_row,
                    ft.Text(result.answer, size=13, selectable=True),
                    *([ft.Divider(height=6, color=COLOR_BORDER)] + source_controls
                      if source_controls else []),
                ], spacing=6),
                bgcolor=COLOR_ASST_BG, border_radius=8, padding=12,
            )
        )

    def _append_assistant_msg_streaming(self, result: QAResult):
        """
        建立串流 UI 骨架，回傳 (answer_text_ctrl, container) 供呼叫端逐步更新文字。
        """
        source_controls = self._build_source_controls(result.source_chunks)
        intent_chip = self._intent_chip(result)
        header_row = ft.Row([
            ft.Icon("smart_toy", size=14, color=ft.colors.PURPLE_700),
            ft.Text("AI 助理", size=11, weight=ft.FontWeight.W_600,
                    color=ft.colors.PURPLE_700),
            ft.Container(expand=True),
            *([intent_chip] if intent_chip else []),
        ], spacing=4)
        answer_text = ft.Text("", size=13, selectable=True)
        container = ft.Container(
            content=ft.Column([
                header_row,
                answer_text,
                *([ft.Divider(height=6, color=COLOR_BORDER)] + source_controls
                  if source_controls else []),
            ], spacing=6),
            bgcolor=COLOR_ASST_BG, border_radius=8, padding=12,
        )
        self._chat_column.controls.append(container)
        return answer_text, container

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
                    ft.TextButton(
                        "APA",
                        tooltip=f"複製 APA：\n{apa_text}",
                        style=ft.ButtonStyle(
                            color=ft.colors.INDIGO_600,
                            padding=ft.padding.symmetric(horizontal=6, vertical=0),
                        ),
                        on_click=lambda e, t=apa_text: self.page.set_clipboard(t),
                    ),
                    ft.TextButton(
                        "MLA",
                        tooltip=f"複製 MLA：\n{mla_text}",
                        style=ft.ButtonStyle(
                            color=ft.colors.TEAL_600,
                            padding=ft.padding.symmetric(horizontal=6, vertical=0),
                        ),
                        on_click=lambda e, t=mla_text: self.page.set_clipboard(t),
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

    def _append_followup_chips(self, suggestions: list[str]):
        """在聊天區末尾加上引導式追問按鈕"""
        chips = []
        for q in suggestions:
            chips.append(ft.OutlinedButton(
                text=q,
                icon="chat_bubble_outline",
                on_click=lambda e, text=q: self._fill_input(text),
                style=ft.ButtonStyle(
                    color="#1D4ED8",
                    side=ft.BorderSide(1, "#BFDBFE"),
                    shape=ft.RoundedRectangleBorder(radius=20),
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                ),
            ))
        self._chat_column.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon("lightbulb_outline", size=12, color="#6366F1"),
                        ft.Text("可以繼續問：", size=11, color="#6366F1",
                                italic=True),
                    ], spacing=4),
                    ft.Row(chips, spacing=8, wrap=True),
                ], spacing=6),
                padding=ft.padding.only(left=12, top=6, bottom=2),
            )
        )

    def _fill_input(self, text: str):
        self._input.value = text
        self._input.update()
        self._input.focus()

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

    # ── 匯出對話 Markdown ─────────────────────────────────────────────────

    def _on_export_session(self, e):
        session = self._sessions[self._current_session_idx]
        if not any(m["type"] in ("user", "assistant") for m in session["messages"]):
            self._append_error("目前對話是空的，無法匯出。")
            return

        lines: list[str] = [
            f"# {session['title']}",
            f"> 匯出時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for msg in session["messages"]:
            if msg["type"] == "user":
                lines += [f"## 你\n\n{msg['text']}\n"]
            elif msg["type"] == "assistant":
                result = msg["result"]
                lines += [f"## AI 助理\n\n{result.answer}\n"]
                chunks = result.source_chunks or []
                if chunks:
                    lines.append("### 引用來源\n")
                    seen: set[int] = set()
                    for i, sc in enumerate(chunks, 1):
                        pid = sc.paper.id
                        if pid in seen:
                            continue
                        seen.add(pid)
                        year = f" ({sc.paper.year})" if sc.paper.year else ""
                        lines.append(f"{i}. **{sc.paper.title}**{year}")
                        if sc.paper.doi:
                            lines.append(f"   doi:{sc.paper.doi}")
                    lines.append("")

        self._pending_export_md = "\n".join(lines)
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in session["title"])
        self._export_picker.save_file(
            dialog_title="儲存對話記錄",
            file_name=f"{safe_title}.md",
            allowed_extensions=["md"],
        )

    def _on_export_picker_result(self, e):
        if not e.path or not self._pending_export_md:
            return
        try:
            Path(e.path).write_text(self._pending_export_md, encoding="utf-8")
            self._chat_column.controls.append(
                ft.Container(
                    content=ft.Text(f"✅ 對話已匯出至：{Path(e.path).name}",
                                    size=12, color=ft.colors.GREEN_700),
                    bgcolor="#E8F5E9", border_radius=8, padding=10,
                )
            )
        except Exception as ex:
            self._append_error(f"❌ 匯出失敗：{ex}")
        finally:
            self._pending_export_md = ""
        self._chat_column.update()

    def _set_loading(self, loading: bool):
        self._loading = loading
        self._send_btn.disabled = loading
        self._send_btn.update()
