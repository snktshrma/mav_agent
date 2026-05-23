from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from mav_agent.perception.udp import UdpVideoStream
from mav_agent.perception.rtsp import RTSPStream


class FrameSource(Protocol):
    def start(self) -> bool: ...

    def stop(self) -> None: ...

    def get_frame(self) -> np.ndarray | None: ...


class RtspFrameSource:
    def __init__(self, url: str) -> None:
        self._url = url
        self._stream: RTSPStream | None = None

    def start(self) -> bool:
        if self._stream is not None and self._stream._thread is not None and self._stream._thread.is_alive():
            return True
        self.stop()
        self._stream = RTSPStream(self._url)
        return self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream = None

    def get_frame(self) -> np.ndarray | None:
        if self._stream is None:
            return None
        return self._stream.get_frame()


class RosFrameSource:
    def __init__(self, topic: str) -> None:
        self._topic = topic
        self._latest: np.ndarray | None = None
        self._lock = threading.Lock()
        self._node = None
        self._subscription = None
        self._ctx = None

    def _on_image(self, msg) -> None:
        rgb = _sensor_image_to_rgb(msg)
        if rgb is not None:
            with self._lock:
                self._latest = rgb

    def start(self) -> bool:
        try:
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from sensor_msgs.msg import Image
        except ImportError as e:
            raise ImportError(
                "ROS image source requires rclpy and sensor_msgs (source ROS + pip install -e '.[ros]')"
            ) from e

        from mav_agent.perception.ros_context import ROSContext

        self._ctx = ROSContext.shared()
        self._node = self._ctx.create_node("mav_agent_perception")
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth=1,
        )
        self._subscription = self._node.create_subscription(
            Image, self._topic, self._on_image, qos
        )
        return True

    def stop(self) -> None:
        if self._node is not None and self._ctx is not None:
            self._ctx.remove_node(self._node)
            self._node = None
            self._ctx = None
        self._subscription = None
        with self._lock:
            self._latest = None

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest is None:
                return None
            return self._latest.copy()


def _sensor_image_to_rgb(msg) -> np.ndarray | None:
    h, w = msg.height, msg.width
    enc = (msg.encoding or "").lower()
    data = np.frombuffer(msg.data, dtype=np.uint8)
    if enc in ("rgb8",):
        return data.reshape((h, w, 3))
    if enc in ("bgr8",):
        bgr = data.reshape((h, w, 3))
        return bgr[:, :, ::-1].copy()
    if enc in ("mono8",):
        gray = data.reshape((h, w))
        return np.stack([gray, gray, gray], axis=-1)
    return None


def build_frame_source(
    kind: str,
    *,
    rtsp_url: str | None,
    ros_topic: str,
    video_udp_port: int | None = None,
    video_width: int = 640,
    video_height: int = 360,
) -> FrameSource:
    if kind == "udp":
        if video_udp_port is None:
            raise ValueError("udp requires --video-port")
        return UdpVideoStream(
            port=video_udp_port, width=video_width, height=video_height
        )
    if kind == "rtsp":
        if not rtsp_url:
            raise ValueError("RTSP source requires --rtsp or rtsp skill url=")
        return RtspFrameSource(rtsp_url)
    if kind == "ros":
        return RosFrameSource(ros_topic)
    raise ValueError(f"Unknown frame source kind: {kind}")
