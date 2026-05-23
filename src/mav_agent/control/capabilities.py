"""Backend capability names checked at skill dispatch time."""

MAVLINK_CAPABILITIES: frozenset[str] = frozenset(
    {
        "connect",
        "arm",
        "takeoff",
        "arm_takeoff",
        "disarm",
        "set_mode",
        "land",
        "rtl",
        "loiter",
        "move_velocity",
        "move_trajectory",
        "move_to_position",
        "set_yaw",
        "set_yaw_rate",
        "stop_motion",
        "get_param",
        "set_param",
        "vehicle_state",
    }
)

ROS2_CAPABILITIES: frozenset[str] = frozenset(
    {
        "connect",
        "arm",
        "takeoff",
        "arm_takeoff",
        "disarm",
        "set_mode",
        "land",
        "rtl",
        "loiter",
        "move_velocity",
        "move_trajectory",
        "set_yaw_rate",
        "stop_motion",
    }
)
