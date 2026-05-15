"""
SmartPaper-Tagging 首次設定精靈
執行方式：python smartpaper_setup.py
"""

import os
import sys
from pathlib import Path

_ENV_PATH = Path(__file__).parent / ".env"


def _read_existing_env() -> dict:
    vals = {"GEMINI_API_KEY": "", "CROSSREF_EMAIL": ""}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() in vals:
                    vals[k.strip()] = v.strip()
    return vals


def _save_env(api_key: str, email: str):
    lines = [
        f"GEMINI_API_KEY={api_key}",
        f"CROSSREF_EMAIL={email}",
    ]
    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _launch_flet_wizard():
    import flet as ft

    existing = _read_existing_env()

    def main(page: ft.Page):
        page.title = "SmartPaper 設定精靈"
        page.window.width = 520
        page.window.height = 480
        page.window.min_width = 480
        page.window.min_height = 400
        page.padding = 0
        page.bgcolor = "#F5F5F7"
        page.theme_mode = ft.ThemeMode.LIGHT

        saved = ft.Ref[ft.Text]()
        api_field = ft.TextField(
            label="Gemini API Key",
            value=existing["GEMINI_API_KEY"],
            password=True,
            can_reveal_password=True,
            border_color="#6366F1",
            focused_border_color="#6366F1",
            expand=True,
            hint_text="AIza...",
        )
        email_field = ft.TextField(
            label="Crossref Email（選填，可加快 API 速率）",
            value=existing["CROSSREF_EMAIL"],
            border_color="#6366F1",
            focused_border_color="#6366F1",
            expand=True,
            hint_text="your@email.com",
        )
        status = ft.Text("", ref=saved, color="#22C55E", size=13)

        def on_save(e):
            key = api_field.value.strip()
            if not key:
                status.value = "請輸入 Gemini API Key"
                status.color = "#EF4444"
                page.update()
                return
            _save_env(key, email_field.value.strip())
            status.value = "已儲存！可以關閉此視窗並執行 launch.bat / launch.sh 啟動應用程式。"
            status.color = "#22C55E"
            page.update()

        def on_launch(e):
            key = api_field.value.strip()
            if not key:
                status.value = "請先輸入 Gemini API Key"
                status.color = "#EF4444"
                page.update()
                return
            _save_env(key, email_field.value.strip())
            page.window.close()
            os.execv(sys.executable, [sys.executable, "main.py", "ui"])

        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Row([
                            ft.Container(
                                ft.Icon(ft.icons.AUTO_AWESOME_ROUNDED, color="white", size=20),
                                width=44,
                                height=44,
                                border_radius=14,
                                bgcolor="#6366F1",
                                alignment=ft.alignment.center,
                            ),
                            ft.Column([
                                ft.Text("SmartPaper", size=18, weight=ft.FontWeight.BOLD,
                                        color="#1E1E2E"),
                                ft.Text("首次設定精靈", size=12, color="#71717A"),
                            ], spacing=0, tight=True),
                        ], spacing=12),
                        ft.Divider(color="#E4E4E7", height=24),
                        ft.Text(
                            "請輸入您的 Google Gemini API Key。取得方式：",
                            size=13, color="#3F3F46",
                        ),
                        ft.Text(
                            "https://aistudio.google.com/app/apikey",
                            size=12, color="#6366F1", selectable=True,
                        ),
                        ft.Container(height=4),
                        api_field,
                        ft.Container(height=4),
                        email_field,
                        ft.Container(height=8),
                        status,
                        ft.Container(height=4),
                        ft.Row([
                            ft.ElevatedButton(
                                "儲存設定",
                                icon=ft.icons.SAVE_OUTLINED,
                                on_click=on_save,
                                style=ft.ButtonStyle(
                                    bgcolor={"": "#6366F1"},
                                    color={"": "white"},
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                            ),
                            ft.ElevatedButton(
                                "儲存並啟動",
                                icon=ft.icons.ROCKET_LAUNCH_OUTLINED,
                                on_click=on_launch,
                                style=ft.ButtonStyle(
                                    bgcolor={"": "#22C55E"},
                                    color={"": "white"},
                                    shape=ft.RoundedRectangleBorder(radius=10),
                                ),
                            ),
                        ], spacing=12),
                    ],
                    spacing=10,
                ),
                padding=ft.padding.all(32),
                expand=True,
            )
        )

    ft.app(target=main)


def _cli_wizard():
    """Fallback when Flet is not available."""
    existing = _read_existing_env()
    print("=" * 50)
    print("  SmartPaper-Tagging 設定精靈")
    print("=" * 50)
    print()

    default_key = existing["GEMINI_API_KEY"]
    hint = f" [{default_key[:8]}...]" if default_key else ""
    api_key = input(f"請輸入 Gemini API Key{hint}: ").strip() or default_key

    default_email = existing["CROSSREF_EMAIL"]
    hint_e = f" [{default_email}]" if default_email else ""
    email = input(f"請輸入 Crossref Email（選填）{hint_e}: ").strip() or default_email

    if not api_key:
        print("未輸入 API Key，設定取消。")
        sys.exit(1)

    _save_env(api_key, email)
    print()
    print("✓ 已儲存 .env 設定檔！")
    print("  現在可以執行: python main.py ui")


if __name__ == "__main__":
    try:
        import flet  # noqa: F401
        _launch_flet_wizard()
    except ImportError:
        _cli_wizard()
