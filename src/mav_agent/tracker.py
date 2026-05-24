from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import cv2
import numpy as np

from mav_agent.control.protocol import FlightBackend
from mav_agent.defaults import DEFAULT_QWEN_MODEL, QWEN_API
from mav_agent.qwen_bbox import get_bbox_from_qwen_frame

if TYPE_CHECKING:
    from mav_agent.session import DroneSession

logger = logging.getLogger(__name__)

GetFrameFn = Callable[[], np.ndarray | None]


class DroneVisualServoingController:
    def __init__(
        self, forward_speed=0.2, vertical_error_gain=0.0012, lateral_error_to_yaw_rate=0.001
    ):
        self.forward_speed = forward_speed
        self.vertical_error_gain = vertical_error_gain
        self.lateral_error_to_yaw_rate = lateral_error_to_yaw_rate
        self.max_vz = 0.45
        self.max_yaw_rate = 0.5

    def compute_velocity_control(self, target_x, target_y, center_x, center_y, lock_altitude=False):
        error_x = target_x - center_x
        error_y = target_y - center_y
        vx = self.forward_speed
        vy = 0.0
        yaw_rate = self.lateral_error_to_yaw_rate * error_x
        yaw_rate = max(-self.max_yaw_rate, min(self.max_yaw_rate, yaw_rate))
        if lock_altitude:
            vz = 0.0
        else:
            vz = self.vertical_error_gain * error_y
            vz = max(-self.max_vz, min(self.max_vz, vz))
        return vx, vy, vz, yaw_rate


def _control_under_lock(session: DroneSession | None, fn: Callable[[], bool]) -> bool:
    if session is not None:
        return session.under_dispatch_lock(fn)
    return fn()


def _create_csrt_tracker():
    legacy = getattr(cv2, "legacy", None)
    if legacy is not None and hasattr(legacy, "TrackerCSRT_create"):
        return legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    raise RuntimeError(
        "OpenCV CSRT tracker not available. Reinstall with: pip install opencv-contrib-python-headless"
    )


