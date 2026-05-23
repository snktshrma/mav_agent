from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class VehicleState:
    """Snapshot from GLOBAL_POSITION_INT, LOCAL_POSITION_NED, and ATTITUDE."""

    lat_deg: float | None = None
    lon_deg: float | None = None
    alt_msl_m: float | None = None
    alt_rel_m: float | None = None
    local_x_m: float | None = None
    local_y_m: float | None = None
    local_z_m: float | None = None
    yaw_deg: float | None = None
    yaw_rad: float | None = None

    @property
    def has_data(self) -> bool:
        return any(
            v is not None
            for v in (
                self.lat_deg,
                self.lon_deg,
                self.alt_msl_m,
                self.alt_rel_m,
                self.local_x_m,
                self.local_y_m,
                self.local_z_m,
                self.yaw_deg,
            )
        )

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if self.lat_deg is not None and self.lon_deg is not None:
            lines.append(f"Lat/Lon: {self.lat_deg:.7f}, {self.lon_deg:.7f}")
        if self.alt_rel_m is not None:
            lines.append(f"Altitude (rel): {self.alt_rel_m:.2f} m")
        elif self.alt_msl_m is not None:
            lines.append(f"Altitude (MSL): {self.alt_msl_m:.2f} m")
        if self.local_x_m is not None and self.local_y_m is not None:
            z_part = f", z={self.local_z_m:.2f} m" if self.local_z_m is not None else ""
            lines.append(f"Local NED: x={self.local_x_m:.2f}, y={self.local_y_m:.2f}{z_part}")
        if self.yaw_deg is not None:
            lines.append(f"Yaw: {self.yaw_deg:.1f} deg ({self.yaw_rad:.3f} rad)")
        return lines

    def merge_attitude_yaw(self, yaw_rad: float) -> None:
        self.yaw_rad = yaw_rad
        self.yaw_deg = math.degrees(yaw_rad)

    def merge_global_position_int(self, msg) -> None:
        self.lat_deg = msg.lat / 1.0e7
        self.lon_deg = msg.lon / 1.0e7
        self.alt_msl_m = msg.alt / 1000.0
        self.alt_rel_m = msg.relative_alt / 1000.0
        if msg.hdg != 65535:
            self.yaw_deg = msg.hdg / 100.0
            self.yaw_rad = math.radians(self.yaw_deg)

    def merge_local_position_ned(self, msg) -> None:
        self.local_x_m = float(msg.x)
        self.local_y_m = float(msg.y)
        self.local_z_m = float(msg.z)
