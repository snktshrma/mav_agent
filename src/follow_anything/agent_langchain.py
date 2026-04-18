"""LangGraph create_react_agent over the skill registry + dispatch."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, ConfigDict, Field, SecretStr, create_model

from follow_anything.agent import SYSTEM_PROMPT
from follow_anything.session import DroneSession
from follow_anything.skills.registry import dispatch, list_skills


class _EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _tools_for_session(session: DroneSession) -> list[StructuredTool]:
    tools: list[StructuredTool] = []
    for s in list_skills():
        if s.openai is None:
            continue
        if not s.openai:
            schema: type[BaseModel] = _EmptyArgs
        else:
            fields = {k: (str, Field(description=v)) for k, v in s.openai.items()}
            schema = create_model(
                f"Args_{s.name}",
                __config__=ConfigDict(extra="forbid"),
                **fields,
            )  # type: ignore[call-overload]
        skill_name = s.name

        def _make(name: str) -> Any:
            def _fn(**kwargs: Any) -> str:
                return dispatch(
                    session,
                    name,
                    {k: "" if v is None else str(v) for k, v in kwargs.items()},
                )

            return _fn

        tools.append(
            StructuredTool.from_function(
                name=s.name,
                description=s.description,
                func=_make(skill_name),
                args_schema=schema,
            )
        )
    return tools


def build_agent_graph(session: DroneSession, model: str, api_key: str) -> Any:
    tools = _tools_for_session(session)
    llm = ChatOpenAI(model=model, api_key=SecretStr(api_key))
    return create_react_agent(
        llm,
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=MemorySaver(),
    )


def _text_from_ai_message(msg: AIMessage) -> str:
    c = msg.content
    if isinstance(c, str) and c.strip():
        return c.strip()
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        if parts:
            return "\n".join(parts).strip()
    return ""


def _last_assistant_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            t = _text_from_ai_message(m)
            if t:
                return t
    return "(no assistant reply)"


def run_langchain_turn(graph: Any, user_text: str, config: dict[str, Any]) -> str:
    result = graph.invoke({"messages": [HumanMessage(content=user_text)]}, config)
    msgs = result.get("messages", [])
    return _last_assistant_text(msgs)
