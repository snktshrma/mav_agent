"""MCP JSON-RPC handling"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from mav_agent.session import DroneSession
from mav_agent.skills.registry import (
    get_skill,
    list_skills,
    skill_input_schema,
    validate_and_stringify_args,
)

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-11-25"


def _jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_result_text(req_id: Any, text: str) -> dict[str, Any]:
    return _jsonrpc_result(req_id, {"content": [{"type": "text", "text": text}]})


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_initialize(req_id: Any) -> dict[str, Any]:
    return _jsonrpc_result(
        req_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mav-agent", "version": "0.1.0"},
        },
    )


def _skill_to_mcp_tool(skill_name: str) -> dict[str, Any]:
    s = get_skill(skill_name)
    assert s is not None
    return {
        "name": s.name,
        "description": s.description,
        "inputSchema": skill_input_schema(s),
    }


def _handle_tools_list(req_id: Any) -> dict[str, Any]:
    tools = [_skill_to_mcp_tool(s.name) for s in list_skills() if s.args_model is not None]
    return _jsonrpc_result(req_id, {"tools": tools})


def _handle_tools_call_sync(
    req_id: Any,
    params: dict[str, Any],
    session: DroneSession,
) -> dict[str, Any]:
    name = str(params.get("name", "") or "")
    if not name:
        return _jsonrpc_error(req_id, -32602, "Missing tool name")
    skill = get_skill(name)
    if skill is None or skill.args_model is None:
        return _jsonrpc_result_text(req_id, f"Tool not found: {name}")
    try:
        args = validate_and_stringify_args(skill, params.get("arguments"))
    except ValueError as e:
        return _jsonrpc_error(req_id, -32602, f"Invalid tool arguments: {e}")

    t0 = time.monotonic()
    try:
        text = session.dispatch_skill(name, args)
    except Exception as e:
        logger.exception("MCP tools/call failed tool=%s", name)
        return _jsonrpc_result_text(req_id, f"Error running tool '{name}': {e}")

    duration = time.monotonic() - t0
    logger.info("MCP tool done tool=%s duration=%.3fs", name, duration)
    return _jsonrpc_result_text(req_id, text)


def handle_jsonrpc(
    request: dict[str, Any],
    session: DroneSession,
) -> dict[str, Any] | None:
    """Handle one JSON-RPC object. Returns None for notifications (no id)."""
    method = request.get("method", "")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    req_id = request.get("id")

    if "id" not in request:
        return None

    if method == "initialize":
        return _handle_initialize(req_id)
    if method == "tools/list":
        return _handle_tools_list(req_id)
    if method == "tools/call":
        return _handle_tools_call_sync(req_id, params, session)

    return _jsonrpc_error(req_id, -32601, f"Unknown method: {method}")


def parse_json_body(raw: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """Return (body, error_message). error_message set if parse fails."""
    if not raw.strip():
        return None, "empty body"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, str(e)
    if not isinstance(data, dict):
        return None, "JSON must be an object"
    return data, None
