from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FlightBackend(Protocol):
    @property
    def backend_name(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def connect(self, heartbeat_timeout: float = 30.0) -> bool: ...

    @property
    def is_connected(self) -> bool: ...

    def close(self) -> None: ...

    def arm(self, *, set_guided: bool = True) -> bool: ...

    def disarm(self) -> bool: ...

    def is_armed(self) -> bool: ...

    def set_mode(self, mode: str) -> bool: ...

    def get_flight_mode(self) -> str | None: ...

    def takeoff(self, altitude: float = 3.0) -> bool: ...

    def arm_and_takeoff(self, altitude: float = 3.0) -> bool: ...

    def move_velocity(
        self,
        vx: float,
        vy: float,
        vz: float = 0.0,
        yaw_rate: float = 0.0,
        duration: float = 0.0,
        *,
        lock_altitude: bool = True,
    ) -> bool: ...

    def move_to_position(
        self,
        x: float,
        y: float,
        z: float,
        duration: float = 0.0,
    ) -> bool: ...

    def set_yaw(self, yaw_rad: float, duration: float = 0.0) -> bool: ...

    def set_yaw_rate(self, yaw_rate: float, duration: float = 0.0) -> bool: ...

    def move_trajectory(
        self,
        duration: float,
        vx: float = 0.0,
        vy: float = 0.0,
        vz: float = 0.0,
        yaw_rate: float = 0.0,
        *,
        lock_altitude: bool = True,
    ) -> bool: ...

    def stop_motion(self) -> bool: ...

    def get_parameter(self, name: str, timeout: float = 5.0) -> float | None: ...

    def set_parameter(self, name: str, value: float) -> bool: ...
