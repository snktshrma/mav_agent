from __future__ import annotations

import argparse
import os
import shlex
import sys
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Input, RichLog
from textual.worker import Worker, WorkerState

import mav_agent.skills  # noqa: F401  # registers built-in skills via package __init__
from mav_agent.control.config import ControlConfig, PerceptionConfig
from mav_agent.defaults import (
    DEFAULT_BACKEND,
    DEFAULT_CONNECTION,
    DEFAULT_IMAGE_SOURCE,
    DEFAULT_MCP_HOST,
    DEFAULT_MCP_PORT,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_QWEN_MODEL,
    DEFAULT_ROS_IMAGE_TOPIC,
    DEFAULT_VIDEO_UDP_PORT,
    QWEN_API,
    QWEN_DEFAULT_BASE_URL,
)
from mav_agent.session import DroneSession


def parse_command_line(line: str) -> tuple[str | None, dict[str, str], str | None]:
    """Return (command, args, error_message). command None if empty."""
    stripped = line.strip()
    if not stripped:
        return None, {}, None
    try:
        parts = shlex.split(stripped)
    except ValueError:
        return None, {}, "Invalid quoting in command."
    if not parts:
        return None, {}, None
    cmd = parts[0].lstrip("/").lower()
    kwargs: dict[str, str] = {}
    positionals: list[str] = []
    for p in parts[1:]:
        if "=" in p:
            k, _, v = p.partition("=")
            kwargs[k.strip().lower()] = v.strip()
        else:
            positionals.append(p)
    if positionals:
        kwargs["_positional"] = positionals[0]
        if len(positionals) > 1:
            kwargs["_positional_rest"] = " ".join(positionals[1:])
    return cmd, kwargs, None


# Instant skill dispatch (no LangGraph / OpenAI round-trip).
_DIRECT_COMMANDS = frozenset({"stop", "status", "help"})


