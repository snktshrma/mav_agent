from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import numpy as np

from mav_agent.control.config import ControlConfig, build_control, resolve_perception_source
from mav_agent.control.protocol import FlightBackend
from mav_agent.defaults import DEFAULT_CONNECTION, DEFAULT_QWEN_MODEL, QWEN_API
from mav_agent.perception.source import FrameSource, build_frame_source
from mav_agent.tracker import FollowController

T = TypeVar("T")


@dataclass(frozen=True)
class VisionConfig:
    api_key: str | None
    model: str
    base_url: str | None
    qwen_api: str


class DroneSession:
    """One interactive session: settings, FlightBackend, and lazily created FollowController."""

    def __init__(
        self,
        connection_string: str = DEFAULT_CONNECTION,
        rtsp_url: str | None = None,
        qwen_model: str = DEFAULT_QWEN_MODEL,
        qwen_base_url: str | None = None,
        qwen_api: str = QWEN_API,
        api_key: str | None = None,
        *,
        control_config: ControlConfig | None = None,
    ) -> None:
        cfg = control_config or ControlConfig(connection_string=connection_string)
        self._config = cfg
        self._control: FlightBackend = build_control(cfg)
        self._rtsp_url = rtsp_url
        self._qwen_model = qwen_model
        self._qwen_base_url = qwen_base_url
        self._qwen_api = qwen_api
        self._api_key = api_key
        self._tracker: FollowController | None = None
        self._frame_source: FrameSource | None = None
        self._perception_kind: str | None = None
        self._video_started = False
        self._dispatch_lock = threading.Lock()

    def under_dispatch_lock(self, fn: Callable[[], T]) -> T:
        with self._dispatch_lock:
            return fn()

    def dispatch_skill(self, name: str, args: dict[str, str]) -> str:
        from mav_agent.skills.registry import dispatch

        with self._dispatch_lock:
            return dispatch(self, name, args)

    @property
    def config(self) -> ControlConfig:
        return self._config

    @property
    def vision_config(self) -> VisionConfig:
        return VisionConfig(
            api_key=self._api_key,
            model=self._qwen_model,
            base_url=self._qwen_base_url,
            qwen_api=self._qwen_api,
        )

    def mark_video_started(self) -> None:
        self._video_started = True

    def stop_video(self) -> None:
        self._video_started = False
        if self._frame_source is not None:
            self._frame_source.stop()
            self._frame_source = None

    def get_control(self) -> FlightBackend:
        return self._control

    def get_perception_kind(self) -> str:
        if self._perception_kind is None:
            self._perception_kind = resolve_perception_source(self._config, self._rtsp_url)
        return self._perception_kind

    def get_frame_source(self) -> FrameSource | None:
        kind = self.get_perception_kind()
        if kind == "rtsp" and not self._rtsp_url:
            return None
        if self._frame_source is None:
            self._frame_source = build_frame_source(
                kind,
                rtsp_url=self._rtsp_url,
                ros_topic=self._config.perception.ros_image_topic,
                video_udp_port=self._config.perception.video_udp_port,
                video_width=self._config.perception.video_width,
                video_height=self._config.perception.video_height,
            )
        return self._frame_source

    def start_video(self) -> bool:
        """Start the perception pipeline once (safe to call repeatedly)."""
        if self._video_started:
            return True
        try:
            fs = self.get_frame_source()
            if fs is None:
                return False
            if fs.start():
                self.mark_video_started()
                return True
        except ValueError:
            return False
        return False

    def get_frame(self) -> np.ndarray | None:
        if not self._video_started:
            return None
        fs = self.get_frame_source()
        if fs is None:
            return None
        return fs.get_frame()

    def get_tracker(self) -> FollowController:
        if self._tracker is None:
            vision = self.vision_config
            self._tracker = FollowController(
                control=self._control,
                get_frame=self.get_frame,
                session=self,
                qwen_model=vision.model,
                qwen_base_url=vision.base_url,
                qwen_api=vision.qwen_api,
                api_key=vision.api_key,
            )
        return self._tracker

    def set_rtsp_url(self, url: str | None) -> None:
        self._rtsp_url = url
        self._perception_kind = None
        self.stop_video()

    def capture_frame(self, timeout: float = 10.0) -> np.ndarray | None:
        """Grab one RGB frame from the configured video source (UDP / RTSP / ROS)."""
        if not self.start_video():
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.get_frame()
            if frame is not None:
                return frame
            time.sleep(0.05)
        return None

    def start_rtsp(self, url: str) -> str:
        self.set_rtsp_url(url)
        self._perception_kind = "rtsp"
        if self.start_video():
            return f"RTSP started: {url}"
        return "Failed to open RTSP stream"

    def close(self) -> None:
        self.stop_video()
        if self._tracker is not None:
            self._tracker.close()
            self._tracker = None
        self._control.close()
