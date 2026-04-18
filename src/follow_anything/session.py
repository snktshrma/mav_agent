from __future__ import annotations

from follow_anything.tracker import AITracker


class DroneSession:
    """One interactive session: settings plus a lazily created `AITracker`."""

    def __init__(
        self,
        connection_string: str = "udp:0.0.0.0:14550",
        rtsp_url: str | None = None,
        qwen_model: str = "qwen2.5-vl-72b-instruct",
        api_key: str | None = None,
    ) -> None:
        self._connection_string = connection_string
        self._rtsp_url = rtsp_url
        self._qwen_model = qwen_model
        self._api_key = api_key
        self._tracker: AITracker | None = None

    @property
    def connection_string(self) -> str:
        return self._connection_string

    def get_tracker(self) -> AITracker:
        if self._tracker is None:
            self._tracker = AITracker(
                connection_string=self._connection_string,
                rtsp_url=self._rtsp_url,
                qwen_model=self._qwen_model,
                api_key=self._api_key,
            )
        return self._tracker

    def set_rtsp_url(self, url: str | None) -> None:
        self._rtsp_url = url

    def start_rtsp(self, url: str) -> str:
        self._rtsp_url = url
        t = self.get_tracker()
        if t.start_rtsp(url):
            return f"RTSP started: {url}"
        return "Failed to open RTSP stream"

    def close(self) -> None:
        if self._tracker is not None:
            self._tracker.close()
            self._tracker = None
