"""Agent system prompt and OpenAI API resolution for the LangGraph CLI."""

from __future__ import annotations

import os

SYSTEM_PROMPT = (
    "You control a MAVLink drone stack with tools. Use tools to act; do not invent results.\n"
    "Prefer: connect MAVLink first if needed, set RTSP if video is required, "
    "then follow/stop/status as appropriate.\n"
    "Be brief in final replies."
)


def resolve_openai(api_key_cli: str | None, model_cli: str | None) -> tuple[str | None, str]:
    key = api_key_cli if api_key_cli is not None else os.environ.get("OPENAI_API_KEY")
    model = (
        model_cli
        if model_cli is not None
        else os.environ.get("FOLLOW_ANYTHING_OPENAI_MODEL", "gpt-4o-mini")
    )
    return key, model
