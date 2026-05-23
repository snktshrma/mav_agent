from __future__ import annotations

from mav_agent.defaults import DEFAULT_TELEMETRY_HZ
from mav_agent.session import DroneSession
from mav_agent.skills.helpers import ensure_connected, float_arg
from mav_agent.skills.registry import list_skills, register_skill


def _image_source_label(session: DroneSession) -> str:
    try:
        return session.get_perception_kind()
    except ValueError:
        return "none (mavlink: --image-source udp|rtsp; ros2: --ros-image-topic)"


def _status(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    c = session.get_control()
    t = session.get_tracker()
    lines = [
        f"Backend: {c.backend_name}",
        f"Connected: {c.is_connected}",
        f"Tracking active: {t.is_active()}",
        f"Image source: {_image_source_label(session)}",
    ]
    if c.is_connected:
        mode = c.get_flight_mode()
        if mode:
            lines.append(f"Flight mode: {mode}")
        elif c.backend_name == "ros2":
            lines.append("Flight mode: unknown (set_mode updates from service reply)")
        armed_state = getattr(c, "armed_state", None)
        if callable(armed_state):
            known = armed_state()
            if known is None:
                lines.append("Armed: unknown (no AP DDS status topic; run arm/disarm)")
            else:
                lines.append(f"Armed: {known}")
        else:
            lines.append(f"Armed: {c.is_armed()}")
        get_state = getattr(c, "get_vehicle_state", None)
        if callable(get_state):
            state = get_state(timeout=1.0, ensure_streams=False)
            if state is not None:
                lines.extend(state.summary_lines())
    return "\n".join(lines)


def _vehicle_state(session: DroneSession, args: dict[str, str]) -> str:
    c, err = ensure_connected(session)
    if err:
        return err
    get_state = getattr(c, "get_vehicle_state", None)
    if not callable(get_state):
        return "Vehicle telemetry not supported on this backend."
    timeout = float_arg(args, "timeout", 2.0)
    rate_hz = float_arg(args, "rate_hz", DEFAULT_TELEMETRY_HZ)
    if timeout is None or timeout <= 0:
        return "Invalid timeout (expected seconds > 0)."
    if rate_hz is None or rate_hz <= 0:
        return "Invalid rate_hz (expected Hz > 0)."
    state = get_state(timeout=timeout, rate_hz=rate_hz)
    if state is None:
        return (
            "No vehicle telemetry received. Check GPS/EKF on the vehicle or increase timeout."
        )
    lines = state.summary_lines()
    return "\n".join(lines) if lines else "No data"


def _help(session: DroneSession, args: dict[str, str]) -> str:
    _ = session, args
    lines = ["Commands (name plus key=value or positional args):"]
    for s in list_skills():
        lines.append(f"  {s.name}: {s.description}")
    lines.append("  quit / q: exit TUI")
    return "\n".join(lines)


def register_meta_skills() -> None:
    register_skill("status", "Report MAVLink connection and whether tracking is active", _status)
    register_skill(
        "vehicle_state",
        "Read lat/lon, local NED pose, altitude, and yaw from MAVLink telemetry streams",
        _vehicle_state,
        for_openai={
            "timeout": "Seconds to wait for telemetry (default 2)",
            "rate_hz": "Stream rate to request via MAV_CMD_SET_MESSAGE_INTERVAL (default 5)",
        },
        capability="vehicle_state",
    )
    register_skill(
        "help",
        "List direct commands (for humans, not needed for tool use)",
        _help,
        for_openai=False,
    )
