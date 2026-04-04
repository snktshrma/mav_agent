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
