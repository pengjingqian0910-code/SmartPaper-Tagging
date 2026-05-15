from .base_skill import SkillConfig
from .general import GENERAL
from .ml_researcher import ML_RESEARCHER
from .healthcare import HEALTHCARE

ALL_SKILLS: dict[str, SkillConfig] = {
    "general": GENERAL,
    "ml_researcher": ML_RESEARCHER,
    "healthcare": HEALTHCARE,
}


def get_skill(skill_id: str) -> SkillConfig:
    return ALL_SKILLS.get(skill_id, GENERAL)
