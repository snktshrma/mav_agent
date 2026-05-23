"""RTP-H264 video on UDP (GStreamer udpsrc pipeline)."""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

RTP_H264_CAPS = (
    "application/x-rtp,media=(string)video,clock-rate=(int)90000,encoding-name=(string)H264"
)


class UdpVideoStream:
    def __init__(self, port: int = 5600, width: int = 640, height: int = 360) -> None:
        self.port = port
        self.width = width
        self.height = height
        self._process: subprocess.Popen[bytes] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None

    def _running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> bool:
        if self._running():
            return True
        self.stop()
        try:
            cmd = [
                "gst-launch-1.0",
                "-q",
                "udpsrc",
                f"port={self.port}",
                "buffer-size=9000000",
                "!",
                RTP_H264_CAPS,
                "!",
                "rtph264depay",
                "!",
                "h264parse",
                "!",
                "avdec_h264",
                "!",
                "videoscale",
                "!",
                f"video/x-raw,width={self.width},height={self.height}",
                "!",
                "videoconvert",
                "!",
                "video/x-raw,format=RGB",
                "!",
                "filesink",
                "location=/dev/stdout",
                "buffer-mode=2",
            ]
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
            )
            self._stop.clear()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            threading.Thread(target=self._stderr_loop, daemon=True).start()
            logger.info("UDP video started on port %s", self.port)
            return True
        except Exception as e:
            logger.warning("UDP video failed to start: %s", e)
            return False

    def _stderr_loop(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        while not self._stop.is_set() and self._running():
            line = self._process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text and ("ERROR" in text or "WARNING" in text):
                logger.warning("GStreamer: %s", text)

    def _capture_loop(self) -> None:
        frame_size = self.width * self.height * 3
        while not self._stop.is_set():
            if self._process is None or self._process.stdout is None:
                time.sleep(0.1)
                continue
            frame_data = b""
            needed = frame_size
            while needed > 0 and not self._stop.is_set():
                chunk = self._process.stdout.read(needed)
                if not chunk:
                    time.sleep(0.1)
                    break
                frame_data += chunk
                needed -= len(chunk)
            if len(frame_data) == frame_size:
                frame = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                    (self.height, self.width, 3)
                )
                with self._lock:
                    self._latest = frame
            elif not self._stop.is_set():
                time.sleep(0.05)

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest is None:
                return None
            return self._latest.copy()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        with self._lock:
            self._latest = None
