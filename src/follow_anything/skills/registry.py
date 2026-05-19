from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model
from follow_anything.session import DroneSession

# SkillHandler is a function type that takes a DroneSession and argument dict, returns a string.
# Example usage:
# def example_handler(session: DroneSession, args: dict[str, str]) -> str:
#     return f"Hello, {args.get('name', 'world')}!"
SkillHandler = Callable[[DroneSession, dict[str, str]], str]
ForOpenAI = bool | Mapping[str, str]
SkillArgsModel = type[BaseModel]


class _EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    handler: SkillHandler
    args_model: SkillArgsModel | None
    """None means not exposed to LLM/MCP. Otherwise shared typed args schema."""


_REGISTRY: dict[str, SkillInfo] = {}


def register_skill(
    name: str,
    description: str,
    handler: SkillHandler,
    *,
    for_openai: ForOpenAI = True,
) -> None:
    key = name.strip().lower()
    title = "".join(part.capitalize() for part in key.replace("-", "_").split("_")) or "Skill"
    if for_openai is False:
        args_model: SkillArgsModel | None = None
    elif for_openai is True:
        args_model = _EmptyArgs
    else:
        fields = {k: (str, Field(description=v)) for k, v in dict(for_openai).items()}
        args_model = create_model(
            f"{title}Args",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )  # type: ignore[call-overload]
    _REGISTRY[key] = SkillInfo(
        name=key,
        description=description,
        handler=handler,
        args_model=args_model,
    )


def list_skills() -> list[SkillInfo]:
    return sorted(_REGISTRY.values(), key=lambda s: s.name)


def get_skill(name: str) -> SkillInfo | None:
    return _REGISTRY.get(name.strip().lower())


def skill_input_schema(skill: SkillInfo) -> dict[str, Any]:
    if skill.args_model is None:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    schema = dict(skill.args_model.model_json_schema())
    schema.pop("title", None)
    return schema


def validate_and_stringify_args(skill: SkillInfo, raw: Any) -> dict[str, str]:
    if skill.args_model is None:
        return {}
    payload = raw if isinstance(raw, dict) else {}
    try:
        validated = skill.args_model.model_validate(payload)
    except ValidationError as e:
        raise ValueError(e.errors(include_url=False)) from e
    obj = validated.model_dump(mode="python", exclude_none=False)
    out: dict[str, str] = {}
    for k, v in obj.items():
        if v is None:
            out[str(k)] = ""
        elif isinstance(v, bool):
            out[str(k)] = "true" if v else "false"
        else:
            out[str(k)] = str(v)
    return out


def dispatch(session: DroneSession, name: str, args: dict[str, str]) -> str:
    key = name.strip().lower()
    info = _REGISTRY.get(key)
    if info is None:
        return f"Unknown command: {name}. Type help."
    return info.handler(session, args)
