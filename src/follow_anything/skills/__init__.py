from __future__ import annotations

import follow_anything.skills.builtin  # noqa: F401 - register built-in skills
from follow_anything.skills.registry import SkillInfo, dispatch, list_skills, register_skill

__all__ = [
    "SkillInfo",
    "dispatch",
    "list_skills",
    "register_skill",
]
