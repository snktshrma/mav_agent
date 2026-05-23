from __future__ import annotations

import time
from typing import TYPE_CHECKING

from mav_agent.control.capabilities import ROS2_CAPABILITIES
from mav_agent.control.config import ControlConfig
from mav_agent.control.mavlink_backend import (
    COPTER_MODE_BY_NUMBER,
    COPTER_MODE_NUMBERS,
    STREAM_HZ,
)
from mav_agent.perception.ros_context import ROSContext

if TYPE_CHECKING:
    from rclpy.node import Node


class Ros2Backend:
    backend_name = "ros2"

    @property
    def capabilities(self) -> frozenset[str]:
        return ROS2_CAPABILITIES

    def __init__(self, config: ControlConfig) -> None:
        self._config = config
        self._topics = config.ros2
        self._ctx = ROSContext.shared()
        self._node: Node | None = None
        self._connected = False
        self._armed: bool | None = None
        self._mode_name: str | None = None
        self._TwistStamped = None
        self._ArmMotors = None
        self._ModeSwitch = None
        self._Takeoff = None
        self._cmd_vel_pub = None
        self._arm_client = None
        self._mode_client = None
        self._takeoff_client = None

    def _import_ros(self) -> None:
        if self._TwistStamped is not None:
            return
        try:
            from ardupilot_msgs.srv import ArmMotors, ModeSwitch, Takeoff
            from geometry_msgs.msg import TwistStamped
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        except ImportError as e:
            raise ImportError(
                "ROS2 backend requires sourced ROS Humble workspace with ardupilot_msgs "
                'and pip install -e ".[ros]"'
            ) from e
        self._TwistStamped = TwistStamped
        self._ArmMotors = ArmMotors
        self._ModeSwitch = ModeSwitch
        self._Takeoff = Takeoff
        self._qos_vel = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth=1,
        )

    def _ensure_node(self) -> Node:
        self._import_ros()
        if self._node is None:
            self._node = self._ctx.create_node("mav_agent_control")
            self._cmd_vel_pub = self._node.create_publisher(
                self._TwistStamped, self._topics.cmd_vel, self._qos_vel
            )
            self._arm_client = self._node.create_client(
                self._ArmMotors, self._topics.arm_service
            )
            self._mode_client = self._node.create_client(
                self._ModeSwitch, self._topics.mode_service
            )
            self._takeoff_client = self._node.create_client(
                self._Takeoff, self._topics.takeoff_service
            )
        return self._node

    def armed_state(self) -> bool | None:
        """Armed tri-state for ROS2: None until a successful arm/disarm service call."""
        return self._armed

    def _spin_future(self, future, timeout_sec: float) -> bool:
        self._ensure_node()
        return self._ctx.spin_until_future_complete(future, timeout_sec)

    def connect(self, heartbeat_timeout: float = 30.0) -> bool:
        try:
            self._ensure_node()
        except ImportError:
            return False
        deadline = time.time() + heartbeat_timeout
        while time.time() < deadline:
            if self._arm_client.service_is_ready():
                self._connected = True
                return True
            time.sleep(0.2)
            self._ctx.spin_once(timeout_sec=0.1)
        return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self.stop_motion()
        if self._node is not None:
            self._ctx.remove_node(self._node)
            self._node = None
            self._cmd_vel_pub = None
            self._arm_client = None
            self._mode_client = None
            self._takeoff_client = None
        self._connected = False

    def set_mode(self, mode: str) -> bool:
        key = mode.strip().upper().replace("-", "_")
        num = COPTER_MODE_NUMBERS.get(key)
        if num is None:
            return False
        self._ensure_node()
        req = self._ModeSwitch.Request()
        req.mode = num
        future = self._mode_client.call_async(req)
        if not self._spin_future(future, 5.0):
            return False
        result = future.result()
        if result is None:
            return False
        self._mode_name = COPTER_MODE_BY_NUMBER.get(int(result.curr_mode))
        return bool(result.status)

    def arm(self, *, set_guided: bool = True) -> bool:
        _ = set_guided
        if not self.set_mode("GUIDED"):
            return False
        self._ensure_node()
        req = self._ArmMotors.Request()
        req.arm = True
        future = self._arm_client.call_async(req)
        if not self._spin_future(future, 5.0):
            return False
        result = future.result()
        if result and result.result:
            self._armed = True
            return True
        return False

    def disarm(self) -> bool:
        self._ensure_node()
        req = self._ArmMotors.Request()
        req.arm = False
        future = self._arm_client.call_async(req)
        if not self._spin_future(future, 5.0):
            return False
        result = future.result()
        if result and result.result:
            self._armed = False
            return True
        return False

    def is_armed(self) -> bool:
        return self._armed is True

    def get_flight_mode(self) -> str | None:
        return self._mode_name

    def takeoff(self, altitude: float = 3.0) -> bool:
        if self._armed is not True:
            return False
        if not self.set_mode("GUIDED"):
            return False
        self._ensure_node()
        req = self._Takeoff.Request()
        req.alt = float(altitude)
        future = self._takeoff_client.call_async(req)
        if not self._spin_future(future, 10.0):
            return False
        result = future.result()
        return bool(result and result.status)

    def arm_and_takeoff(self, altitude: float = 3.0) -> bool:
        if not self.arm():
            return False
        return self.takeoff(altitude)

    def _publish_cmd_vel(
        self,
        vx: float,
        vy: float,
        vz: float,
        yaw_rate: float,
        frame_id: str = "base_link",
    ) -> None:
        msg = self._TwistStamped()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.header.frame_id = frame_id
        msg.twist.linear.x = float(vx)
        msg.twist.linear.y = float(vy)
        msg.twist.linear.z = float(vz)
        msg.twist.angular.z = float(yaw_rate)
        self._cmd_vel_pub.publish(msg)
        self._ctx.spin_once(timeout_sec=0)

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
        if not self._connected:
            return False
        self._ensure_node()
        down = 0.0 if lock_altitude else vz

        def send_once() -> None:
            self._publish_cmd_vel(vx, vy, down, yaw_rate, frame_id="base_link")

        if duration <= 0:
            send_once()
            return True
        end = time.time() + duration
        interval = 1.0 / STREAM_HZ
        while time.time() < end:
            send_once()
            time.sleep(interval)
        self.stop_motion()
        return True

    def move_to_position(
        self,
        x: float,
        y: float,
        z: float,
        duration: float = 0.0,
    ) -> bool:
        _ = x, y, z, duration
        return False

    def set_yaw(self, yaw_rad: float, duration: float = 0.0) -> bool:
        _ = yaw_rad, duration
        return False

    def set_yaw_rate(self, yaw_rate: float, duration: float = 0.0) -> bool:
        return self.move_velocity(0, 0, 0, yaw_rate, duration, lock_altitude=True)

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
        if duration <= 0:
            return False
        return self.move_velocity(
            vx, vy, vz, yaw_rate, duration, lock_altitude=lock_altitude
        )

    def stop_motion(self) -> bool:
        if not self._connected or self._node is None:
            return False
        self._publish_cmd_vel(0, 0, 0, 0)
        return True

    def get_parameter(self, name: str, timeout: float = 5.0) -> float | None:
        _ = name, timeout
        return None

    def set_parameter(self, name: str, value: float) -> bool:
        _ = name, value
        return False
