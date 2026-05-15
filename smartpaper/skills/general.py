from .base_skill import SkillConfig

GENERAL = SkillConfig(
    id="general",
    name="通用學術研究員",
    description="適用於各種學術領域，均衡分析論文的研究目的、方法與貢獻",
    system_prompt=(
        "你是一位具有廣泛學術背景的資深研究員，"
        "擅長客觀分析各領域的學術論文，能清楚辨別論文的核心貢獻與研究價值。"
    ),
    tag_categories=[
        "Machine Learning", "Deep Learning", "Natural Language Processing",
        "Computer Vision", "Data Mining", "Healthcare", "Finance",
        "Education", "Security", "IoT", "Optimization", "Survey",
    ],
    classification_criteria=(
        "1. 論文的研究主題是否與該主題直接相關\n"
        "2. 論文使用的方法或技術是否屬於該領域\n"
        "3. 論文的應用場景是否涉及該主題"
    ),
    summary_style="從研究目的、研究方法、主要發現三個維度進行總結",
)