class HumanCLIApp(App[None]):
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    Screen { background: #0c0c0c; }
    #chat { height: 1fr; border: solid #333; }
    Input { dock: bottom; }
    """

    def __init__(self, session: DroneSession, langchain_graph: Any) -> None:
        super().__init__()
        self._session = session
        self._langchain_graph = langchain_graph
        self._busy = False

    def compose(self) -> ComposeResult:
        with Container(id="chat"):
            yield RichLog(id="log", highlight=True, markup=True)
        yield Input(placeholder="natural language [LangGraph] (or !command) ...", id="cmd")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(
            "[bold]mav-agent[/] [magenta]agent[/] [dim](LangGraph)[/] - "
            "Prefix [bold]![/] for direct skills. "
            "[bold]stop[/]/[bold]status[/]/[bold]help[/] run instantly. [bold]quit[/] to exit."
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        inp = self.query_one("#cmd", Input)
        inp.disabled = busy
        if busy:
            inp.placeholder = "Working..."
        else:
            inp.placeholder = "natural language [LangGraph] (or !command) ..."

    @on(Input.Submitted, "#cmd")
    def handle_submit(self, event: Input.Submitted) -> None:
        inp = event.input
        line = inp.value.strip()
        inp.value = ""
        low = line.lower()
        if low in ("q", "quit", "exit"):
            self.exit()
            return
        log = self.query_one("#log", RichLog)
        if not line:
            return
        if self._busy:
            log.write("[yellow]Busy - wait for the current command to finish.[/]")
            return

        if line.startswith("!"):
            log.write(f"[green]{line}[/]")
            direct = line[1:].lstrip()
            cmd, args, err = parse_command_line(direct)
            if err:
                log.write(f"[red]{err}[/]")
                return
            if cmd is None:
                return
            self._set_busy(True)
            self._run_direct_skill(line, cmd, args)
            return

        log.write(f"[green]> {line}[/]")
        self._set_busy(True)
        if low in _DIRECT_COMMANDS:
            self._run_direct_skill(line, low, {})
        else:
            self._run_agent_turn(line)

    @work(thread=True, exclusive=True, exit_on_error=False, group="tui_command")
    def _run_agent_turn(self, line: str) -> str:
        from mav_agent.agent_langchain import run_langchain_turn

        return run_langchain_turn(
            self._langchain_graph,
            line,
            {"configurable": {"thread_id": "mav-cli"}},
        )

    @work(thread=True, exclusive=True, exit_on_error=False, group="tui_command")
    def _run_direct_skill(self, user_line: str, cmd: str, args: dict[str, str]) -> str:
        result = self._session.dispatch_skill(cmd, args)
        if cmd == "stop":
            from mav_agent.agent_langchain import record_manual_stop

            record_manual_stop(
                self._langchain_graph,
                {"configurable": {"thread_id": "mav-cli"}},
                result,
            )
        return result

    @on(Worker.StateChanged)
    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "tui_command":
            return
        if event.state == WorkerState.RUNNING:
            return
        log = self.query_one("#log", RichLog)
        self._set_busy(False)
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if result:
                if event.worker.name == "_run_agent_turn":
                    log.write(str(result))
                else:
                    log.write(f"[cyan]{result}[/]")
        elif event.state == WorkerState.ERROR:
            err = event.worker.error
            log.write(f"[red]Error: {err}[/]")

    async def action_quit(self) -> None:
        self.exit()


def _build_control_config(args: argparse.Namespace) -> ControlConfig:
    backend = args.backend.strip().lower()
    if backend == "ros2":
        source = "ros"
    else:
        source = args.image_source.strip().lower()
    return ControlConfig(
        backend=backend,
        connection_string=args.connection,
        perception=PerceptionConfig(
            source=source,
            ros_image_topic=args.ros_image_topic,
            video_udp_port=args.video_port,
        ),
    )


def _maybe_start_video(session: DroneSession, control_config: ControlConfig, rtsp_url: str | None) -> None:
    try:
        session.get_perception_kind()
    except ValueError:
        return
    p = control_config.perception
    if session.start_video():
        if control_config.backend == "ros2":
            print(f"Video: ROS topic {p.ros_image_topic}", flush=True)
        elif p.source == "udp":
            print(
                f"Video: UDP port {p.video_udp_port} "
                "(mav-cli owns gst-launch; stop any other viewer on this port).",
                flush=True,
            )
        elif p.source == "rtsp" and rtsp_url:
            print(f"Video: RTSP {rtsp_url}", flush=True)
    elif control_config.backend == "ros2" or p.source == "udp":
        print("Video: failed to start receiver.", file=sys.stderr, flush=True)


def main() -> None:
    p = argparse.ArgumentParser(
        description="mav-cli: LangGraph agent TUI (default) or MCP HTTP server (--mcp)."
    )
    p.add_argument(
        "--mcp",
        action="store_true",
        help="MCP HTTP server only (default: LangGraph agent TUI)",
    )
    p.add_argument("--connection", default=DEFAULT_CONNECTION, help="MAVLink connection string")
    p.add_argument(
        "--backend",
        choices=("mavlink", "ros2"),
        default=DEFAULT_BACKEND,
        help="Vehicle control: mavlink (pymavlink) or ros2 (ArduPilot DDS topics)",
    )
    p.add_argument(
        "--image-source",
        choices=("udp", "rtsp"),
        default=DEFAULT_IMAGE_SOURCE,
        help="Video for mavlink (default udp). rtsp needs --rtsp. Ignored for ros2.",
    )
    p.add_argument(
        "--video-port",
        type=int,
        default=DEFAULT_VIDEO_UDP_PORT,
        help=f"Camera UDP port for --image-source udp (default {DEFAULT_VIDEO_UDP_PORT}). Not RTSP.",
    )
    p.add_argument(
        "--ros-image-topic",
        default=DEFAULT_ROS_IMAGE_TOPIC,
        help="ROS image topic when --backend ros2",
    )
    p.add_argument("--rtsp", default=None, help="Optional default RTSP URL")
    p.add_argument(
        "--qwen-api",
        choices=("local", "remote"),
        default=QWEN_API,
        help="Qwen-VL backend: local OpenAI-compatible server or Alibaba DashScope (remote)",
    )
    p.add_argument(
        "--qwen-base-url",
        default=QWEN_DEFAULT_BASE_URL,
        help="Local Qwen OpenAI-compatible base URL (--qwen-api local)",
    )
    p.add_argument(
        "--qwen-model",
        default=DEFAULT_QWEN_MODEL,
        help="Qwen-VL model name (local server; remote uses Alibaba default unless overridden)",
    )
    p.add_argument(
        "--mcp-host",
        default=DEFAULT_MCP_HOST,
        help=f"MCP bind address (default {DEFAULT_MCP_HOST})",
    )
    p.add_argument(
        "--mcp-port",
        type=int,
        default=DEFAULT_MCP_PORT,
        help=f"MCP port (default {DEFAULT_MCP_PORT})",
    )
    args = p.parse_args()
    control_config = _build_control_config(args)
    session = DroneSession(
        rtsp_url=args.rtsp,
        qwen_model=args.qwen_model,
        qwen_base_url=args.qwen_base_url,
        qwen_api=args.qwen_api,
        control_config=control_config,
    )

    if args.mcp:
        _maybe_start_video(session, control_config, args.rtsp)
        try:
            from mav_agent.mcp.server import run_mcp_blocking

            print(
                f"MCP server http://{args.mcp_host}:{args.mcp_port}/mcp (GET /health). Ctrl+C to stop.",
                flush=True,
            )
            run_mcp_blocking(session, host=args.mcp_host, port=args.mcp_port)
        finally:
            session.close()
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Agent mode requires OPENAI_API_KEY", file=sys.stderr)
        raise SystemExit(2)
    from mav_agent.agent_langchain import build_agent_graph

    lc_graph = build_agent_graph(session, api_key, DEFAULT_OPENAI_MODEL)

    _maybe_start_video(session, control_config, args.rtsp)

    try:
        app = HumanCLIApp(session, lc_graph)
        app.run()
    finally:
        session.close()


if __name__ == "__main__":
    main()
