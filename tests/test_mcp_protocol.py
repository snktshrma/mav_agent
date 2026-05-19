"""Contract tests for MCP JSON-RPC (no HTTP)."""

from __future__ import annotations

import threading

import pytest

import follow_anything.skills  # noqa: F401
from follow_anything.mcp.protocol import handle_jsonrpc
from follow_anything.session import DroneSession


@pytest.fixture
def session() -> DroneSession:
    return DroneSession(connection_string="udp:0.0.0.0:14550")


@pytest.fixture
def lock() -> threading.Lock:
    return threading.Lock()


def test_initialize(session: DroneSession, lock: threading.Lock) -> None:
    r = handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, session, lock)
    assert r is not None
    assert r["id"] == 1
    assert r["result"]["protocolVersion"]
    assert r["result"]["serverInfo"]["name"] == "follow-anything"


def test_tools_list(session: DroneSession, lock: threading.Lock) -> None:
    r = handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session, lock)
    assert r is not None
    tools = r["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "follow" in names
    assert "arm" in names
    assert "takeoff" in names
    assert "arm_takeoff" in names
    assert "help" not in names
    for t in tools:
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


def test_tools_call_unknown(session: DroneSession, lock: threading.Lock) -> None:
    r = handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "nosuch", "arguments": {}},
        },
        session,
        lock,
    )
    assert r is not None
    text = r["result"]["content"][0]["text"]
    assert "not found" in text.lower()


def test_tools_call_invalid_args(session: DroneSession, lock: threading.Lock) -> None:
    r = handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "rtsp", "arguments": {"url": ["bad"]}},
        },
        session,
        lock,
    )
    assert r is not None
    assert "error" in r
    assert r["error"]["code"] == -32602


def test_unknown_method(session: DroneSession, lock: threading.Lock) -> None:
    r = handle_jsonrpc({"jsonrpc": "2.0", "id": 4, "method": "foo"}, session, lock)
    assert r is not None
    assert "error" in r
