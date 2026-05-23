from __future__ import annotations

from mav_agent.skills.discovery import load_all_skills
from mav_agent.skills.registry import SkillInfo, dispatch, list_skills, register_skill

load_all_skills()

__all__ = [
    "SkillInfo",
    "dispatch",
    "list_skills",
    "load_all_skills",
    "register_skill",
]
