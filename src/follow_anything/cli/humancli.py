from __future__ import annotations

import argparse
import shlex
import sys
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Input, RichLog

import follow_anything.skills  # noqa: F401  # registers built-in skills via package __init__
from follow_anything.agent import resolve_openai
from follow_anything.session import DroneSession
from follow_anything.skills.registry import dispatch


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

    def __init__(
        self,
        session: DroneSession,
        *,
        agent: bool = False,
        langchain_graph: Any | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._agent = agent
        self._langchain_graph = langchain_graph

    def compose(self) -> ComposeResult:
        with Container(id="chat"):
            yield RichLog(id="log", highlight=True, markup=True)
        if self._agent:
            ph = "natural language [LangGraph] (or !command) ..."
        else:
            ph = "command (help, connect, rtsp url=..., follow query=...)"
        yield Input(placeholder=ph, id="cmd")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        if self._agent:
            log.write(
                "[bold]follow-anything[/] [magenta]agent[/] [dim](LangGraph)[/] - "
                "Prefix [bold]![/] for direct skills. [bold]quit[/] to exit."
            )
        else:
            log.write("[bold]follow-anything[/] - type [bold]help[/] or [bold]quit[/]")

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

        if self._agent:
            assert self._langchain_graph is not None
            if line.startswith("!"):
                direct = line[1:].lstrip()
                cmd, args, err = parse_command_line(direct)
                if err:
                    log.write(f"[red]{err}[/]")
                    return
                if cmd is None:
                    return
                out = dispatch(self._session, cmd, args)
                log.write(f"[cyan]! {direct}[/]\n{out}")
                return
            from follow_anything.agent_langchain import run_langchain_turn

            reply = run_langchain_turn(
                self._langchain_graph,
                line,
                {"configurable": {"thread_id": "mav-cli"}},
            )
            log.write(f"[green]> {line}[/]\n{reply}")
            return

        cmd, args, err = parse_command_line(line)
        if err:
            log.write(f"[red]{err}[/]")
            return
        if cmd is None:
            return
        out = dispatch(self._session, cmd, args)
        log.write(f"[cyan]> {line}[/]\n{out}")

    async def action_quit(self) -> None:
        self.exit()


def main() -> None:
    p = argparse.ArgumentParser(
        description="MAVLink skills TUI (mav-cli): registry includes follow, connect, rtsp, etc."
    )
    p.add_argument("--connection", default="udp:0.0.0.0:14550", help="MAVLink connection string")
    p.add_argument("--rtsp", default=None, help="Optional default RTSP URL")
    p.add_argument("--qwen-model", default="qwen2.5-vl-72b-instruct", help="Qwen-VL model name")
    p.add_argument(
        "--agent",
        action="store_true",
        help="LangGraph agent: natural language maps to skills (needs OPENAI_API_KEY)",
    )
    p.add_argument(
        "--openai-model",
        default=None,
        help="OpenAI model for --agent (default: env FOLLOW_ANYTHING_OPENAI_MODEL or gpt-4o-mini)",
    )
    p.add_argument(
        "--openai-api-key",
        default=None,
        help="OpenAI API key (default: env OPENAI_API_KEY)",
    )
    args = p.parse_args()
    session = DroneSession(
        connection_string=args.connection,
        rtsp_url=args.rtsp,
        qwen_model=args.qwen_model,
    )
    api_key, openai_model = resolve_openai(args.openai_api_key, args.openai_model)
    lc_graph: Any | None = None
    if args.agent:
        if not api_key:
            print("Agent mode requires OPENAI_API_KEY or --openai-api-key", file=sys.stderr)
            raise SystemExit(2)
        from follow_anything.agent_langchain import build_agent_graph

        assert api_key is not None
        lc_graph = build_agent_graph(session, openai_model, api_key)
    try:
        app = HumanCLIApp(
            session,
            agent=args.agent,
            langchain_graph=lc_graph,
        )
        app.run()
    finally:
        session.close()


if __name__ == "__main__":
    main()
