"""
SmartPaper-Tagging 主應用程式
使用 Flet 建立桌面應用程式介面
"""

import threading
import flet as ft

from .views.home_view import HomeView
from .views.papers_view import PapersView
from .views.search_view import SearchView
from .views.classify_view import ClassifyView
from .views.writing_guide_view import WritingGuideView
from .views.graph_view import GraphView
from .views.literature_view import LiteratureView
from .views.qa_view import QAView
from . import theme as T


_NAV_ICON_NAMES = [
    ("home",            "home_outlined",           "首頁"),
    ("library_books",   "library_books_outlined",  "論文管理"),
    ("search",          "search_outlined",         "搜尋"),
    ("category",        "category_outlined",       "分類"),
    ("edit_note",       "edit_note_outlined",      "寫作導引"),
    ("bubble_chart",    "bubble_chart_outlined",   "圖譜工具"),
    ("menu_book",       "menu_book_outlined",      "文獻分析"),
    ("question_answer", "question_answer_outlined", "問論文"),
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
        self.page.title = "SmartPaper"
        self.page.window.width = 1280
        self.page.window.height = 820
        self.page.window.min_width = 900
        self.page.window.min_height = 600
        self.page.padding = 0
        self.page.bgcolor = T.PAGE_BG
        self.page.theme_mode = ft.ThemeMode.LIGHT

    # ── Sidebar ───────────────────────────────────────────────────────

    def _build_nav_item(self, idx: int, icon_on, icon_off, label: str) -> ft.Container:
        is_active = idx == self._selected

        indicator = ft.Container(
            content=ft.Icon(
                icon_on if is_active else icon_off,
                color=T.ACCENT if is_active else T.TEXT_M,
                size=20,
            ),
            width=46,
            height=40,
            border_radius=12,
            bgcolor=T.ACCENT_SOFT if is_active else ft.colors.TRANSPARENT,
            alignment=ft.alignment.center,
            animate=ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        label_widget = ft.Text(
            label,
            size=10,
            weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
            color=T.ACCENT if is_active else T.TEXT_M,
            text_align=ft.TextAlign.CENTER,
        )

        item = ft.Container(
            content=ft.Column(
                [indicator, label_widget],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=3,
                tight=True,
            ),
            padding=ft.padding.symmetric(vertical=6, horizontal=8),
            border_radius=14,
            on_click=lambda e, i=idx: self._on_nav_click(i),
            tooltip=label,
        )
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
                        content=ft.Icon(ft.icons.AUTO_AWESOME_ROUNDED, color=ft.colors.WHITE, size=18),
                        width=38,
                        height=38,
                        border_radius=12,
                        bgcolor=T.ACCENT,
                        alignment=ft.alignment.center,
                        shadow=ft.BoxShadow(
                            blur_radius=12,
                            color="#4D6366F1",   # 30% ACCENT
                            offset=ft.Offset(0, 4),
                        ),
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(vertical=16),
        )

        return ft.Container(
            content=ft.Column(
                [
                    logo,
                    ft.Container(height=1, bgcolor=T.CARD_BORDER, margin=ft.margin.symmetric(horizontal=12)),
                    ft.Container(height=8),
                    *self._nav_items_refs,
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=76,
            bgcolor=T.SIDEBAR_BG,
            border=ft.border.only(right=ft.border.BorderSide(1, T.CARD_BORDER)),
            shadow=ft.BoxShadow(
                blur_radius=20,
                spread_radius=-4,
                color="#0F000000",   # 6% black
                offset=ft.Offset(4, 0),
            ),
        )

    # ── Navigation ────────────────────────────────────────────────────

    def setup_navigation(self):
        self.home_view = HomeView(self.page)
        self.papers_view = PapersView(self.page)
        self.search_view = SearchView(self.page)
        self.classify_view = ClassifyView(self.page)
        self.writing_guide_view = WritingGuideView(self.page)
        self.graph_view = GraphView(self.page)
        self.literature_view = LiteratureView(self.page)
        self.qa_view = QAView(self.page)

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
        )

        self._sidebar = self._build_sidebar()

        self.page.add(
            ft.Row(
                [self._sidebar, self.content_area],
                expand=True,
                spacing=0,
            )
        )

    def _on_nav_click(self, index: int):
        self._selected = index
        # rebuild all nav items to update active state
        for i, (icon_on, icon_off, label) in enumerate(_NAV_ICON_NAMES):
            new_item = self._build_nav_item(i, icon_on, icon_off, label)
            self._nav_items_refs[i].content = new_item.content
            self._nav_items_refs[i].on_click = new_item.on_click

        views = [
            self.home_view,
            self.papers_view,
            self.search_view,
            self.classify_view,
            self.writing_guide_view,
            self.graph_view,
            self.literature_view,
            self.qa_view,
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

    def _set_status(self, msg: str):
        pass  # overlay removed; prewarming runs silently in background


def main(page: ft.Page):
    """應用程式入口函數"""
    # 啟動本地 API server（供 Bookmarklet 呼叫，port 7878）
    from ..services.api_server import start as start_api
    start_api()

    SmartPaperApp(page)
    ModelPrewarmer(page).start()


if __name__ == "__main__":
    ft.app(target=main)
