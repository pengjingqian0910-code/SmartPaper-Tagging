"""
設定頁面：管理 Gemini API Key 與模型選擇
"""

import threading
import flet as ft
from typing import Optional


async def _async_call(fn):
    fn()

from ... import config
from ...config import (
    GEMINI_MODEL_OPTIONS,
    set_gemini_api_key,
    set_gemini_model,
)
from ...database.sqlite_db import SQLiteDB


def _card(title: str, icon: str, icon_color: str,
          content: ft.Control, border_color: str = "#E5E7EB") -> ft.Container:
    return ft.Container(
        content=ft.Column([
            ft.Text(title, size=13, weight=ft.FontWeight.W_600, color="#18181B"),
            ft.Container(height=1, bgcolor="#E5E7EB"),
            content,
        ], spacing=12),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, "#E5E7EB"),
        border_radius=10,
        padding=20,
        shadow=ft.BoxShadow(blur_radius=8, spread_radius=0,
                             color="#09000000", offset=ft.Offset(0, 2)),
    )


class SettingsView:
    def __init__(self, page: ft.Page):
        self.page = page
        self._snack_shown = False
        self._sqlite = SQLiteDB()

    def build(self) -> ft.Control:
        self._update_info: Optional[dict] = None
        return ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("設定", size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("管理 API 金鑰與模型偏好",
                            size=11, color=ft.colors.GREY_600),
                ], spacing=2),
            ]),
            ft.Divider(height=1, color="#E5E7EB"),
            ft.Column([
                self._build_profile_card(),
                self._build_api_key_card(),
                self._build_model_card(),
                self._build_update_card(),
                self._build_about_card(),
            ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True),
        ], expand=True, spacing=12)

    # ── 研究身份卡片 ─────────────────────────────────────────────────────────

    def _build_profile_card(self) -> ft.Control:
        profile = self._sqlite.get_user_profile()

        self._profile_field = ft.TextField(
            label="研究領域",
            hint_text="例如：Natural Language Processing, Computer Vision",
            value=profile.get("research_field", ""),
            prefix_icon=ft.icons.SCHOOL_OUTLINED,
            border_color="#0D9488",
            focused_border_color="#0F766E",
            expand=True,
        )
        self._keywords_field = ft.TextField(
            label="核心關鍵詞（逗號分隔）",
            hint_text="例如：transformer, BERT, fine-tuning, few-shot",
            value=profile.get("research_keywords", ""),
            prefix_icon=ft.icons.LABEL_OUTLINED,
            border_color="#0D9488",
            focused_border_color="#0F766E",
            expand=True,
        )
        self._style_dropdown = ft.Dropdown(
            label="寫作風格偏好",
            value=profile.get("writing_style", "balanced"),
            options=[
                ft.dropdown.Option("formal",   "正式學術（Formal Academic）"),
                ft.dropdown.Option("balanced", "平衡簡潔（Balanced & Clear）"),
                ft.dropdown.Option("concise",  "精簡扼要（Concise）"),
            ],
            border_color="#0D9488",
            focused_border_color="#0F766E",
            expand=True,
        )
        self._profile_status = ft.Text("", size=11)

        save_btn = ft.ElevatedButton(
            "儲存研究身份", icon=ft.icons.SAVE_OUTLINED,
            on_click=self._on_save_profile,
            style=ft.ButtonStyle(bgcolor="#0D9488", color=ft.colors.WHITE),
        )

        content = ft.Column([
            ft.Text(
                "設定你的研究背景，讓 AI 問答和文稿潤色更貼近你的領域與寫作習慣。",
                size=11, color=ft.colors.GREY_600,
            ),
            self._profile_field,
            self._keywords_field,
            self._style_dropdown,
            ft.Row([save_btn, self._profile_status],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=10)

        return _card("研究身份設定", ft.icons.PERSON_OUTLINED, "#0D9488",
                     content, "#CCFBF1")

    def _on_save_profile(self, e):
        self._sqlite.set_user_profile("research_field",
                                      (self._profile_field.value or "").strip())
        self._sqlite.set_user_profile("research_keywords",
                                      (self._keywords_field.value or "").strip())
        self._sqlite.set_user_profile("writing_style",
                                      self._style_dropdown.value or "balanced")
        self._profile_status.value = "✓ 已儲存"
        self._profile_status.color = ft.colors.GREEN_700
        try:
            self._profile_status.update()
        except Exception:
            pass
        self._show_snack("研究身份已儲存，即時套用至 AI 問答與文稿潤色")

    # ── API Key 卡片 ──────────────────────────────────────────────────────────

    def _build_api_key_card(self) -> ft.Control:
        current_key = config.GEMINI_API_KEY or ""
        masked = ("*" * 20 + current_key[-6:]) if len(current_key) > 6 else ("*" * len(current_key))

        self._key_field = ft.TextField(
            value=current_key,
            password=True,
            can_reveal_password=True,
            label="Gemini API Key",
            hint_text="AIzaSy...",
            prefix_icon=ft.icons.VPN_KEY_OUTLINED,
            border_color="#6D28D9",
            focused_border_color="#7C3AED",
            expand=True,
        )
        self._key_status = ft.Text("", size=11)

        validate_btn = ft.OutlinedButton(
            "驗證", icon=ft.icons.CHECK_CIRCLE_OUTLINE,
            on_click=self._on_validate_key,
            style=ft.ButtonStyle(color="#1D4ED8"),
        )
        save_key_btn = ft.ElevatedButton(
            "儲存", icon=ft.icons.SAVE_OUTLINED,
            on_click=self._on_save_key,
            style=ft.ButtonStyle(bgcolor="#7C3AED", color=ft.colors.WHITE),
        )

        content = ft.Column([
            ft.Text(
                "用於 AI 標籤生成、論文問答與分類功能。"
                "前往 https://makersuite.google.com/app/apikey 取得免費金鑰。",
                size=11, color=ft.colors.GREY_600,
            ),
            ft.Row([self._key_field, validate_btn, save_key_btn],
                   spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self._key_status,
        ], spacing=8)

        return _card("Gemini API Key", ft.icons.VPN_KEY_OUTLINED, "#7C3AED",
                     content, "#EDE9FE")

    def _on_validate_key(self, e):
        key = (self._key_field.value or "").strip()
        if not key:
            self._set_key_status("請先輸入 API Key", ft.colors.RED_700)
            return
        self._set_key_status("驗證中...", ft.colors.ORANGE_700)

        def run():
            try:
                from google import genai
                client = genai.Client(api_key=key)
                # 用最便宜的模型發一個最小請求
                client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents="hi",
                )
                self.page.run_task(
                    lambda: self._set_key_status("✓ API Key 有效！", ft.colors.GREEN_700)
                )
            except Exception as ex:
                self.page.run_task(
                    lambda: self._set_key_status(f"✗ 驗證失敗：{ex}", ft.colors.RED_700)
                )
        threading.Thread(target=run, daemon=True).start()

    def _on_save_key(self, e):
        key = (self._key_field.value or "").strip()
        if not key:
            self._set_key_status("API Key 不能為空", ft.colors.RED_700)
            return
        set_gemini_api_key(key)
        self._set_key_status("已儲存", ft.colors.GREEN_700)
        self._show_snack("API Key 已更新，即時生效")

    def _set_key_status(self, text: str, color):
        self._key_status.value = text
        self._key_status.color = color
        try:
            self._key_status.update()
        except Exception:
            pass

    # ── 模型選擇卡片 ─────────────────────────────────────────────────────────

    def _build_model_card(self) -> ft.Control:
        current = config.GEMINI_MODEL

        self._model_status = ft.Text("", size=11)

        options_col = ft.Column(spacing=6)
        self._model_radio_group = ft.RadioGroup(
            content=options_col,
            value=current,
            on_change=self._on_model_change,
        )

        for model_id, display_name, desc in GEMINI_MODEL_OPTIONS:
            is_default = model_id == "gemini-2.5-flash"
            options_col.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Radio(value=model_id, label=""),
                        ft.Column([
                            ft.Row([
                                ft.Text(display_name, size=12,
                                        weight=ft.FontWeight.W_600),
                                *([ ft.Container(
                                    content=ft.Text("推薦", size=9,
                                                    color=ft.colors.WHITE),
                                    bgcolor="#059669", border_radius=8,
                                    padding=ft.padding.symmetric(
                                        horizontal=6, vertical=1),
                                )] if is_default else []),
                            ], spacing=6),
                            ft.Text(desc, size=11, color=ft.colors.GREY_600),
                            ft.Text(model_id, size=10,
                                    color=ft.colors.GREY_400,
                                    font_family="monospace"),
                        ], spacing=2, expand=True),
                    ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor="#F8FAFC" if model_id != current else "#F5F3FF",
                    border=ft.border.all(
                        1, "#7C3AED" if model_id == current else "#E2E8F0"),
                    border_radius=8,
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                )
            )

        content = ft.Column([
            ft.Text(
                "選擇 Gemini 模型。模型切換即時生效，不需重啟程式。",
                size=11, color=ft.colors.GREY_600,
            ),
            self._model_radio_group,
            self._model_status,
        ], spacing=10)

        return _card("AI 模型選擇", ft.icons.PSYCHOLOGY_OUTLINED, "#1D4ED8",
                     content, "#DBEAFE")

    def _on_model_change(self, e):
        selected = e.control.value
        set_gemini_model(selected)
        # 更新卡片邊框高亮（重建選項）
        self._model_status.value = f"✓ 已切換至 {selected}"
        self._model_status.color = ft.colors.GREEN_700
        try:
            self._model_status.update()
        except Exception:
            pass
        self._show_snack(f"模型已切換至 {selected}，即時生效")

    # ── 版本更新卡片 ─────────────────────────────────────────────────────────

    def _build_update_card(self) -> ft.Control:
        from ...services.updater import get_local_version
        local_ver = get_local_version()

        self._update_status = ft.Text(
            "點擊「檢查更新」確認是否有新版本",
            size=11, color=ft.colors.GREY_600,
        )
        self._update_progress = ft.ProgressBar(
            visible=False, color="#0D9488", bgcolor="#CCFBF1", height=6,
        )
        self._download_btn = ft.ElevatedButton(
            "下載更新", icon=ft.icons.DOWNLOAD_OUTLINED,
            on_click=self._on_download_update,
            visible=False,
            style=ft.ButtonStyle(bgcolor="#0D9488", color=ft.colors.WHITE),
        )

        content = ft.Column([
            ft.Row([
                ft.Text(f"目前版本：", size=12, color=ft.colors.GREY_600),
                ft.Text(f"v{local_ver}", size=12, weight=ft.FontWeight.W_600),
            ], spacing=4),
            self._update_status,
            self._update_progress,
            ft.Row([
                ft.OutlinedButton(
                    "檢查更新", icon=ft.icons.REFRESH,
                    on_click=self._on_check_update,
                    style=ft.ButtonStyle(color="#0D9488"),
                ),
                self._download_btn,
            ], spacing=8),
        ], spacing=8)

        return _card("版本更新", ft.icons.SYSTEM_UPDATE_OUTLINED, "#0D9488",
                     content, "#CCFBF1")

    def _on_check_update(self, e):
        self._update_status.value = "檢查中…"
        self._update_status.color = ft.colors.ORANGE_700
        self._download_btn.visible = False
        try:
            self._update_status.update()
            self._download_btn.update()
        except Exception:
            pass

        def _run():
            from ...services.updater import check_for_update
            info = check_for_update()

            def _done():
                if info:
                    self._update_info = info
                    self._update_status.value = (
                        f"發現新版本 v{info['version']}！點擊「下載更新」即可升級。"
                    )
                    self._update_status.color = ft.colors.GREEN_700
                    self._download_btn.visible = True
                else:
                    self._update_status.value = "已是最新版本 ✓"
                    self._update_status.color = ft.colors.GREEN_700
                try:
                    self._update_status.update()
                    self._download_btn.update()
                except Exception:
                    pass

            self.page.run_task(_async_call, _done)

        threading.Thread(target=_run, daemon=True).start()

    def _on_download_update(self, e):
        if not self._update_info:
            return
        self._download_btn.disabled = True
        self._update_progress.visible = True
        self._update_progress.value = None   # indeterminate
        self._update_status.value = "下載中…"
        self._update_status.color = ft.colors.ORANGE_700
        try:
            self._download_btn.update()
            self._update_progress.update()
            self._update_status.update()
        except Exception:
            pass

        url = self._update_info["url"]

        def _run():
            from ...services.updater import download_update

            def _progress(pct: float):
                self._update_progress.value = pct
                try:
                    self._update_progress.update()
                except Exception:
                    pass

            ok = download_update(url, _progress)

            def _done():
                self._update_progress.visible = False
                if ok:
                    self._update_status.value = (
                        "✓ 下載完成！關閉並重新開啟程式即可套用更新。"
                    )
                    self._update_status.color = ft.colors.GREEN_700
                    self._download_btn.visible = False
                else:
                    self._update_status.value = "下載失敗，請稍後再試"
                    self._update_status.color = ft.colors.RED_700
                    self._download_btn.disabled = False
                try:
                    self._update_progress.update()
                    self._update_status.update()
                    self._download_btn.update()
                except Exception:
                    pass

            self.page.run_task(_async_call, _done)

        threading.Thread(target=_run, daemon=True).start()

    # ── 關於卡片 ─────────────────────────────────────────────────────────────

    def _build_about_card(self) -> ft.Control:
        content = ft.Column([
            ft.Row([
                ft.Icon(ft.icons.INFO_OUTLINE, color=ft.colors.GREY_500, size=14),
                ft.Text("SmartPaper Tagging", size=12,
                        weight=ft.FontWeight.W_600),
            ], spacing=6),
            ft.Text(
                "智能學術論文管理系統\n"
                "使用 ChromaDB 向量搜尋 + Google Gemini AI\n"
                "支援 Classic RAG 與 Function Calling 兩種問答模式",
                size=11, color=ft.colors.GREY_600,
            ),
        ], spacing=6)

        return _card("關於", ft.icons.INFO_OUTLINE, "#64748B",
                     content, "#E2E8F0")

    # ── 工具 ─────────────────────────────────────────────────────────────────

    def _show_snack(self, msg: str):
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(msg),
            bgcolor="#1E293B",
            duration=2500,
        )
        self.page.snack_bar.open = True
        try:
            self.page.update()
        except Exception:
            pass
