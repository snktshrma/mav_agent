#!/usr/bin/env python3

import argparse
import sys
import time

from follow_anything import AITracker


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--connection", default="udp:0.0.0.0:14550")
    p.add_argument("--rtsp", required=True)
    p.add_argument("--query", default="person")
    p.add_argument("--duration", type=float, default=0.0)
    args = p.parse_args()

    tracker = AITracker(connection_string=args.connection, rtsp_url=args.rtsp)
    if not tracker.connect_mavlink():
        print("MAVLink connect failed", file=sys.stderr)
        return
    if not tracker.start_rtsp():
        print("Could not open RTSP stream", file=sys.stderr)
        return

    time.sleep(1.0)
    # print(tracker)
    print(tracker.track(args.query, duration=args.duration))

    try:
        while tracker.is_active():
            time.sleep(0.2)
    except KeyboardInterrupt:
        tracker.stop_tracking()
    tracker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
