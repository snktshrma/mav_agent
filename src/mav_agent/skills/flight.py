from __future__ import annotations

from mav_agent.defaults import TAKEOFF_ALT_TOLERANCE_M
from mav_agent.session import DroneSession
from mav_agent.skills.helpers import (
    bool_arg,
    ensure_connected,
    ensure_guided,
    ensure_guided_armed,
    float_arg,
    motion_velocity_common,
    parse_altitude,
    set_mode_skill,
    set_yaw_from_args,
)
from mav_agent.skills.registry import register_skill


def _connect(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    c = session.get_control()
    if c.connect():
        return f"{c.backend_name} connected."
    return f"{c.backend_name} connection failed."


def _arm(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    c, err = ensure_connected(session)
    if err:
        return err
    if c.arm():
        return "GUIDED mode set and motors armed."
    return "Arm failed (check prearm, mode, or SITL state)."


def _takeoff(session: DroneSession, args: dict[str, str]) -> str:
    altitude, err = parse_altitude(args)
    if err:
        return err
    assert altitude is not None
    c, conn_err = ensure_connected(session)
    if conn_err:
        return conn_err
    guided_err = ensure_guided(c)
    if guided_err:
        return guided_err
    if not c.is_armed():
        return "Not armed. Run arm first, or use arm_takeoff."
    if c.takeoff(altitude=altitude):
        return (
            f"Takeoff to {altitude} m complete "
            f"(within {TAKEOFF_ALT_TOLERANCE_M:.0f} m of target)."
        )
    return "Takeoff failed (GUIDED, climb wait, or command rejected)."


def _arm_takeoff(session: DroneSession, args: dict[str, str]) -> str:
    altitude, err = parse_altitude(args)
    if err:
        return err
    assert altitude is not None
    c, conn_err = ensure_connected(session)
    if conn_err:
        return conn_err
    if c.arm_and_takeoff(altitude=altitude):
        return (
            f"GUIDED, armed, and climbed to ~{altitude} m "
            f"(within {TAKEOFF_ALT_TOLERANCE_M:.0f} m of target)."
        )
    return "arm_takeoff failed (GUIDED, arm delay, prearm, or climb wait)."


def _disarm(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    c, err = ensure_connected(session)
    if err:
        return err
    if c.disarm():
        return "Disarm command sent."
    return "Disarm failed."


def _set_mode(session: DroneSession, args: dict[str, str]) -> str:
    mode = (args.get("mode") or args.get("_positional") or "").strip()
    if not mode:
        return "Usage: set_mode mode=GUIDED|LAND|RTL|LOITER|STABILIZE|AUTO|ALT_HOLD|..."
    c, err = ensure_connected(session)
    if err:
        return err
    if c.set_mode(mode):
        return f"Mode set to {mode.upper()}."
    return f"set_mode failed for {mode}."


def _move_to_position(session: DroneSession, args: dict[str, str]) -> str:
    x = float_arg(args, "x")
    y = float_arg(args, "y")
    z = float_arg(args, "z", 0.0)
    if x is None or y is None or z is None:
        return "Usage: move_to_position x=<m> y=<m> z=<m> (BODY_OFFSET NED: forward/right/down)."
    c, err = ensure_connected(session)
    if err:
        return err
    motion_err = ensure_guided_armed(c)
    if motion_err:
        return motion_err
    if c.move_to_position(x, y, z):
        return f"Position target sent once (x={x}, y={y}, z={z})."
    return "move_to_position failed."


def _set_yaw_rate(session: DroneSession, args: dict[str, str]) -> str:
    yaw_rate = float_arg(args, "yaw_rate")
    duration = float_arg(args, "duration", 0.0)
    if yaw_rate is None or duration is None:
        return "Usage: set_yaw_rate yaw_rate=<rad/s> [duration]."
    c, err = ensure_connected(session)
    if err:
        return err
    motion_err = ensure_guided_armed(c)
    if motion_err:
        return motion_err
    if c.set_yaw_rate(yaw_rate, duration):
        return f"Yaw rate setpoint sent ({yaw_rate} rad/s, duration={duration}s)."
    return "set_yaw_rate failed."


def _stop_motion(session: DroneSession, args: dict[str, str]) -> str:
    _ = args
    c, err = ensure_connected(session)
    if err:
        return err
    if c.stop_motion():
        return "Zero velocity setpoint sent (does not stop visual follow)."
    return "stop_motion failed."


def _get_param(session: DroneSession, args: dict[str, str]) -> str:
    name = (args.get("name") or args.get("_positional") or "").strip()
    if not name:
        return "Usage: get_param name=<PARAM_NAME>"
    c, err = ensure_connected(session)
    if err:
        return err
    val = c.get_parameter(name)
    if val is None:
        return f"Could not read parameter {name}."
    return f"{name} = {val}"


def _set_param(session: DroneSession, args: dict[str, str]) -> str:
    name = (args.get("name") or "").strip()
    value = float_arg(args, "value")
    if not name:
        name = (args.get("_positional") or "").strip()
    if value is None and args.get("_positional") and not args.get("name"):
        parts = args["_positional"].split()
        if len(parts) >= 2:
            name = parts[0]
            try:
                value = float(parts[1])
            except ValueError:
                return "Usage: set_param name=<PARAM> value=<number>"
    if not name or value is None:
        return "Usage: set_param name=<PARAM> value=<number>"
    c, err = ensure_connected(session)
    if err:
        return err
    if c.set_parameter(name, value):
        return f"Set {name} = {value} (verify with get_param)."
    return f"set_param failed for {name}."


def register_flight_skills() -> None:
    register_skill(
        "connect",
        "Connect vehicle (mavlink or ros2 backend per --backend)",
        _connect,
        capability="connect",
    )
    register_skill(
        "arm",
        "Set GUIDED mode then arm motors. Does not take off. Does not require RTSP.",
        _arm,
        capability="arm",
    )
    register_skill(
        "takeoff",
        "Take off to altitude in meters. Requires already armed; call arm first.",
        _takeoff,
        for_openai={"altitude": "Target altitude in meters (default 3)"},
        capability="takeoff",
    )
    register_skill(
        "arm_takeoff",
        "GUIDED + arm + takeoff; blocks until climb is within 1 m of target (use for multi-step missions)",
        _arm_takeoff,
        for_openai={"altitude": "Target altitude in meters (default 3)"},
        capability="arm_takeoff",
    )
    register_skill("disarm", "Disarm motors (when safe)", _disarm, capability="disarm")
    register_skill(
        "set_mode",
        "Set Copter flight mode (GUIDED, LAND, RTL, LOITER, STABILIZE, AUTO, ALT_HOLD, ...)",
        _set_mode,
        for_openai={"mode": "Mode name, e.g. GUIDED or LAND"},
        capability="set_mode",
    )
    register_skill(
        "land",
        "Switch to LAND mode",
        lambda session, args: set_mode_skill(session, args, "LAND", "LAND"),
        capability="land",
    )
    register_skill(
        "rtl",
        "Switch to RTL (return to launch)",
        lambda session, args: set_mode_skill(session, args, "RTL", "RTL"),
        capability="rtl",
    )
    register_skill(
        "loiter",
        "Switch to LOITER mode",
        lambda session, args: set_mode_skill(session, args, "LOITER", "LOITER"),
        capability="loiter",
    )
    register_skill(
        "move_velocity",
        "Stream SET_POSITION_TARGET_LOCAL_NED velocity in BODY_NED (m/s). Requires GUIDED and armed. "
        "Default 5s stream if duration omitted.",
        motion_velocity_common,
        for_openai={
            "vx": "Forward m/s (body frame)",
            "vy": "Right m/s",
            "vz": "Down m/s (ignored if lock_altitude=true)",
            "yaw_rate": "Yaw rate rad/s",
            "duration": "Seconds to stream setpoint (~20Hz); omit for 5s default; 0 = one shot",
            "lock_altitude": "true/false, default true",
        },
        capability="move_velocity",
    )
    register_skill(
        "move_to_position",
        "Fly to offset position via SET_POSITION_TARGET_LOCAL_NED (single setpoint; default BODY_OFFSET: x fwd, y right, z down m).",
        _move_to_position,
        for_openai={
            "x": "Forward offset meters",
            "y": "Right offset meters",
            "z": "Down offset meters",
        },
        capability="move_to_position",
    )
    register_skill(
        "set_yaw",
        "Set target yaw via SET_POSITION_TARGET (GUIDED). Use yaw_deg or yaw_rad.",
        set_yaw_from_args,
        for_openai={
            "yaw_deg": "Target heading degrees",
            "yaw_rad": "Target heading radians",
            "duration": "Seconds to stream (0 = once)",
        },
        capability="set_yaw",
    )
    register_skill(
        "set_yaw_rate",
        "Set yaw rate via SET_POSITION_TARGET (rad/s).",
        _set_yaw_rate,
        for_openai={
            "yaw_rate": "Yaw rate rad/s",
            "duration": "Seconds to stream",
        },
        capability="set_yaw_rate",
    )
    register_skill(
        "move_trajectory",
        "Stream velocity setpoints for duration seconds (~20Hz). Timed GUIDED segment.",
        lambda session, args: motion_velocity_common(
            session, args, require_duration=True, use_trajectory=True
        ),
        for_openai={
            "duration": "Seconds (required, > 0)",
            "vx": "Forward m/s",
            "vy": "Right m/s",
            "vz": "Down m/s",
            "yaw_rate": "Yaw rate rad/s",
            "lock_altitude": "true/false",
        },
        capability="move_trajectory",
    )
    register_skill(
        "stop_motion",
        "Send zero velocity setpoint; does not stop visual follow (use stop for tracking)",
        _stop_motion,
        capability="stop_motion",
    )
    register_skill(
        "get_param",
        "Read an ArduPilot parameter by name",
        _get_param,
        for_openai={"name": "Parameter name e.g. WPNAV_SPEED"},
        capability="get_param",
    )
    register_skill(
        "set_param",
        "Set an ArduPilot parameter (use with care)",
        _set_param,
        for_openai={
            "name": "Parameter name",
            "value": "Numeric value",
        },
        capability="set_param",
    )
