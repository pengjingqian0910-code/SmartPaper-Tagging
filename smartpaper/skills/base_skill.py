from dataclasses import dataclass, field


@dataclass
class SkillConfig:
    id: str
    name: str
    description: str
    system_prompt: str
    tag_categories: list[str]
    classification_criteria: str
    summary_style: str
