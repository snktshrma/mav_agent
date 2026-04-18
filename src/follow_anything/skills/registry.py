from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from follow_anything.session import DroneSession

# SkillHandler is a function type that takes a DroneSession and argument dict, returns a string.
# Example usage:
# def example_handler(session: DroneSession, args: dict[str, str]) -> str:
#     return f"Hello, {args.get('name', 'world')}!"
SkillHandler = Callable[[DroneSession, dict[str, str]], str]
ForOpenAI = bool | Mapping[str, str]


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    handler: SkillHandler
    openai: dict[str, str] | None
    """If None, skill is not exposed to the LLM. Empty dict: no parameters. Else param name -> help."""


_REGISTRY: dict[str, SkillInfo] = {}


def register_skill(
    name: str,
    description: str,
    handler: SkillHandler,
    *,
    for_openai: ForOpenAI = True,
) -> None:
    key = name.strip().lower()
    if for_openai is False:
        oa: dict[str, str] | None = None
    elif for_openai is True:
        oa = {}
    else:
        oa = dict(for_openai)
    _REGISTRY[key] = SkillInfo(name=key, description=description, handler=handler, openai=oa)


def list_skills() -> list[SkillInfo]:
    return sorted(_REGISTRY.values(), key=lambda s: s.name)


def dispatch(session: DroneSession, name: str, args: dict[str, str]) -> str:
    key = name.strip().lower()
    info = _REGISTRY.get(key)
    if info is None:
        return f"Unknown command: {name}. Type help."
    return info.handler(session, args)
