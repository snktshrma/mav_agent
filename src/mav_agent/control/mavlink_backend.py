from __future__ import annotations

import time

from pymavlink import mavutil

from mav_agent.control.capabilities import MAVLINK_CAPABILITIES
from mav_agent.control.vehicle_state import VehicleState
from mav_agent.defaults import (
    DEFAULT_CONNECTION,
    DEFAULT_TELEMETRY_HZ,
    POST_ARM_DELAY_S,
    TAKEOFF_ALT_TOLERANCE_M,
    TAKEOFF_ALT_WAIT_TIMEOUT_S,
)

MASK_USE_POSITION = 0b0000110111111000
MASK_USE_VELOCITY = 0b0000110111000111
MASK_USE_YAW = 0b0000100111000111
MASK_USE_VEL_YAW_RATE = 0b0000011111000111

FRAME_BODY_NED = mavutil.mavlink.MAV_FRAME_BODY_NED
FRAME_BODY_OFFSET = mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED

COPTER_MODE_NUMBERS: dict[str, int] = {
    "STABILIZE": 0,
    "ACRO": 1,
    "ALT_HOLD": 2,
    "AUTO": 3,
    "GUIDED": 4,
    "LOITER": 5,
    "RTL": 6,
    "CIRCLE": 7,
    "LAND": 9,
    "BRAKE": 17,
}

COPTER_MODE_BY_NUMBER = {v: k for k, v in COPTER_MODE_NUMBERS.items()}

STREAM_HZ = 20.0

MAV_CMD_SET_MESSAGE_INTERVAL = 511
MSG_LOCAL_POSITION_NED = 32
MSG_GLOBAL_POSITION_INT = 33
MSG_ATTITUDE = 30
TELEMETRY_MESSAGE_IDS = (MSG_GLOBAL_POSITION_INT, MSG_LOCAL_POSITION_NED, MSG_ATTITUDE)

_MODE_ALIASES = {
    "ALTHOLD": "ALT_HOLD",
}


