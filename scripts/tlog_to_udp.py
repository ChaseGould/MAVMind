"""Play a .tlog onto a UDP port as if it were a live vehicle.

Lets any live-link profile (MAVLink, MAVROS via fcu_url, mavlink-router, Mission Planner) consume a
recorded flight. Only vehicle-originated traffic is sent (GCS packets in the log are skipped).

    python scripts/tlog_to_udp.py tests/tlogs/battery_failsafe.tlog --out udpout:127.0.0.1:14550 --speed 1
    # MAVROS:  ros2 launch mavros apm.launch fcu_url:=udp://:14550@
"""

from __future__ import annotations

import argparse
import time

from pymavlink import mavutil


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tlog")
    p.add_argument("--out", default="udpout:127.0.0.1:14550")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    out = mavutil.mavlink_connection(args.out, source_system=1)
    while True:
        log = mavutil.mavlink_connection(args.tlog, dialect="ardupilotmega")
        t0 = wall0 = None
        while True:
            m = log.recv_match()
            if m is None:
                break
            if m.get_type() == "BAD_DATA" or m.get_srcSystem() == 255:
                continue
            if t0 is None:
                t0, wall0 = m._timestamp, time.monotonic()
            if args.speed > 0:
                delay = (m._timestamp - t0) / args.speed - (time.monotonic() - wall0)
                if delay > 0:
                    time.sleep(delay)
            out.write(m.get_msgbuf())
        if not args.loop:
            break


if __name__ == "__main__":
    main()
