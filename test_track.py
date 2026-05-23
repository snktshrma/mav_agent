#!/usr/bin/env python3

import argparse
import sys
import time

from mav_agent import ControlConfig, DroneSession
from mav_agent.control.config import PerceptionConfig
from mav_agent.defaults import DEFAULT_CONNECTION


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--connection", default=DEFAULT_CONNECTION)
    p.add_argument("--rtsp", required=True)
    p.add_argument("--query", default="person")
    p.add_argument("--duration", type=float, default=0.0)
    args = p.parse_args()

    session = DroneSession(
        rtsp_url=args.rtsp,
        control_config=ControlConfig(
            backend="mavlink",
            connection_string=args.connection,
            perception=PerceptionConfig(source="rtsp"),
        ),
    )
    if not session.get_control().connect():
        print("MAVLink connect failed", file=sys.stderr)
        return 1
    if not session.start_video():
        print("Could not open RTSP stream", file=sys.stderr)
        return 1

    time.sleep(1.0)
    tracker = session.get_tracker()
    print(tracker.track(args.query, duration=args.duration))

    try:
        while tracker.is_active():
            time.sleep(0.2)
    except KeyboardInterrupt:
        tracker.stop()
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