class MavlinkBackend:
    """Direct pymavlink FlightBackend for ArduPilot Copter GUIDED control."""

    def __init__(self, connection_string: str = DEFAULT_CONNECTION) -> None:
        self.connection_string = connection_string
        self.mavlink = None
        self.connected = False
        self._telemetry_stream_hz: float | None = None

    @property
    def backend_name(self) -> str:
        return "mavlink"

    @property
    def capabilities(self) -> frozenset[str]:
        return MAVLINK_CAPABILITIES

    @property
    def is_connected(self) -> bool:
        return self.connected

    def connect(self, heartbeat_timeout: float = 30.0) -> bool:
        try:
            self.mavlink = mavutil.mavlink_connection(self.connection_string)
            self.mavlink.wait_heartbeat(timeout=heartbeat_timeout)
            self.connected = True
            self.ensure_telemetry_streams()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.stop_motion()
        self._telemetry_stream_hz = None

    def set_message_interval(self, message_id: int, rate_hz: float) -> bool:
        """Request MAVLink message rate via MAV_CMD_SET_MESSAGE_INTERVAL (ArduPilot 4.0+)."""
        if not self.connected or self.mavlink is None:
            return False
        if rate_hz <= 0:
            interval_us = -1
        else:
            interval_us = int(1_000_000 / rate_hz)
        self.mavlink.mav.command_long_send(
            self.mavlink.target_system,
            self.mavlink.target_component,
            MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            float(message_id),
            float(interval_us),
            0,
            0,
            0,
            0,
            0,
        )
        ack = self.mavlink.recv_match(type="COMMAND_ACK", blocking=True, timeout=2)
        if ack is None:
            return False
        if ack.command != MAV_CMD_SET_MESSAGE_INTERVAL:
            return False
        return ack.result in (
            mavutil.mavlink.MAV_RESULT_ACCEPTED,
            mavutil.mavlink.MAV_RESULT_IN_PROGRESS,
        )

    def ensure_telemetry_streams(self, rate_hz: float = DEFAULT_TELEMETRY_HZ) -> bool:
        """Stream GLOBAL_POSITION_INT, LOCAL_POSITION_NED, and ATTITUDE from the autopilot."""
        if self._telemetry_stream_hz == rate_hz:
            return True
        ok = all(self.set_message_interval(msg_id, rate_hz) for msg_id in TELEMETRY_MESSAGE_IDS)
        if ok:
            self._telemetry_stream_hz = rate_hz
        return ok

    def get_vehicle_state(
        self,
        timeout: float = 2.0,
        *,
        rate_hz: float = DEFAULT_TELEMETRY_HZ,
        ensure_streams: bool = True,
    ) -> VehicleState | None:
        """Read lat/lon, local NED pose, altitude, and yaw from streamed MAVLink messages."""
        if not self.connected or self.mavlink is None:
            return None
        if ensure_streams:
            self.ensure_telemetry_streams(rate_hz=rate_hz)
        state = VehicleState()
        deadline = time.time() + timeout
        need_global = True
        need_local = True
        need_yaw = True
        while time.time() < deadline and (need_global or need_local or need_yaw):
            msg = self.mavlink.recv_match(blocking=True, timeout=0.25)
            if msg is None:
                continue
            mtype = msg.get_type()
            if mtype == "GLOBAL_POSITION_INT":
                state.merge_global_position_int(msg)
                need_global = False
                if state.yaw_deg is not None:
                    need_yaw = False
            elif mtype == "LOCAL_POSITION_NED":
                state.merge_local_position_ned(msg)
                need_local = False
            elif mtype == "ATTITUDE":
                state.merge_attitude_yaw(msg.yaw)
                need_yaw = False
        return state if state.has_data else None

    def _wait_takeoff_altitude(
        self, target_alt: float, timeout: float = TAKEOFF_ALT_WAIT_TIMEOUT_S
    ) -> bool:
        min_alt = max(0.2, target_alt - TAKEOFF_ALT_TOLERANCE_M)
        deadline = time.time() + timeout
        self.ensure_telemetry_streams()
        while time.time() < deadline:
            state = self.get_vehicle_state(timeout=0.5, ensure_streams=False)
            if state is not None and state.alt_rel_m is not None and state.alt_rel_m >= min_alt:
                return True
            time.sleep(0.2)
        return False

    def send_position_target_local_ned(
        self,
        *,
        frame_id: int,
        type_mask: int,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        vx: float = 0.0,
        vy: float = 0.0,
        vz: float = 0.0,
        yaw: float = 0.0,
        yaw_rate: float = 0.0,
    ) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        self.mavlink.mav.set_position_target_local_ned_send(
            0,
            self.mavlink.target_system,
            self.mavlink.target_component,
            frame_id,
            type_mask,
            x,
            y,
            z,
            vx,
            vy,
            vz,
            0,
            0,
            0,
            yaw,
            yaw_rate,
        )
        return True

    def _stream_setpoint(
        self,
        send_once,
        duration: float,
        rate_hz: float = STREAM_HZ,
    ) -> bool:
        if duration <= 0:
            return send_once()
        end = time.time() + duration
        interval = 1.0 / rate_hz
        while time.time() < end:
            if not send_once():
                return False
            time.sleep(interval)
        return True

    def move_velocity(
        self,
        vx: float,
        vy: float,
        vz: float = 0.0,
        yaw_rate: float = 0.0,
        duration: float = 0.0,
        *,
        lock_altitude: bool = True,
    ) -> bool:
        down = 0.0 if lock_altitude else vz
        type_mask = MASK_USE_VEL_YAW_RATE

        def send():
            return self.send_position_target_local_ned(
                frame_id=FRAME_BODY_NED,
                type_mask=type_mask,
                vx=vx,
                vy=vy,
                vz=down,
                yaw_rate=yaw_rate,
            )

        ok = self._stream_setpoint(send, duration)
        if duration > 0:
            self.stop_motion()
        return ok

    def move_to_position(
        self,
        x: float,
        y: float,
        z: float,
        duration: float = 0.0,
    ) -> bool:
        _ = duration
        return self.send_position_target_local_ned(
            frame_id=FRAME_BODY_OFFSET,
            type_mask=MASK_USE_POSITION,
            x=x,
            y=y,
            z=-z,
        )
   
    def set_yaw(self, yaw_rad: float, duration: float = 0.0) -> bool:
        def send():
            return self.send_position_target_local_ned(
                frame_id=FRAME_BODY_OFFSET,
                type_mask=MASK_USE_YAW,
                x=0.0,
                y=0.0,
                z=0.0,
                vx=0.0,
                vy=0.0,
                vz=0.0,
                yaw=yaw_rad,
                yaw_rate=0.0,
            )

        return self._stream_setpoint(send, duration)

    def set_yaw_rate(self, yaw_rate: float, duration: float = 0.0) -> bool:
        def send():
            return self.send_position_target_local_ned(
                frame_id=FRAME_BODY_NED,
                type_mask=MASK_USE_VEL_YAW_RATE,
                yaw_rate=yaw_rate,
            )

        ok = self._stream_setpoint(send, duration)
        if duration > 0:
            self.stop_motion()
        return ok

    def move_trajectory(
        self,
        duration: float,
        vx: float = 0.0,
        vy: float = 0.0,
        vz: float = 0.0,
        yaw_rate: float = 0.0,
        *,
        lock_altitude: bool = True,
    ) -> bool:
        """Stream velocity setpoints for a timed segment (ArduPilot GUIDED)."""
        if duration <= 0:
            return False
        return self.move_velocity(
            vx,
            vy,
            vz,
            yaw_rate,
            duration,
            lock_altitude=lock_altitude,
        )

    def stop_motion(self) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        return self.send_position_target_local_ned(
            frame_id=FRAME_BODY_NED,
            type_mask=MASK_USE_VELOCITY,
        )

    def set_mode(self, mode: str) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        key = mode.strip().upper().replace("-", "_")
        key = _MODE_ALIASES.get(key, key)
        if key not in COPTER_MODE_NUMBERS:
            return False
        self.mavlink.mav.command_long_send(
            self.mavlink.target_system,
            self.mavlink.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            COPTER_MODE_NUMBERS[key],
            0,
            0,
            0,
            0,
            0,
        )
        time.sleep(0.3)
        return True

    def get_flight_mode(self) -> str | None:
        if not self.connected or self.mavlink is None:
            return None
        msg = self.mavlink.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
        if msg is None:
            return None
        return COPTER_MODE_BY_NUMBER.get(msg.custom_mode, f"MODE_{msg.custom_mode}")

    def is_armed(self) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        msg = self.mavlink.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
        if msg is None:
            return False
        return bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

    def _send_arm_disarm(self, arm: bool) -> bool:
        assert self.mavlink is not None
        self.mavlink.mav.command_long_send(
            self.mavlink.target_system,
            self.mavlink.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1 if arm else 0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        ack = self.mavlink.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
        if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            return ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED
        return False

    def _wait_armed(self, timeout_s: float = 3.0, *, armed: bool = True) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_armed() == armed:
                return True
            time.sleep(0.2)
        return False

    def disarm(self) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        if not self.is_armed():
            return True
        if not self._send_arm_disarm(False):
            return False
        return self._wait_armed(timeout_s=3.0, armed=False)

    def arm(self, *, set_guided: bool = True) -> bool:
        _ = set_guided
        if not self.connected or self.mavlink is None:
            return False
        if not self.set_mode("GUIDED"):
            return False
        if self.is_armed():
            return True
        if not self._send_arm_disarm(True):
            return False
        if not self._wait_armed(timeout_s=3.0, armed=True):
            return False
        time.sleep(POST_ARM_DELAY_S)
        return True

    def _send_takeoff(self, altitude: float) -> bool:
        assert self.mavlink is not None
        self.mavlink.mav.command_long_send(
            self.mavlink.target_system,
            self.mavlink.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            altitude,
        )
        ack = self.mavlink.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
        if ack and ack.command == mavutil.mavlink.MAV_CMD_NAV_TAKEOFF:
            return ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED
        return True

    def takeoff(self, altitude: float = 3.0) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        if not self.set_mode("GUIDED"):
            return False
        if not self.is_armed():
            return False
        if not self._send_takeoff(altitude):
            return False
        return self._wait_takeoff_altitude(altitude)

    def arm_and_takeoff(self, altitude: float = 3.0) -> bool:
        if not self.arm():
            return False
        if not self._send_takeoff(altitude):
            return False
        return self._wait_takeoff_altitude(altitude)

    def get_parameter(self, name: str, timeout: float = 5.0) -> float | None:
        if not self.connected or self.mavlink is None:
            return None
        try:
            return self.mavlink.param_fetch_one(name, timeout=timeout)
        except Exception:
            return None

    def set_parameter(self, name: str, value: float) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        try:
            self.mavlink.param_set(name, value)
            return True
        except Exception:
            return False


MavlinkConnection = MavlinkBackend
