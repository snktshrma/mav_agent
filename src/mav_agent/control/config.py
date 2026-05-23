from __future__ import annotations

from dataclasses import dataclass, field

from mav_agent.control.protocol import FlightBackend
from mav_agent.defaults import (
    DEFAULT_BACKEND,
    DEFAULT_CONNECTION,
    DEFAULT_IMAGE_SOURCE,
    DEFAULT_ROS_IMAGE_TOPIC,
    DEFAULT_VIDEO_UDP_PORT,
)


@dataclass
class Ros2Topics:
    cmd_vel: str = "/ap/cmd_vel"
    cmd_gps_pose: str = "/ap/cmd_gps_pose"
    geopose: str = "/ap/geopose/filtered"
    arm_service: str = "/ap/arm_motors"
    mode_service: str = "/ap/mode_switch"
    takeoff_service: str = "/ap/experimental/takeoff"


@dataclass
class PerceptionConfig:
    source: str = DEFAULT_IMAGE_SOURCE
    ros_image_topic: str = DEFAULT_ROS_IMAGE_TOPIC
    video_udp_port: int | None = DEFAULT_VIDEO_UDP_PORT
    video_width: int = 640
    video_height: int = 360


@dataclass
class ControlConfig:
    backend: str = DEFAULT_BACKEND
    connection_string: str = DEFAULT_CONNECTION
    ros2: Ros2Topics = field(default_factory=Ros2Topics)
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)


def build_control(config: ControlConfig) -> FlightBackend:
    if config.backend == "mavlink":
        from mav_agent.control.mavlink_backend import MavlinkBackend

        return MavlinkBackend(config.connection_string)
    if config.backend == "ros2":
        from mav_agent.control.ros2_backend import Ros2Backend

        return Ros2Backend(config)
    raise ValueError(f"Unknown backend: {config.backend!r} (use mavlink or ros2)")


def resolve_perception_source(config: ControlConfig, rtsp_url: str | None) -> str:
    if config.backend == "ros2":
        return "ros"
    src = config.perception.source
    if src == "udp":
        if config.perception.video_udp_port is None:
            raise ValueError("udp requires --video-port")
        return "udp"
    if src == "rtsp":
        if not rtsp_url:
            raise ValueError("rtsp requires --rtsp URL or rtsp skill url=")
        return "rtsp"
    raise ValueError(
        "mavlink backend requires --image-source udp (with --video-port) or rtsp (with --rtsp)"
    )
