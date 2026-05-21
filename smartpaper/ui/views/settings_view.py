"""
設定頁面：管理 Gemini API Key 與模型選擇
"""

import threading
import flet as ft
from typing import Optional

from ... import config
from ...config import (
    GEMINI_MODEL_OPTIONS,
    set_gemini_api_key,
    set_gemini_model,
)


def _card(title: str, icon: str, icon_color: str,
          content: ft.Control, border_color: str = "#E2E8F0") -> ft.Container:
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(icon, color=icon_color, size=16),
                ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=icon_color),
            ], spacing=8),
            ft.Divider(height=6, color=border_color),
            content,
        ], spacing=10),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, border_color),
        border_radius=12,
        padding=18,
    )


class SettingsView:
    def __init__(self, page: ft.Page):
        self.page = page
        self._snack_shown = False

    def build(self) -> ft.Control:
        return ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text("設定", size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("管理 API 金鑰與模型偏好",
                            size=11, color=ft.colors.GREY_600),
                ], spacing=2),
            ]),
            ft.Divider(height=1, color="#E2E8F0"),
            ft.Column([
                self._build_api_key_card(),
                self._build_model_card(),
                self._build_about_card(),
            ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True),
        ], expand=True, spacing=12)

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