class FollowController:
    """CSRT tracking loop and visual servoing (~30Hz). Owns the follow thread."""

    def __init__(
        self,
        control: FlightBackend,
        get_frame: GetFrameFn,
        *,
        session: DroneSession | None = None,
        qwen_model: str = DEFAULT_QWEN_MODEL,
        qwen_base_url: str | None = None,
        qwen_api: str = QWEN_API,
        api_key: str | None = None,
        servoing_controller: DroneVisualServoingController | None = None,
    ) -> None:
        self._control = control
        self._get_frame = get_frame
        self._session = session
        self._qwen_model = qwen_model
        self._qwen_base_url = qwen_base_url
        self._qwen_api = qwen_api
        self._api_key = api_key
        self.servoing_controller = servoing_controller or DroneVisualServoingController()
        self._tracking_active = False
        self._tracking_thread: threading.Thread | None = None
        self._current_object: str | None = None
        self._last_bbox: tuple[float, float, float, float] | None = None

    def _motion_preflight(self) -> str | None:
        if not self._control.is_connected:
            return "Vehicle not connected. Run connect first."
        mode = self._control.get_flight_mode()
        if not mode or mode.upper() != "GUIDED":
            if not self._control.set_mode("GUIDED"):
                return "Failed to set GUIDED (required for follow)."
        if not self._control.is_armed():
            return "Not armed. Run arm_takeoff before follow."
        return None

    def track(self, query: str | None = None, duration: float = 0.0) -> str:
        if self._session is not None and not self._session.start_video():
            return (
                "Error: No video source. For mavlink use --image-source udp with "
                "--video-port, or --image-source rtsp with --rtsp. For ros2, camera comes "
                "from --ros-image-topic."
            )
        preflight = self._motion_preflight()
        if preflight:
            return preflight
        frame = self._get_frame()
        if frame is None:
            return "Error: No video frame available"
        try:
            bbox = get_bbox_from_qwen_frame(
                frame,
                query,
                api_key=self._api_key,
                model_name=self._qwen_model,
                base_url=self._qwen_base_url,
                qwen_api=self._qwen_api,
            )
            if bbox is None:
                return f"No object detected for query={query!r}"
            csrt = _create_csrt_tracker()
            x1, y1, x2, y2 = bbox
            x, y, w, h = x1, y1, x2 - x1, y2 - y1
            self._last_bbox = (x1, y1, x2, y2)
            fh, fw = frame.shape[:2]
            logger.info(
                "Qwen bbox query=%r xyxy=[%.0f,%.0f,%.0f,%.0f] csrt=(%.0f,%.0f,%.0f,%.0f) frame=%dx%d",
                query,
                x1,
                y1,
                x2,
                y2,
                x,
                y,
                w,
                h,
                fw,
                fh,
            )
            if not csrt.init(frame, (x, y, w, h)):
                return (
                    f"Failed to initialize CSRT tracker. Qwen bbox xyxy="
                    f"[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}] on {fw}x{fh} frame."
                )
            center_x = fw / 2
            center_y = fh / 2
            target_x = x + w / 2
            target_y = y + h / 2
            vx, vy, vz, yaw_rate = self.servoing_controller.compute_velocity_control(
                target_x, target_y, center_x, center_y, lock_altitude=False
            )
            self._current_object = query or "object"
            self._tracking_active = True
            self._tracking_thread = threading.Thread(
                target=self._visual_servoing_loop,
                args=(csrt, duration),
                daemon=True,
            )
            self._tracking_thread.start()
            return (
                f"Tracking started for {self._current_object}. "
                f"bbox xyxy=[{x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}] "
                f"csrt xywh=({x:.0f},{y:.0f},{w:.0f},{h:.0f}) frame={fw}x{fh}. "
                f"first_cmd vx={vx:.3f} vy={vy:.3f} vz={vz:.3f} yaw_rate={yaw_rate:.3f} (body m/s, rad/s). "
                "Runs until stop or CSRT loses the target."
            )
        except Exception as e:
            self.stop()
            logger.exception("track failed")
            return f"Tracking failed: {e}"

    def _visual_servoing_loop(self, csrt, duration: float) -> None:
        start_time = time.time()
        lost_track_count = 0
        max_lost_frames = 100
        frame_count = 0
        logger.info("Visual servo loop started (vel+yaw_rate setpoints ~30Hz)")
        try:
            while self._tracking_active and (duration <= 0 or time.time() - start_time < duration):
                frame = self._get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue
                frame_count += 1
                ok, bbox = csrt.update(frame)
                if not ok:
                    lost_track_count += 1
                    if lost_track_count >= max_lost_frames:
                        logger.warning("CSRT lost track after %d frames", frame_count)
                        break
                    continue
                lost_track_count = 0
                x, y, w, h = bbox
                current_x = x + w / 2
                current_y = y + h / 2
                fh, fw = frame.shape[:2]
                center_x = fw / 2
                center_y = fh / 2
                vx, vy, vz, yaw_rate = self.servoing_controller.compute_velocity_control(
                    current_x, current_y, center_x, center_y, lock_altitude=False
                )
                sent = _control_under_lock(
                    self._session,
                    lambda: self._control.move_velocity(
                        vx, vy, vz, yaw_rate, 0, lock_altitude=False
                    ),
                )
                if frame_count == 1 or frame_count % 30 == 0:
                    logger.info(
                        "follow frame=%d bbox=(%.0f,%.0f,%.0f,%.0f) err=(%.0f,%.0f) "
                        "cmd vx=%.3f vy=%.3f vz=%.3f yaw_rate=%.3f sent=%s",
                        frame_count,
                        x,
                        y,
                        w,
                        h,
                        current_x - center_x,
                        current_y - center_y,
                        vx,
                        vy,
                        vz,
                        yaw_rate,
                        sent,
                    )
                if not sent and frame_count <= 3:
                    logger.warning("move_velocity returned False (check GUIDED, armed, MAVLink link)")
                time.sleep(0.033)
        except Exception:
            logger.exception("visual servo loop error")
        finally:
            _control_under_lock(self._session, lambda: self._control.stop_motion())
            self._tracking_active = False
            logger.info("Visual servo loop ended after %d frames", frame_count)

    def stop(self) -> str:
        self._tracking_active = False
        if self._tracking_thread and self._tracking_thread.is_alive():
            self._tracking_thread.join(timeout=2.0)
        _control_under_lock(self._session, lambda: self._control.stop_motion())
        self._current_object = None
        return "Tracking stopped"

    def is_active(self) -> bool:
        return self._tracking_active

    def close(self) -> None:
        if self._tracking_active:
            self.stop()
