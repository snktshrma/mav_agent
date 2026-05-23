"""LangGraph create_react_agent over the skill registry + dispatch."""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import SecretStr

from mav_agent.defaults import DEFAULT_AGENT_RECURSION_LIMIT
from mav_agent.session import DroneSession
from mav_agent.skills.registry import SkillInfo, list_skills, validate_and_stringify_args

SYSTEM_PROMPT = (
    "You control an ArduPilot Copter via tools (backend mavlink or ros2). Use tools; do not invent results.\n"
    "Multi-step missions: If the user lists several actions in one message (connect, arm, takeoff, moves), "
    "you MUST run EVERY step as separate tool calls in order. Do not stop after the first tool. "
    "Do not skip to the last step. Read each tool result, then call the next tool until the mission is done.\n"
    "Boot sequence: connect (if needed) -> arm_takeoff altitude=<m> (preferred over separate arm+takeoff; "
    "blocks until climb). Then each move as its own move_to_position call.\n"
    "Position moves (meters forward/back/left/right): move_to_position only (BODY_OFFSET: x=forward, "
    "y=right, z=down). forward=+x, back=-x, right=+y, left=-y. One call per leg. "
    "Do not use velocity for distance.\n"
    "Velocity moves (m/s): move_velocity or move_trajectory. Omit duration for default 5s stream.\n"
    "GUIDED only for arm/takeoff/motion; use land/rtl/loiter/set_mode when the user asks for those modes.\n"
    "Safety: land, rtl, loiter, disarm, stop_motion. "
    "Telemetry: vehicle_state for lat/lon, altitude, pose, yaw. "
    "Vision: describe, follow (needs video). Be brief in the final summary after all tools finish."
)


def _tools_for_session(session: DroneSession) -> list[StructuredTool]:
    tools: list[StructuredTool] = []
    for s in list_skills():
        if s.args_model is None:
            continue
        skill_name = s.name

        def _make(name: str, skill: SkillInfo) -> Any:
            def _fn(**kwargs: Any) -> str:
                try:
                    args = validate_and_stringify_args(skill, kwargs)
                except ValueError as e:
                    return f"Invalid tool arguments: {e}"
                try:
                    return session.dispatch_skill(name, args)
                except Exception as e:
                    return f"Tool error ({name}): {e}"

            return _fn

        tools.append(
            StructuredTool.from_function(
                name=s.name,
                description=s.description,
                func=_make(skill_name, s),
                args_schema=s.args_model,
            )
        )
    return tools


def build_agent_graph(session: DroneSession, api_key: str, model: str) -> Any:
    tools = _tools_for_session(session)
    llm = ChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        model_kwargs={"parallel_tool_calls": False},
    )
    graph = create_react_agent(
        llm,
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=MemorySaver(),
    )
    graph._mav_invoke_lock = threading.Lock()  # type: ignore[attr-defined]
    return graph


def _invoke_lock(graph: Any) -> threading.Lock:
    lock = getattr(graph, "_mav_invoke_lock", None)
    if lock is None:
        lock = threading.Lock()
        graph._mav_invoke_lock = lock  # type: ignore[attr-defined]
    return lock


def record_manual_stop(graph: Any, config: dict[str, Any], result: str) -> None:
    """Tell the agent the user stopped tracking outside LangGraph (e.g. TUI `stop` / `!stop`)."""
    with _invoke_lock(graph):
        graph.update_state(
            config,
            {
                "messages": [
                    HumanMessage(content="User manually stopped tracking."),
                    AIMessage(content=result),
                ]
            },
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


def format_agent_turn_reply(messages: list[BaseMessage]) -> str:
    """Show each tool result from this turn, then the final assistant text."""
    last_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last_idx = i
    turn = messages[last_idx + 1 :] if last_idx >= 0 else messages
    lines: list[str] = []
    for m in turn:
        if isinstance(m, ToolMessage):
            name = m.name or "tool"
            content = m.content if isinstance(m.content, str) else str(m.content)
            lines.append(f"{name}: {content}")
    final = _last_assistant_text(messages)
    if lines:
        body = "\n".join(lines)
        if final and final != "(no assistant reply)":
            return f"{body}\n\n{final}"
        return body
    return final


def run_langchain_turn(graph: Any, user_text: str, config: dict[str, Any]) -> str:
    run_config = {**config, "recursion_limit": DEFAULT_AGENT_RECURSION_LIMIT}
    with _invoke_lock(graph):
        result = graph.invoke({"messages": [HumanMessage(content=user_text)]}, run_config)
    msgs = result.get("messages", [])
    return format_agent_turn_reply(msgs)
