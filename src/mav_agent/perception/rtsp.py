import threading
import time

import cv2


class RTSPStream:
    def __init__(self, url: str) -> None:
        self.url = url
        self.cap = None
        self._lock = threading.Lock()
        self._latest = None
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive() and self.cap is not None:
            return True
        self.stop()
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
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

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self.cap:
            self.cap.release()
            self.cap = None
        with self._lock:
            self._latest = None
