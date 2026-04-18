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
