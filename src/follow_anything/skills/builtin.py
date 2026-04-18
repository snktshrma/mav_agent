from __future__ import annotations

from follow_anything.session import DroneSession
from follow_anything.skills.registry import list_skills, register_skill


def _query_from_args(args: dict[str, str], default: str) -> str:
    if args.get("query"):
        return args["query"]
    if args.get("q"):
        return args["q"]
    if args.get("_positional"):
        return args["_positional"]
    return default


def _connect(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    t = session.get_tracker()
    if t.connect_mavlink():
        return "MAVLink connected."
    return "MAVLink connection failed."


def _rtsp(session: DroneSession, args: dict[str, str]) -> str:
    url = (args.get("url") or args.get("_positional") or "").strip()
    if not url:
        return "Usage: rtsp url=<rtsp_url>"
    return session.start_rtsp(url)


def _follow(session: DroneSession, args: dict[str, str]) -> str:
    query = _query_from_args(args, "person")
    duration_s = args.get("duration", "0")
    try:
        duration = float(duration_s)
    except ValueError:
        return "Invalid duration (expected a number)."
    return session.get_tracker().track(query=query, duration=duration)


def _stop(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    return session.get_tracker().stop_tracking()


def _status(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    t = session.get_tracker()
    lines = [
        f"MAVLink: {'connected' if t.is_mavlink_connected else 'not connected'}",
        f"Tracking active: {t.is_active()}",
    ]
    return "\n".join(lines)


def _help(session: DroneSession, args: dict[str, str]) -> str:
    _ = session, args
    lines = ["Commands (name plus key=value or positional args):"]
    for s in list_skills():
        lines.append(f"  {s.name}: {s.description}")
    lines.append("  quit / q: exit TUI")
    return "\n".join(lines)


def register_builtin_skills() -> None:
    register_skill("connect", "Connect MAVLink using session --connection", _connect)
    register_skill(
        "rtsp",
        "Start RTSP video stream before follow or tracking",
        _rtsp,
        for_openai={
            "url": "RTSP URL (e.g. rtsp://host:8554/stream)",
        },
    )
    register_skill(
        "follow",
        "Start visual follow: Qwen bbox + CSRT + velocity commands",
        _follow,
        for_openai={
            "query": "What to detect and track (e.g. person, car)",
            "duration": "Seconds to run; 0 means until stop",
        },
    )
    register_skill("stop", "Stop visual tracking", _stop)
    register_skill("status", "Report MAVLink connection and whether tracking is active", _status)
    register_skill(
        "help",
        "List direct commands (for humans, not needed for tool use)",
        _help,
        for_openai=False,
    )


register_builtin_skills()
