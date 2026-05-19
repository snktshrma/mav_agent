import time

from pymavlink import mavutil


class Twist:
    def __init__(self, vx=0.0, vy=0.0, vz=0.0, yaw_rate=0.0):
        self.vx = vx
        self.vy = vy
        self.vz = vz
        self.yaw_rate = yaw_rate


class MavlinkConnection:
    def __init__(self, connection_string="udp:0.0.0.0:14550"):
        self.connection_string = connection_string
        self.mavlink = None
        self.connected = False

    def connect(self, heartbeat_timeout=30.0):
        try:
            self.mavlink = mavutil.mavlink_connection(self.connection_string)
            self.mavlink.wait_heartbeat(timeout=heartbeat_timeout)
            self.connected = True
            return True
        except Exception:
            return False

    def move_twist(self, twist, duration=0.0, lock_altitude=True):
        if not self.connected or self.mavlink is None:
            return False
        forward = twist.vx
        right = twist.vy
        down = 0.0 if lock_altitude else twist.vz
        yaw_rate = twist.yaw_rate
        mask_vel = 0b0000111111000111
        mask_use_yaw_rate = mask_vel & ~mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
        if duration > 0:
            end_time = time.time() + duration
            while time.time() < end_time:
                self.mavlink.mav.set_position_target_local_ned_send(
                    0,
                    self.mavlink.target_system,
                    self.mavlink.target_component,
                    mavutil.mavlink.MAV_FRAME_BODY_NED,
                    mask_use_yaw_rate,
                    0,
                    0,
                    0,
                    forward,
                    right,
                    down,
                    0,
                    0,
                    0,
                    0,
                    yaw_rate,
                )
                time.sleep(0.05)
            self.stop()
        else:
            self.mavlink.mav.set_position_target_local_ned_send(
                0,
                self.mavlink.target_system,
                self.mavlink.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_NED,
                mask_use_yaw_rate,
                0,
                0,
                0,
                forward,
                right,
                down,
                0,
                0,
                0,
                0,
                yaw_rate,
            )
        return True

    def set_mode(self, mode: str) -> bool:
        if not self.connected or self.mavlink is None:
            return False
        mode_mapping = {
            "STABILIZE": 0,
            "GUIDED": 4,
            "LOITER": 5,
            "RTL": 6,
            "LAND": 9,
        }
        if mode not in mode_mapping:
            return False
        self.mavlink.mav.command_long_send(
            self.mavlink.target_system,
            self.mavlink.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_mapping[mode],
            0,
            0,
            0,
            0,
            0,
        )
        time.sleep(0.3)
        return True

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

    def _wait_armed(self, timeout_s: float = 3.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_armed():
                return True
            time.sleep(0.2)
        return False

    def arm(self, *, set_guided: bool = True) -> bool:
        """Set GUIDED (optional), then arm. Does not take off."""
        if not self.connected or self.mavlink is None:
            return False
        if set_guided and not self.set_mode("GUIDED"):
            return False
        if self.is_armed():
            return True
        if not self._send_arm_disarm(True):
            return False
        return self._wait_armed(timeout_s=3.0)

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
        """Take off only if already armed. Does not change mode or arm."""
        if not self.connected or self.mavlink is None:
            return False
        if not self.is_armed():
            return False
        return self._send_takeoff(altitude)

    def arm_and_takeoff(self, altitude: float = 3.0) -> bool:
        """GUIDED -> arm -> takeoff in order."""
        if not self.connected or self.mavlink is None:
            return False
        if not self.set_mode("GUIDED"):
            return False
        if not self.is_armed():
            if not self._send_arm_disarm(True):
                return False
            if not self._wait_armed(timeout_s=3.0):
                return False
        return self._send_takeoff(altitude)

    def stop(self):
        if not self.connected or self.mavlink is None:
            return False
        self.mavlink.mav.set_position_target_local_ned_send(
            0,
            self.mavlink.target_system,
            self.mavlink.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_NED,
            0b0000111111000111,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        return True
