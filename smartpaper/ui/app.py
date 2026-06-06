"""
SmartPaper-Tagging 主應用程式
使用 Flet 建立桌面應用程式介面
"""

import threading
import flet as ft

from .views.home_view import HomeView
from .views.papers_view import PapersView
from .views.classify_view import ClassifyView
from .views.writing_guide_view import WritingGuideView
from .views.graph_view import GraphView
from .views.literature_view import LiteratureView
from .views.qa_view import QAView
from .views.settings_view import SettingsView
from .views.timeline_view import TimelineView
from . import theme as T


_NAV_ICON_NAMES = [
    ("home",            "home_outlined",           "首頁"),
    ("library_books",   "library_books_outlined",  "論文管理"),
    ("category",        "category_outlined",       "分類"),
    ("edit_note",       "edit_note_outlined",      "寫作導引"),
    ("bubble_chart",    "bubble_chart_outlined",   "圖譜工具"),
    ("menu_book",       "menu_book_outlined",      "文獻分析"),
    ("question_answer", "question_answer_outlined", "問論文"),
    ("timeline",        "timeline_outlined",       "時間線"),
]


class SmartPaperApp:
    """SmartPaper-Tagging 主應用程式類"""

    def __init__(self, page: ft.Page):
        self.page = page
        self._selected = 0
        self._nav_items_refs: list[ft.Container] = []
        self.setup_page()
        self.setup_navigation()

    def setup_page(self):
        # 基本視窗設定已在 main() 的 splash 階段完成；
        # 這裡只補充尚未設定的屬性即可
        self.page.padding = 0
        self.page.bgcolor = T.PAGE_BG
        self.page.theme_mode = ft.ThemeMode.LIGHT

    # ── Sidebar ───────────────────────────────────────────────────────

    def _build_nav_item(self, idx: int, icon_on, icon_off, label: str) -> ft.Container:
        is_active = idx == self._selected

        icon_ctrl = ft.Icon(
            icon_on if is_active else icon_off,
            color=T.SIDEBAR_ICON_ACT if is_active else T.SIDEBAR_ICON,
            size=18,
        )
        label_widget = ft.Text(
            label,
            size=9,
            weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
            color=T.SIDEBAR_TEXT_ACT if is_active else T.SIDEBAR_TEXT,
            text_align=ft.TextAlign.CENTER,
        )
        item = ft.Container(
            content=ft.Column(
                [icon_ctrl, label_widget],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
                tight=True,
            ),
            padding=ft.padding.symmetric(vertical=8, horizontal=6),
            border_radius=T.RADIUS_M,
            bgcolor=T.SIDEBAR_ACTIVE if is_active else ft.colors.TRANSPARENT,
            animate=T.ANIM,
            tooltip=label,
        )

        def _click(_e, i=idx, c=item):
            T.jelly_tap(c, self.page, lambda: self._on_nav_click(i))

        item.on_click = _click
        return item

    def _build_sidebar(self) -> ft.Container:
        self._nav_items_refs = [
            self._build_nav_item(i, *item)
            for i, item in enumerate(_NAV_ICON_NAMES)
        ]

        logo = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.AUTO_AWESOME_ROUNDED,
                                        color=ft.colors.WHITE, size=16),
                        width=34, height=34,
                        border_radius=T.RADIUS_M,
                        bgcolor=T.ACCENT,
                        alignment=ft.alignment.center,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(vertical=T.SP4),
        )

        self._settings_btn = self._build_settings_btn()

        return ft.Container(
            content=ft.Column(
                [
                    logo,
                    ft.Container(height=1, bgcolor=T.SIDEBAR_BORDER,
                                 margin=ft.margin.symmetric(horizontal=T.SP3)),
                    ft.Container(height=T.SP2),
                    *self._nav_items_refs,
                    ft.Container(expand=True),
                    ft.Container(height=1, bgcolor=T.SIDEBAR_BORDER,
                                 margin=ft.margin.symmetric(horizontal=T.SP3)),
                    self._settings_btn,
                    ft.Container(height=T.SP2),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            width=72,
            bgcolor=T.SIDEBAR_BG,
            border=ft.border.only(right=ft.border.BorderSide(1, T.SIDEBAR_BORDER)),
        )

    def _build_settings_btn(self) -> ft.Container:
        is_active = self._selected == -1
        btn = ft.Container(
            content=ft.Column([
                ft.Icon(
                    ft.icons.SETTINGS if is_active else ft.icons.SETTINGS_OUTLINED,
                    color=T.SIDEBAR_ICON_ACT if is_active else T.SIDEBAR_ICON,
                    size=18,
                ),
                ft.Text("設定", size=9,
                        weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                        color=T.SIDEBAR_TEXT_ACT if is_active else T.SIDEBAR_TEXT,
                        text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4, tight=True),
            padding=ft.padding.symmetric(vertical=8, horizontal=6),
            border_radius=T.RADIUS_M,
            bgcolor=T.SIDEBAR_ACTIVE if is_active else ft.colors.TRANSPARENT,
            animate=T.ANIM,
            tooltip="設定",
        )

        def _click(e, c=btn):
            T.jelly_tap(c, self.page, lambda: self._on_settings_click(e))

        btn.on_click = _click
        return btn

    # ── Navigation ────────────────────────────────────────────────────

    def setup_navigation(self):
        self.home_view = HomeView(self.page)
        self.papers_view = PapersView(self.page)
        self.classify_view = ClassifyView(self.page)
        self.writing_guide_view = WritingGuideView(self.page)
        self.graph_view = GraphView(self.page)
        self.literature_view = LiteratureView(self.page)
        self.qa_view = QAView(self.page)
        self.settings_view = SettingsView(self.page)
        self.timeline_view = TimelineView(self.page)

        try:
            home_content = self.home_view.build()
        except Exception as e:
            import traceback
            home_content = ft.Column([
                ft.Text("⚠ 首頁載入失敗", color="#D32F2F", size=16,
                        weight=ft.FontWeight.BOLD),
                ft.Text(str(e), color="#D32F2F", size=13),
                ft.Text(traceback.format_exc(), size=10, color="#616161",
                        selectable=True),
            ], spacing=12, scroll=ft.ScrollMode.AUTO)

        self.content_area = ft.Container(
            content=home_content,
            expand=True,
            padding=ft.padding.only(top=24, right=24, bottom=24, left=20),
            bgcolor=T.PAGE_BG,
        )

        self._sidebar = self._build_sidebar()

        self.page.add(
            ft.Row(
                [self._sidebar, self.content_area],
                expand=True,
                spacing=0,
            )
        )

    def _on_settings_click(self, e):
        self._selected = -1
        for i, (icon_on, icon_off, label) in enumerate(_NAV_ICON_NAMES):
            new_item = self._build_nav_item(i, icon_on, icon_off, label)
            self._nav_items_refs[i].content = new_item.content
            self._nav_items_refs[i].on_click = new_item.on_click
        new_btn = self._build_settings_btn()
        self._settings_btn.content = new_btn.content
        try:
            self.content_area.content = self.settings_view.build()
        except Exception as ex:
            self.content_area.content = ft.Text(str(ex), color=ft.colors.RED_700)
        self.page.update()

    def _on_nav_click(self, index: int):
        self._selected = index
        # rebuild all nav items to update active state
        for i, (icon_on, icon_off, label) in enumerate(_NAV_ICON_NAMES):
            new_item = self._build_nav_item(i, icon_on, icon_off, label)
            self._nav_items_refs[i].content = new_item.content
            self._nav_items_refs[i].on_click = new_item.on_click
        # reset settings button
        new_btn = self._build_settings_btn()
        self._settings_btn.content = new_btn.content

        views = [
            self.home_view,
            self.papers_view,
            self.classify_view,
            self.writing_guide_view,
            self.graph_view,
            self.literature_view,
            self.qa_view,
            self.timeline_view,
        ]
        try:
            self.content_area.content = views[index].build()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.content_area.content = ft.Column([
                ft.Text("⚠ 頁面載入失敗", color="#D32F2F", size=16,
                        weight=ft.FontWeight.BOLD),
                ft.Text(str(e), color="#D32F2F", size=13),
                ft.Text(tb, size=10, color="#616161", selectable=True),
            ], spacing=12, scroll=ft.ScrollMode.AUTO)
        self.page.update()

    # Keep old handler name for compatibility
    def on_nav_change(self, e):
        self._on_nav_click(e.control.selected_index)  # noqa: used by legacy callers


class ModelPrewarmer:
    """
    在背景執行緒預載 ML 模型，讓使用者打開 QA / 搜尋頁面時不需等待。
    狀態以 status_text 顯示在視窗右下角。
    """

    _MODELS = [
        ("CrossEncoder",       "cross-encoder/ms-marco-MiniLM-L-6-v2",         "cross_encoder"),
        ("對話記憶模型",        "paraphrase-multilingual-MiniLM-L12-v2",         "multilingual"),
        ("語意搜尋模型",        "allenai-specter",                               "specter"),
    ]

    def __init__(self, page: ft.Page):
        self._page = page
        self._status = ft.Text("", size=11, color="#9CA3AF", italic=True)
        self._done = False

    @property
    def status_widget(self) -> ft.Text:
        return self._status

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        for label, model_id, kind in self._MODELS:
            self._set_status(f"載入 {label}...")
            try:
                if kind == "cross_encoder":
                    from sentence_transformers import CrossEncoder
                    CrossEncoder(model_id)
                else:
                    from sentence_transformers import SentenceTransformer
                    SentenceTransformer(model_id)
            except Exception:
                pass  # 失敗不影響啟動，使用時再次嘗試

        self._set_status("")

    def _set_status(self, _msg: str):
        pass  # overlay removed; prewarming runs silently in background


def _build_splash(status_text: ft.Text, progress: ft.ProgressBar) -> ft.Container:
    """啟動載入畫面 — 深色背景，與 sidebar 同色調"""
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Icon(ft.icons.AUTO_AWESOME_ROUNDED,
                                    color=ft.colors.WHITE, size=22),
                    width=48, height=48, border_radius=14,
                    bgcolor="#4F46E5",
                    alignment=ft.alignment.center,
                ),
                ft.Container(height=20),
                ft.Text("SmartPaper", size=26, weight=ft.FontWeight.BOLD,
                        color="#FFFFFF"),
                ft.Text("智能學術文獻管理", size=13, color="#6B7280"),
                ft.Container(height=36),
                progress,
                ft.Container(height=10),
                status_text,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        expand=True,
        alignment=ft.alignment.center,
        bgcolor="#111827",
    )


def main(page: ft.Page):
    """應用程式入口函數"""
    # ── 立即設定視窗並顯示 Splash（讓使用者看到畫面，不再黑屏）──
    page.title = "SmartPaper"
    page.window.width = 1280
    page.window.height = 820
    page.window.min_width = 900
    page.window.min_height = 600
    page.padding = 0
    page.bgcolor = "#111827"
    page.theme_mode = ft.ThemeMode.LIGHT

    status_text = ft.Text("正在啟動…", size=12, color="#6B7280")
    progress = ft.ProgressBar(
        width=220, color="#4F46E5", bgcolor="#1F2937",
        border_radius=4, value=None,   # indeterminate
    )
    splash = _build_splash(status_text, progress)
    page.add(splash)
    page.update()

    # ── 其餘初始化移進背景執行緒，避免 UI 凍結 ──────────────────
    def _init():
        def _status(msg: str):
            status_text.value = msg
            try:
                page.update()
            except Exception:
                pass

        _status("啟動 API 服務…")
        try:
            from ..services.api_server import start as start_api
            start_api()
        except Exception:
            pass

        _status("載入介面元件…")
        try:
            # SmartPaperApp 會呼叫 page.add()，加在 splash 之後
            SmartPaperApp(page)
            # 移除 splash（index 0），保留 SmartPaperApp 加入的 Row
            if page.controls and page.controls[0] is splash:
                page.controls.pop(0)
            page.bgcolor = "#F5F5F5"
            page.update()
        except Exception as e:
            status_text.value = f"❌ 載入失敗：{e}"
            page.update()
            return

        ModelPrewarmer(page).start()

    threading.Thread(target=_init, daemon=True).start()


if __name__ == "__main__":
    ft.app(target=main)
