from __future__ import annotations

import math

from mav_agent.control.protocol import FlightBackend
from mav_agent.defaults import DEFAULT_VELOCITY_DURATION_S
from mav_agent.session import DroneSession


def float_arg(args: dict[str, str], key: str, default: float | None = None) -> float | None:
    raw = args.get(key)
    if raw is None or raw == "":
        if default is not None:
            return default
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def bool_arg(args: dict[str, str], key: str, default: bool = True) -> bool:
    raw = (args.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def ensure_connected(session: DroneSession) -> tuple[FlightBackend, str | None]:
    c = session.get_control()
    if not c.is_connected:
        if not c.connect():
            return c, "Vehicle not connected. Run connect first."
    return c, None


def ensure_guided(c: FlightBackend) -> str | None:
    mode = c.get_flight_mode()
    if mode and mode.upper() == "GUIDED":
        return None
    if c.set_mode("GUIDED"):
        return None
    return "Failed to set GUIDED (required for arm, takeoff, and motion)."


def ensure_guided_armed(c: FlightBackend) -> str | None:
    guided_err = ensure_guided(c)
    if guided_err:
        return guided_err
    if not c.is_armed():
        return "Not armed. Run arm before velocity/position/yaw commands."
    return None


def parse_altitude(args: dict[str, str]) -> tuple[float | None, str | None]:
    alt_s = (args.get("altitude") or args.get("_positional") or "3").strip()
    try:
        return float(alt_s), None
    except ValueError:
        return None, "Invalid altitude (expected a number in meters)."


def query_from_args(args: dict[str, str], default: str) -> str:
    if args.get("query"):
        return args["query"]
    if args.get("q"):
        return args["q"]
    if args.get("_positional"):
        return args["_positional"]
    return default


def set_mode_skill(session: DroneSession, args: dict[str, str], mode: str, label: str) -> str:
    _ = args
    c, err = ensure_connected(session)
    if err:
        return err
    if c.set_mode(mode):
        return f"{label} mode requested."
    return f"{label} mode failed."


def motion_velocity_common(
    session: DroneSession,
    args: dict[str, str],
    *,
    require_duration: bool = False,
    use_trajectory: bool = False,
) -> str:
    if require_duration:
        duration = float_arg(args, "duration")
        if duration is None or duration <= 0:
            return "move_trajectory requires duration > 0 (seconds)."
    else:
        duration_raw = args.get("duration")
        if duration_raw is None or str(duration_raw).strip() == "":
            duration = DEFAULT_VELOCITY_DURATION_S
        else:
            duration = float_arg(args, "duration")
            if duration is None:
                return "Invalid duration for move_velocity."
            if duration < 0:
                return "duration must be >= 0 (0 = single setpoint, omit for default stream)."
    vx = float_arg(args, "vx", 0.0)
    vy = float_arg(args, "vy", 0.0)
    vz = float_arg(args, "vz", 0.0)
    yaw_rate = float_arg(args, "yaw_rate", 0.0)
    if vx is None or vy is None or vz is None or yaw_rate is None:
        label = "move_trajectory" if use_trajectory else "move_velocity"
        return f"Invalid numeric args for {label}."
    c, err = ensure_connected(session)
    if err:
        return err
    motion_err = ensure_guided_armed(c)
    if motion_err:
        return motion_err
    lock_alt = bool_arg(args, "lock_altitude", True)
    if use_trajectory:
        ok = c.move_trajectory(
            duration, vx, vy, vz, yaw_rate, lock_altitude=lock_alt
        )
        if ok:
            return (
                f"Trajectory stream complete ({duration}s at ~20Hz: "
                f"vx={vx}, vy={vy}, vz={vz}, yaw_rate={yaw_rate})."
            )
        return "move_trajectory failed."
    ok = c.move_velocity(
        vx, vy, vz, yaw_rate, duration, lock_altitude=lock_alt
    )
    if ok:
        return (
            f"Velocity setpoint sent (vx={vx}, vy={vy}, vz={vz}, yaw_rate={yaw_rate}, "
            f"duration={duration}s)."
        )
    return "move_velocity failed."


def set_yaw_from_args(session: DroneSession, args: dict[str, str]) -> str:
    yaw_deg = float_arg(args, "yaw_deg")
    yaw_rad = float_arg(args, "yaw_rad")
    duration = float_arg(args, "duration", 0.0)
    if duration is None:
        return "Invalid duration."
    if yaw_rad is None and yaw_deg is not None:
        yaw_rad = math.radians(yaw_deg)
    if yaw_rad is None:
        return "Provide yaw_deg or yaw_rad."
    c, err = ensure_connected(session)
    if err:
        return err
    motion_err = ensure_guided_armed(c)
    if motion_err:
        return motion_err
    if c.set_yaw(yaw_rad, duration):
        return f"Yaw target sent ({yaw_rad:.3f} rad, duration={duration}s)."
    return "set_yaw failed."
