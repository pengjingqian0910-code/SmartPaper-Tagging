"""
概念萃取服務
用 LLM 從摘要中抽出方法、資料集、評測指標、研究任務，
建立倒排索引以支援精準的概念搜尋
"""

import json
from typing import Optional, Callable, TYPE_CHECKING
from google import genai

from ..database.sqlite_db import SQLiteDB
from ..config import GEMINI_API_KEY, GEMINI_MODEL
from ..models import Paper

if TYPE_CHECKING:
    from ..skills import SkillConfig

CONCEPT_TYPES = ["method", "dataset", "metric", "task"]

TYPE_LABELS = {
    "method": "方法/模型",
    "dataset": "資料集",
    "metric": "評測指標",
    "task": "研究任務",
}


class ConceptExtractor:
    """概念萃取服務"""

    def __init__(
        self,
        sqlite_db: Optional[SQLiteDB] = None,
        api_key: Optional[str] = None,
        skill: Optional["SkillConfig"] = None,
    ):
        self.db = sqlite_db or SQLiteDB()
        self.skill = skill

        self.api_key = api_key or GEMINI_API_KEY
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    # ── 單篇萃取 ──────────────────────────────────────────────────────

    def extract_for_paper(self, paper: Paper) -> dict:
        """
        用 LLM 從摘要中萃取概念

        Returns:
            {"method": [...], "dataset": [...], "metric": [...], "task": [...]}
        """
        if not paper.abstract or not self.client:
            return {t: [] for t in CONCEPT_TYPES}

        role_prefix = self.skill.system_prompt + "\n\n" if self.skill else ""

        prompt = f"""{role_prefix}請從以下學術論文中萃取關鍵概念。

論文標題：{paper.title}
論文摘要：{paper.abstract[:1000]}

請萃取以下四類概念：
1. **方法/模型（method）**：論文提出或使用的具體技術、架構、演算法（例：BERT、U-Net、Random Forest、attention mechanism）
2. **資料集（dataset）**：使用的訓練或測試資料集（例：ImageNet、MIMIC-III、MS COCO、SQuAD）
3. **評測指標（metric）**：評估性能的具體指標（例：F1-score、BLEU、mAP、AUC、accuracy）
4. **研究任務（task）**：論文解決的具體任務（例：image segmentation、named entity recognition、drug discovery）

注意：
- 只列出明確出現在論文中的概念，不要推測
- 每個概念用英文，保持原始名稱（如 BERT、ResNet-50）
- 每類最多 6 個，優先列最核心的

回傳 JSON：
{{
  "method": ["BERT", "attention mechanism"],
  "dataset": ["ImageNet", "CIFAR-10"],
  "metric": ["accuracy", "F1-score"],
  "task": ["image classification"]
}}

只回傳 JSON，不要有其他文字。"""

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt
            )
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())
            # 確保只保留合法的 key，值為 list[str]
            result = {}
            for t in CONCEPT_TYPES:
                items = data.get(t, [])
                result[t] = [str(x).strip() for x in items if x and str(x).strip()][:6]
            return result

        except Exception as e:
            print(f"概念萃取失敗（{paper.title[:40]}）: {e}")
            return {t: [] for t in CONCEPT_TYPES}

    # ── 批次建立索引 ──────────────────────────────────────────────────

    def build_index(
        self,
        papers: Optional[list[Paper]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        skip_existing: bool = True,
    ) -> dict:
        """
        對所有（或指定的）論文萃取概念並寫入 DB

        Returns:
            {"processed": N, "skipped": M, "total_concepts": K}
        """
        if papers is None:
            papers = self.db.get_all(limit=5000)

        processed = 0
        skipped = 0
        total_concepts = 0
        total = len(papers)

        for idx, paper in enumerate(papers):
            if progress_callback:
                progress_callback(paper.title, idx + 1, total)

            if not paper.abstract:
                skipped += 1
                continue

            if skip_existing and self.db.has_concepts(paper.id):
                skipped += 1
                continue

            concepts = self.extract_for_paper(paper)
            self.db.replace_paper_concepts(paper.id, concepts)
            total_concepts += sum(len(v) for v in concepts.values())
            processed += 1

        return {"processed": processed, "skipped": skipped, "total_concepts": total_concepts}

    # ── 查詢 ──────────────────────────────────────────────────────────

    def search_by_concept(self, query: str) -> list[Paper]:
        """倒排索引查詢：找出使用某概念的論文"""
        return self.db.search_by_concept(query)

    def get_paper_concepts(self, paper_id: int) -> dict:
        """取得某篇論文的所有概念"""
        return self.db.get_paper_concepts(paper_id)

    def get_all_concepts(self, concept_type: Optional[str] = None) -> list[dict]:
        """取得所有概念（可按類型篩選），依使用頻率排序"""
        return self.db.get_all_concepts(concept_type)

    def find_papers_sharing_concepts(self, paper_id: int, top_k: int = 10) -> list[dict]:
        """
        找出與指定論文共享最多概念的其他論文

        Returns:
            [{"paper": Paper, "shared_concepts": [...], "shared_count": N}, ...]
        """
        my_concepts = self.db.get_paper_concepts(paper_id)
        all_my = {
            name
            for names in my_concepts.values()
            for name in names
        }
        if not all_my:
            return []

        # 對每個概念查論文，統計重疊數
        paper_overlap: dict[int, dict] = {}
        for ctype, names in my_concepts.items():
            for name in names:
                matching_papers = self.db.search_by_concept(name)
                for p in matching_papers:
                    if p.id == paper_id:
                        continue
                    if p.id not in paper_overlap:
                        paper_overlap[p.id] = {"paper": p, "shared_concepts": []}
                    label = f"{name} ({TYPE_LABELS.get(ctype, ctype)})"
                    if label not in paper_overlap[p.id]["shared_concepts"]:
                        paper_overlap[p.id]["shared_concepts"].append(label)

        result = [
            {**v, "shared_count": len(v["shared_concepts"])}
            for v in paper_overlap.values()
        ]
        result.sort(key=lambda x: x["shared_count"], reverse=True)
        return result[:top_k]
