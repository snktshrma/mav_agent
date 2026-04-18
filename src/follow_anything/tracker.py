import threading
import time

import cv2

from follow_anything.mavlink import MavlinkConnection, Twist
from follow_anything.qwen_bbox import get_bbox_from_qwen_frame
from follow_anything.visual_servo import DroneVisualServoingController


class RTSPStream:
    def __init__(self, url):
        self.url = url
        self.cap = None
        self._lock = threading.Lock()
        self._latest = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        while not self._stop.is_set():
            ok, bgr = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            with self._lock:
                self._latest = rgb

    def get_frame(self):
        with self._lock:
            if self._latest is None:
                return None
            return self._latest.copy()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self.cap:
            self.cap.release()
            self.cap = None
        with self._lock:
            self._latest = None


class AITracker:
    FORWARD_VELOCITY_DURATION = 10.0

    def __init__(
        self,
        connection_string="udp:0.0.0.0:14550",
        rtsp_url=None,
        qwen_model="qwen2.5-vl-72b-instruct",
        api_key=None,
        mavlink=None,
    ):
        self.servoing_controller = DroneVisualServoingController()
        self._qwen_model = qwen_model
        self._api_key = api_key
        self._mavlink = mavlink if mavlink is not None else MavlinkConnection(connection_string)
        self._owns_mavlink = mavlink is None
        self._rtsp = None
        self._rtsp_url = rtsp_url
        self._frame_source = None
        self._manual_frame = None
        self._lock = threading.Lock()
        self._tracking_active = False
        self._tracking_thread = None
        self._current_object = None

    def set_frame_source(self, fn):
        self._frame_source = fn

    def push_frame(self, frame):
        with self._lock:
            self._manual_frame = frame.copy()

    def connect_mavlink(self, heartbeat_timeout=30.0):
        return self._mavlink.connect(heartbeat_timeout=heartbeat_timeout)

    def start_rtsp(self, url=None):
        u = url or self._rtsp_url
        if not u:
            return False
        self.stop_rtsp()
        self._rtsp = RTSPStream(u)
        return self._rtsp.start()

    def stop_rtsp(self):
        if self._rtsp:
            self._rtsp.stop()
            self._rtsp = None

    def _get_latest_frame(self):
        if self._frame_source is not None:
            return self._frame_source()
        if self._rtsp is not None:
            return self._rtsp.get_frame()
        with self._lock:
            if self._manual_frame is None:
                return None
            return self._manual_frame.copy()

    def track(self, query=None, duration=0.0):
        frame = self._get_latest_frame()
        if frame is None:
            return "Error: No video frame available"
        try:
            bbox = get_bbox_from_qwen_frame(
                frame, query, api_key=self._api_key, model_name=self._qwen_model
            )
            if bbox is None:
                return "No object detected"
            try:
                tracker = cv2.legacy.TrackerCSRT_create()
            except AttributeError:
                tracker = cv2.TrackerCSRT_create()
            x1, y1, x2, y2 = bbox
            x, y, w, h = x1, y1, x2 - x1, y2 - y1
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if not tracker.init(frame_bgr, (int(x), int(y), int(w), int(h))):
                return "Failed to initialize tracker"
            self._current_object = query or "object"
            self._tracking_active = True
            self._tracking_thread = threading.Thread(
                target=self._visual_servoing_loop,
                args=(tracker, duration),
                daemon=True,
            )
            self._tracking_thread.start()
            return f"Tracking started for {self._current_object}."
        except Exception as e:
            self._stop_tracking()
            return f"Tracking failed: {e}"

    def _visual_servoing_loop(self, tracker, duration):
        start_time = time.time()
        lost_track_count = 0
        max_lost_frames = 100
        try:
            while self._tracking_active and (duration <= 0 or time.time() - start_time < duration):
                frame = self._get_latest_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ok, bbox = tracker.update(frame_bgr)
                if not ok:
                    lost_track_count += 1
                    if lost_track_count >= max_lost_frames:
                        break
                    continue
                lost_track_count = 0
                x, y, w, h = bbox
                current_x = x + w / 2
                current_y = y + h / 2
                h, w = frame.shape[:2]
                center_x = w / 2
                center_y = h / 2
                vx, vy, vz, yaw_rate = self.servoing_controller.compute_velocity_control(
                    current_x, current_y, center_x, center_y, lock_altitude=False
                )
                if time.time() - start_time >= self.FORWARD_VELOCITY_DURATION:
                    vx = 0.0
                twist = Twist(vx, vy, vz, yaw_rate)
                self._mavlink.move_twist(twist, duration=0, lock_altitude=False)
                time.sleep(0.033)
        except Exception:
            pass
        finally:
            self._mavlink.move_twist(Twist(), duration=0, lock_altitude=False)
            self._tracking_active = False

    def stop_tracking(self):
        self._stop_tracking()
        return "Tracking stopped"

    def _stop_tracking(self):
        self._tracking_active = False
        if self._tracking_thread and self._tracking_thread.is_alive():
            self._tracking_thread.join(timeout=2.0)
        self._mavlink.move_twist(Twist(), duration=0, lock_altitude=False)
        self._current_object = None

    def is_active(self):
        return self._tracking_active

    @property
    def is_mavlink_connected(self) -> bool:
        return bool(self._mavlink.connected)

    def close(self):
        self.stop_tracking()
        self.stop_rtsp()
        if self._owns_mavlink:
            self._mavlink.stop()
