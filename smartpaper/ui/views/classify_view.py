"""
論文分類視圖
讓用戶輸入主題關鍵字，將論文分類到相應主題
"""

import threading
import flet as ft
from typing import Optional

from ...services.classifier import ClassificationService
from ...skills import ALL_SKILLS, get_skill
from ...config import GEMINI_API_KEY


class ClassifyView:
    """論文分類視圖"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.classifier: Optional[ClassificationService] = None
        self.results_container: Optional[ft.Column] = None
        self.topic_chips: list[ft.Chip] = []
        self.topics: list[str] = []

    def build(self) -> ft.Control:
        """建構視圖"""
        # 主題輸入區
        self.topic_input = ft.TextField(
            label="輸入主題關鍵字",
            hint_text="例如：Machine Learning, Healthcare, NLP",
            expand=True,
            on_submit=self.add_topic,
        )

        self.add_topic_btn = ft.IconButton(
            icon="add_circle",
            icon_color=ft.colors.BLUE,
            tooltip="新增主題",
            on_click=self.add_topic,
        )

        # 已新增的主題 chips
        self.topics_row = ft.Row(
            wrap=True,
            spacing=8,
        )

        # 專家角色選擇
        self.skill_dropdown = ft.Dropdown(
            label="專家角色",
            value="general",
            options=[
                ft.dropdown.Option(skill_id, skill.name)
                for skill_id, skill in ALL_SKILLS.items()
            ],
            width=200,
            tooltip="不同角色使用不同的分類標準與總結風格",
        )

        # 分類方法選擇
        self.method_dropdown = ft.Dropdown(
            label="分類方法",
            value="two_stage",
            options=[
                ft.dropdown.Option("semantic", "語意搜尋（快速）"),
                ft.dropdown.Option("two_stage", "兩階段 RAG（推薦）"),
                ft.dropdown.Option("llm", "純 LLM（最精確）"),
            ],
            width=250,
        )

        self.include_summary_checkbox = ft.Checkbox(
            label="生成各主題的 RAG 總結",
            value=True,
            disabled=not GEMINI_API_KEY,
        )

        # 方法說明
        self.method_hint = ft.Text(
            "兩階段 RAG：先搜尋標題找候選論文，再用 LLM 分析摘要確認分類",
            size=11,
            color=ft.colors.GREY_600,
            italic=True,
        )

        # 分類按鈕
        self.classify_btn = ft.ElevatedButton(
            text="開始分類",
            icon="category",
            on_click=self.run_classification,
            disabled=True,
        )

        # 建議主題按鈕
        self.suggest_btn = ft.OutlinedButton(
            text="自動建議主題",
            icon="auto_awesome",
            on_click=self.suggest_topics,
        )

        # 進度指示器（Ring 用於不確定狀態；Bar 顯示精確進度）
        self.progress_ring = ft.ProgressRing(visible=False, width=20, height=20)
        self.progress_bar = ft.ProgressBar(
            value=0,
            visible=False,
            color=ft.colors.BLUE_600,
            bgcolor=ft.colors.BLUE_100,
            height=6,
            border_radius=3,
        )
        self.progress_text = ft.Text("", size=11, color=ft.colors.GREY_600, visible=False)
        self.status_text = ft.Text("", size=12, color=ft.colors.GREY_600)

        # 視圖切換（主題視圖 / 論文視圖）
        self._current_report = None
        self._current_method = "two_stage"
        self._sort_by_citation = False  # False = by confidence, True = by citation count

        self.view_topic_btn = ft.ElevatedButton(
            text="主題視圖",
            icon="folder_open",
            on_click=self._switch_to_topic_view,
            visible=False,
            style=ft.ButtonStyle(bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE),
        )
        self.view_paper_btn = ft.OutlinedButton(
            text="論文視圖",
            icon="list_alt",
            on_click=self._switch_to_paper_view,
            visible=False,
        )
        self.sort_toggle_btn = ft.OutlinedButton(
            text="排序：信心度",
            icon="sort",
            on_click=self._toggle_sort,
            visible=False,
            tooltip="切換按信心度/引用數排序",
        )
        self.sync_tags_btn = ft.ElevatedButton(
            text="同步分類為標籤",
            icon="sync",
            on_click=self.sync_tags_to_db,
            visible=False,
            style=ft.ButtonStyle(bgcolor=ft.colors.GREEN_600, color=ft.colors.WHITE),
            tooltip="將分類主題新增為論文的標籤",
        )

        # 結果容器
        self.results_container = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # ── 步驟進度指示器 ────────────────────────────────────────
        self._step_indicator = self._build_step_indicator(0)

        # ── 結果視圖切換（大型 Segment）────────────────────────
        self._view_seg = ft.Row(
            [self.view_topic_btn, self.view_paper_btn, self.sort_toggle_btn, self.sync_tags_btn],
            spacing=8, wrap=True, visible=False,
        )

        # 重新設定按鈕（分類完成後顯示，讓使用者能折疊展開設定）
        self._reconfig_btn = ft.TextButton(
            text="重新設定",
            icon="tune",
            on_click=self._toggle_config_panel,
            visible=False,
            style=ft.ButtonStyle(color=ft.colors.BLUE_600),
        )

        # ── Step 1 & 2 容器（分類後可收合）──────────────────────
        self._step1_container = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Step 1", size=10, weight=ft.FontWeight.W_600,
                            color="#4F46E5"),
                    ft.Text("輸入分類主題", size=13,
                            weight=ft.FontWeight.W_600),
                ], spacing=8),
                ft.Row([self.topic_input, self.add_topic_btn],
                       alignment=ft.MainAxisAlignment.START),
                ft.Column([
                    ft.Text("已選主題：", size=11, color=ft.colors.GREY_600),
                    self.topics_row,
                ], spacing=4),
                ft.Row([
                    self.suggest_btn,
                    ft.Text("或讓 AI 根據你的文獻庫自動建議主題",
                            size=11, color=ft.colors.GREY_500),
                ], spacing=8),
            ], spacing=10),
            padding=16,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=10,
            bgcolor="#FFFFFF",
        )

        self._step2_container = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Step 2", size=10, weight=ft.FontWeight.W_600,
                            color="#4F46E5"),
                    ft.Text("選擇分類設定", size=13,
                            weight=ft.FontWeight.W_600),
                ], spacing=8),
                ft.Row([
                    self.skill_dropdown,
                    self.method_dropdown,
                    self.include_summary_checkbox,
                ], spacing=16, wrap=True),
                self.method_hint,
            ], spacing=8),
            padding=16,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=10,
            bgcolor="#FFFFFF",
        )

        # 組裝介面
        return ft.Column(
            [
                ft.Row([
                    ft.Column([
                        ft.Text("論文分類", size=22, weight=ft.FontWeight.BOLD),
                        ft.Text("輸入主題關鍵字，AI 將論文語意分類",
                                size=11, color=ft.colors.GREY_600),
                    ], spacing=2, expand=True),
                ]),
                ft.Divider(height=1, color="#E5E7EB"),

                # 步驟進度
                self._step_indicator,

                self._step1_container,
                self._step2_container,

                # ── Step 3: 執行 ──────────────────────────────────
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("Step 3", size=10, weight=ft.FontWeight.W_600,
                                    color="#4F46E5"),
                            ft.Text("開始分類", size=13,
                                    weight=ft.FontWeight.W_600),
                            self._reconfig_btn,
                        ], spacing=8),
                        ft.Row([
                            self.classify_btn,
                            self.progress_ring,
                            self.status_text,
                        ], spacing=10,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        self.progress_bar,
                        self.progress_text,
                        # 分類完成後：視圖切換
                        self._view_seg,
                    ], spacing=8),
                    padding=16,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=10,
                    bgcolor="#FFFFFF",
                ),

                ft.Divider(height=1, color="#E5E7EB"),

                # 結果區（expand=True 填滿剩餘空間）
                ft.Container(
                    content=self.results_container,
                    expand=True,
                    border=ft.border.all(1, "#E5E7EB"),
                    border_radius=10,
                    padding=16,
                    bgcolor="#FFFFFF",
                ),
            ],
            spacing=12,
            expand=True,
        )

    def _build_step_indicator(self, active: int) -> ft.Row:
        """0=輸入中, 1=設定中, 2=執行中, 3=完成"""
        steps = ["輸入主題", "分類設定", "執行分類", "查看結果"]
        items = []
        for i, label in enumerate(steps):
            if i < active:
                # 完成
                dot_color, dot_bg, text_color = "#FFFFFF", "#059669", "#059669"
                dot_content = ft.Icon("check", size=10, color="#FFFFFF")
            elif i == active:
                # 當前
                dot_color, dot_bg, text_color = "#FFFFFF", "#4F46E5", "#4F46E5"
                dot_content = ft.Text(str(i + 1), size=10, color="#FFFFFF",
                                      weight=ft.FontWeight.BOLD)
            else:
                # 未來
                dot_color, dot_bg, text_color = "#9CA3AF", "#F3F4F6", "#9CA3AF"
                dot_content = ft.Text(str(i + 1), size=10, color="#9CA3AF")

            items.append(ft.Row([
                ft.Container(
                    content=dot_content,
                    width=22, height=22, border_radius=11,
                    bgcolor=dot_bg,
                    alignment=ft.alignment.center,
                ),
                ft.Text(label, size=11, color=text_color,
                        weight=ft.FontWeight.W_500 if i <= active else ft.FontWeight.NORMAL),
            ], spacing=6, tight=True))

            if i < len(steps) - 1:
                items.append(ft.Container(
                    width=24, height=2,
                    bgcolor="#4F46E5" if i < active else "#E5E7EB",
                ))

        return ft.Row(items, spacing=4,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def add_topic(self, e):
        """新增主題"""
        topic = self.topic_input.value.strip()
        if not topic:
            return

        # 支援逗號分隔的多個主題
        new_topics = [t.strip() for t in topic.split(",") if t.strip()]

        for t in new_topics:
            if t not in self.topics:
                self.topics.append(t)
                chip = ft.Chip(
                    label=ft.Text(t),
                    on_delete=lambda e, topic=t: self.remove_topic(topic),
                )
                self.topic_chips.append(chip)
                self.topics_row.controls.append(chip)

        self.topic_input.value = ""
        self.classify_btn.disabled = len(self.topics) == 0
        if self.topics and hasattr(self, '_step_indicator'):
            self._step_indicator.controls = self._build_step_indicator(1).controls
        self.page.update()

    def remove_topic(self, topic: str):
        """移除主題"""
        if topic in self.topics:
            self.topics.remove(topic)
            # 移除對應的 chip
            self.topics_row.controls = [
                c for c in self.topics_row.controls
                if isinstance(c, ft.Chip) and c.label.value != topic
            ]
            self.classify_btn.disabled = len(self.topics) == 0
            self.page.update()

    def suggest_topics(self, e):
        """自動建議主題"""
        self.progress_ring.visible = True
        self.status_text.value = "分析標籤中..."
        self.page.update()

        try:
            skill = get_skill(self.skill_dropdown.value or "general")
            self.classifier = ClassificationService(skill=skill)

            suggested = self.classifier.suggest_topics(num_topics=5)

            if suggested:
                # 清空現有主題
                self.topics.clear()
                self.topics_row.controls.clear()

                # 加入建議的主題
                for topic in suggested:
                    self.topics.append(topic)
                    chip = ft.Chip(
                        label=ft.Text(topic),
                        on_delete=lambda e, t=topic: self.remove_topic(t),
                    )
                    self.topics_row.controls.append(chip)

                self.classify_btn.disabled = False
                self.status_text.value = f"已建議 {len(suggested)} 個主題"
            else:
                self.status_text.value = "無法建議主題（資料庫中沒有足夠的標籤）"

        except Exception as ex:
            self.status_text.value = f"錯誤：{str(ex)}"

        finally:
            self.progress_ring.visible = False
            self.page.update()

    def _toggle_config_panel(self, e):
        """分類完成後切換 Step 1 & 2 的顯示/隱藏"""
        is_visible = self._step1_container.visible
        self._step1_container.visible = not is_visible
        self._step2_container.visible = not is_visible
        self._reconfig_btn.text = "收合設定" if not is_visible else "重新設定"
        self.page.update()

    def run_classification(self, e):
        """執行分類（背景執行緒，UI 保持可互動）"""
        if not self.topics:
            return

        method = self.method_dropdown.value

        if method in ("two_stage", "llm") and not GEMINI_API_KEY:
            self.status_text.value = "錯誤：此方法需要設定 Gemini API Key"
            self.page.update()
            return

        # ── 初始化 UI 狀態 ─────────────────────────────────────────
        self.progress_ring.visible = True
        self.progress_bar.value = 0
        self.progress_bar.visible = True
        self.progress_text.value = "準備中..."
        self.progress_text.visible = True
        self.classify_btn.disabled = True
        self.status_text.value = "分類中，請稍候..."
        self.results_container.controls.clear()
        self.view_topic_btn.visible = False
        self.view_paper_btn.visible = False
        self.sort_toggle_btn.visible = False
        self.sync_tags_btn.visible = False
        self._view_seg.visible = False
        self._reconfig_btn.visible = False
        self._current_report = None
        self._sort_by_citation = False
        # 收合 Step 1 & 2，讓結果區有更多空間
        self._step1_container.visible = False
        self._step2_container.visible = False
        # 步驟指示器：進入 Step 3
        self._step_indicator.controls = self._build_step_indicator(2).controls
        self.page.update()

        topics_snapshot = list(self.topics)
        include_summary = self.include_summary_checkbox.value and bool(GEMINI_API_KEY)
        skill_id = self.skill_dropdown.value or "general"

        def _run():
            try:
                skill = get_skill(skill_id)
                self.classifier = ClassificationService(skill=skill)

                def progress_callback(topic, current, total):
                    self.status_text.value = f"分類中 [{current}/{total}] {topic}..."
                    self.progress_bar.value = current / max(total, 1)
                    self.progress_text.value = (
                        f"完成 {current}/{total} 個主題 · 正在處理：{topic[:28]}"
                    )
                    self.page.update()

                report = self.classifier.get_classification_report(
                    topics=topics_snapshot,
                    method=method,
                    include_summary=include_summary,
                    progress_callback=progress_callback if method == "two_stage" else None,
                )

                self._current_report = report
                self._current_method = method
                self.display_results(report, method)
                self.status_text.value = "✅ 分類完成"
                self.progress_bar.value = 1.0
                self.view_topic_btn.visible = True
                self.view_paper_btn.visible = True
                self.sort_toggle_btn.visible = True
                self.sync_tags_btn.visible = True
                self._view_seg.visible = True
                self._reconfig_btn.visible = True
                self._reconfig_btn.text = "重新設定"
                # 步驟指示器：完成
                self._step_indicator.controls = self._build_step_indicator(3).controls

            except Exception as ex:
                self.status_text.value = f"❌ 錯誤：{str(ex)}"
                self.results_container.controls.append(
                    ft.Text(f"發生錯誤：{str(ex)}", color=ft.colors.RED)
                )
            finally:
                self.progress_ring.visible = False
                self.progress_bar.visible = False
                self.progress_text.visible = False
                self.classify_btn.disabled = False
                self.page.update()

        threading.Thread(target=_run, daemon=True).start()

    def _switch_to_topic_view(self, e):
        """切換到主題視圖"""
        if not self._current_report:
            return
        self.view_topic_btn.style = ft.ButtonStyle(bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE)
        self.view_paper_btn.style = None
        self.results_container.controls.clear()
        self.display_results(self._current_report, self._current_method)
        self.page.update()

    def _switch_to_paper_view(self, e):
        """切換到論文視圖（多標籤）"""
        if not self._current_report:
            return
        self.view_paper_btn.style = ft.ButtonStyle(bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE)
        self.view_topic_btn.style = None
        self.results_container.controls.clear()
        self.display_paper_centric(self._current_report)
        self.page.update()

    def _toggle_sort(self, e):
        """切換排序方式（信心度 ↔ 引用數）"""
        if not self._current_report:
            return
        self._sort_by_citation = not self._sort_by_citation
        self.sort_toggle_btn.text = "排序：引用數" if self._sort_by_citation else "排序：信心度"
        self.results_container.controls.clear()
        self.display_results(self._current_report, self._current_method)
        self.page.update()

    def sync_tags_to_db(self, e):
        """將分類主題同步新增為論文標籤"""
        if not self._current_report:
            return

        from ...database.sqlite_db import SQLiteDB
        db = SQLiteDB()
        updated_count = 0

        for topic, data in self._current_report.get("topics", {}).items():
            for paper_data in data.get("papers", []):
                paper = db.get_by_id(paper_data["id"])
                if paper and topic not in (paper.tags or []):
                    paper.tags = list(paper.tags or []) + [topic]
                    db.update(paper)
                    updated_count += 1

        self.status_text.value = f"已同步：為 {updated_count} 篇論文新增分類標籤"
        self.sync_tags_btn.visible = False
        self.page.update()

    def display_paper_centric(self, report: dict):
        """論文視圖：每篇論文顯示所有符合的主題及百分比"""
        paper_list = report.get("paper_multi_label", [])

        if not paper_list:
            self.results_container.controls.append(
                ft.Text("沒有分類結果", color=ft.colors.GREY_500)
            )
            return

        # 統計卡片
        stats = report["statistics"]
        stats_row = ft.Row(
            [
                self._create_stat_card("論文總數", stats["total_papers"], ft.colors.BLUE),
                self._create_stat_card("多主題論文", sum(1 for p in paper_list if len(p["classifications"]) > 1), ft.colors.PURPLE),
                self._create_stat_card("未分類", stats["unclassified_papers"], ft.colors.ORANGE),
            ],
            spacing=15,
        )
        self.results_container.controls.append(stats_row)
        self.results_container.controls.append(ft.Divider(height=16))

        # 主題顏色映射
        all_topics = list({c["topic"] for p in paper_list for c in p["classifications"]})
        topic_colors = [
            ft.colors.BLUE_600, ft.colors.GREEN_600, ft.colors.PURPLE_600,
            ft.colors.ORANGE_600, ft.colors.TEAL_600, ft.colors.RED_600,
            ft.colors.INDIGO_600, ft.colors.PINK_600,
        ]
        topic_color_map = {t: topic_colors[i % len(topic_colors)] for i, t in enumerate(all_topics)}

        # 每篇論文一張卡片
        for paper_data in paper_list:
            title = paper_data["title"]
            classifications = paper_data["classifications"]
            tags = paper_data.get("tags") or []

            # 建立每個主題的分數列
            score_rows = []
            for cls in classifications:
                score = cls["score"]
                color = topic_color_map.get(cls["topic"], ft.colors.BLUE_600)

                score_rows.append(
                    ft.Row(
                        [
                            # 主題名稱（固定寬度）
                            ft.Container(
                                content=ft.Text(
                                    cls["topic"],
                                    size=11,
                                    color=ft.colors.GREY_700,
                                    no_wrap=True,
                                ),
                                width=150,
                            ),
                            # 進度條
                            ft.Container(
                                content=ft.ProgressBar(
                                    value=score,
                                    bgcolor=ft.colors.GREY_200,
                                    color=color,
                                    height=10,
                                    border_radius=5,
                                ),
                                expand=True,
                            ),
                            # 百分比
                            ft.Container(
                                content=ft.Text(
                                    f"{score:.0%}",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=color,
                                ),
                                width=45,
                                alignment=ft.alignment.center_right,
                            ),
                        ],
                        spacing=8,
                    )
                )

            # 標籤列
            tag_chips = ft.Row(
                [
                    ft.Container(
                        content=ft.Text(tag, size=9, color=ft.colors.GREY_600),
                        bgcolor=ft.colors.GREY_100,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        border_radius=8,
                    )
                    for tag in tags[:5]
                ],
                spacing=4,
                wrap=True,
            ) if tags else ft.Container()

            card = ft.Container(
                content=ft.Column(
                    [
                        # 論文標題
                        ft.Text(
                            title[:80] + "..." if len(title) > 80 else title,
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.colors.GREY_900,
                        ),
                        tag_chips,
                        ft.Container(height=4),
                        *score_rows,
                    ],
                    spacing=4,
                ),
                padding=ft.padding.all(12),
                border=ft.border.all(1, ft.colors.GREY_200),
                border_radius=8,
                bgcolor=ft.colors.WHITE,
                margin=ft.margin.only(bottom=8),
            )
            self.results_container.controls.append(card)

    def display_results(self, report: dict, method: str = "semantic"):
        """顯示分類結果"""
        # 統計卡片
        stats = report["statistics"]
        stats_row = ft.Row(
            [
                self._create_stat_card("論文總數", stats["total_papers"], ft.colors.BLUE),
                self._create_stat_card("已分類", stats["classified_papers"], ft.colors.GREEN),
                self._create_stat_card("未分類", stats["unclassified_papers"], ft.colors.ORANGE),
            ],
            spacing=15,
        )
        self.results_container.controls.append(stats_row)
        self.results_container.controls.append(ft.Divider(height=20))

        # 各主題結果
        for topic, data in report["topics"].items():
            # 主題標題
            topic_header = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon("folder", color=ft.colors.BLUE),
                        ft.Text(
                            f"{topic}",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Container(
                            content=ft.Text(
                                f"{data['count']} 篇",
                                size=12,
                                color=ft.colors.WHITE,
                            ),
                            bgcolor=ft.colors.BLUE,
                            padding=ft.padding.symmetric(horizontal=10, vertical=4),
                            border_radius=12,
                        ),
                    ],
                    spacing=10,
                ),
                padding=ft.padding.only(top=10, bottom=5),
            )
            self.results_container.controls.append(topic_header)

            # 論文列表
            if data["papers"]:
                # 排序
                papers_sorted = sorted(
                    data["papers"],
                    key=lambda p: (p.get("citation_count") or -1) if self._sort_by_citation else p["score"],
                    reverse=True,
                )

                columns = [
                    ft.DataColumn(ft.Text("信心度" if method == "two_stage" else "相似度", size=12)),
                    ft.DataColumn(ft.Text("論文標題", size=12)),
                    ft.DataColumn(ft.Text("期刊/引用", size=12)),
                    ft.DataColumn(ft.Text("分類理由" if method == "two_stage" else "標籤", size=12)),
                ]

                def _make_row(p):
                    citation_count = p.get("citation_count")
                    venue = p.get("venue") or ""
                    cite_text = f"引用 {citation_count}" if citation_count is not None else ""
                    meta_parts = [venue[:20] if venue else "", cite_text]
                    meta_str = " | ".join(x for x in meta_parts if x)

                    if method == "two_stage":
                        extra_cell = ft.DataCell(ft.Text(p.get("reason", "-")[:25], size=11, color=ft.colors.GREY_600))
                    else:
                        extra_cell = ft.DataCell(ft.Text(", ".join((p.get("tags") or [])[:2]) or "-", size=11, color=ft.colors.GREY_600))

                    return ft.DataRow(cells=[
                        ft.DataCell(ft.Text(f"{p['score']:.1%}", size=11)),
                        ft.DataCell(ft.Text(p["title"][:45] + "..." if len(p["title"]) > 45 else p["title"], size=11)),
                        ft.DataCell(ft.Text(meta_str, size=10, color=ft.colors.TEAL_700)),
                        extra_cell,
                    ])

                rows = [_make_row(p) for p in papers_sorted[:10]]

                papers_table = ft.DataTable(
                    columns=columns,
                    rows=rows,
                    border=ft.border.all(1, ft.colors.GREY_300),
                    border_radius=8,
                    heading_row_height=35,
                    data_row_min_height=35,
                )
                self.results_container.controls.append(papers_table)

                # 顯示論文與主題的關聯摘要（兩階段分類特有）
                if method == "two_stage":
                    papers_with_summary = [
                        p for p in papers_sorted[:10]
                        if p.get("topic_summary")
                    ]
                    if papers_with_summary:
                        # 建立可展開的詳細摘要區
                        detail_items = []
                        for p in papers_with_summary:
                            detail_items.append(
                                ft.ExpansionTile(
                                    title=ft.Text(
                                        p["title"][:50] + "..." if len(p["title"]) > 50 else p["title"],
                                        size=12,
                                    ),
                                    subtitle=ft.Text(
                                        f"信心度: {p['score']:.1%}",
                                        size=10,
                                        color=ft.colors.GREY_600,
                                    ),
                                    controls=[
                                        ft.Container(
                                            content=ft.Text(
                                                p.get("topic_summary", ""),
                                                size=11,
                                                color=ft.colors.GREY_700,
                                            ),
                                            padding=ft.padding.all(10),
                                            bgcolor=ft.colors.GREY_100,
                                            border_radius=5,
                                        )
                                    ],
                                    initially_expanded=False,
                                )
                            )

                        details_panel = ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon("description", size=14, color=ft.colors.TEAL),
                                    ft.Text(
                                        "論文與主題關聯摘要（點擊展開）",
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.colors.TEAL,
                                    ),
                                ]),
                                ft.Column(detail_items, spacing=0),
                            ]),
                            padding=ft.padding.only(top=10, bottom=10),
                        )
                        self.results_container.controls.append(details_panel)

            # 主題總結
            if "summary" in data and data["summary"]:
                summary_card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon("auto_awesome", size=16, color=ft.colors.PURPLE),
                            ft.Text("AI 總結", size=12, weight=ft.FontWeight.BOLD),
                        ]),
                        ft.Text(data["summary"], size=12, color=ft.colors.GREY_700),
                    ]),
                    bgcolor=ft.colors.PURPLE_50,
                    padding=15,
                    border_radius=8,
                    margin=ft.margin.only(top=10, bottom=15),
                )
                self.results_container.controls.append(summary_card)

            # 研究缺口分析按鈕（每個主題一個）
            gap_result_text = ft.Text("", size=12, color=ft.colors.GREY_700, selectable=True)
            gap_card = ft.Container(
                content=ft.Column([gap_result_text], spacing=4),
                bgcolor=ft.colors.ORANGE_50,
                padding=12,
                border_radius=8,
                visible=False,
            )

            def _on_gap_click(e, _topic=topic, _gap_card=gap_card, _gap_text=gap_result_text):
                _gap_text.value = "分析中，請稍候..."
                _gap_card.visible = True
                self.page.update()

                raw = (self._current_report or {}).get("_raw_classifications", {})
                papers = raw.get(_topic, [])
                result = self.classifier.analyze_research_gaps(_topic, papers)
                _gap_text.value = result
                self.page.update()

            gap_btn = ft.OutlinedButton(
                text="分析研究缺口",
                icon="search",
                on_click=_on_gap_click,
                style=ft.ButtonStyle(color=ft.colors.ORANGE_700),
            )
            self.results_container.controls.append(
                ft.Row([gap_btn], alignment=ft.MainAxisAlignment.END)
            )
            self.results_container.controls.append(gap_card)
            self.results_container.controls.append(ft.Divider())

        self.page.update()

    def _create_stat_card(self, label: str, value: int, color) -> ft.Container:
        """建立統計卡片"""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(str(value), size=28, weight=ft.FontWeight.BOLD, color=color),
                    ft.Text(label, size=12, color=ft.colors.GREY_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=15,
            border=ft.border.all(1, ft.colors.GREY_300),
            border_radius=8,
            width=120,
        )
