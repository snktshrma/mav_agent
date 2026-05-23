"""Load built-in and entry-point registered skills."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from mav_agent.skills.flight import register_flight_skills
from mav_agent.skills.meta import register_meta_skills
from mav_agent.skills.vision import register_vision_skills

logger = logging.getLogger(__name__)


def register_builtin_skills() -> None:
    register_flight_skills()
    register_vision_skills()
    register_meta_skills()


def load_entry_point_skills() -> None:
    """Register skills from setuptools entry point group ``mav_agent.skills``."""
    try:
        eps = entry_points(group="mav_agent.skills")
    except TypeError:
        eps = entry_points().get("mav_agent.skills", ())
    for ep in eps:
        try:
            register_fn = ep.load()
            if callable(register_fn):
                register_fn()
                logger.debug("Loaded skill entry point: %s", ep.name)
        except Exception:
            logger.exception("Failed to load skill entry point %s", ep.name)


def load_all_skills() -> None:
    register_builtin_skills()
    load_entry_point_skills()
