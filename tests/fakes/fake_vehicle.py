"""A tiny ArduCopter stand-in speaking real MAVLink over UDP.

Implements just enough for MavlinkSource tests and local demos without SITL: telemetry
streams, the mission protocol (download and upload), parameters, arming and mode changes.
Run standalone: python tests/fakes/fake_vehicle.py --port 14550
"""

from __future__ import annotations

import argparse
import math
import os
import threading
import time

os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil  # noqa: E402
from pymavlink.dialects.v20 import ardupilotmega as mavlink  # noqa: E402

HOME = (-35.363262, 149.165237, 584.0)
COPTER_MODES = {"STABILIZE": 0, "AUTO": 3, "GUIDED": 4, "LOITER": 5, "RTL": 6, "LAND": 9}


class FakeVehicle:
    def __init__(self, port: int, sysid: int = 1, rate_hz: float = 10.0) -> None:
        self.conn = mavutil.mavlink_connection(
            f"udpout:127.0.0.1:{port}", source_system=sysid, source_component=1, dialect="ardupilotmega"
        )
        self.rate_hz = rate_hz
        self.armed = False
        self.mode = COPTER_MODES["LOITER"]
        self.params = {
            "BATT_LOW_VOLT": 10.5,
            "BATT_FS_LOW_ACT": 2.0,
            "FS_THR_ENABLE": 1.0,
            "FENCE_ENABLE": 0.0,
            "RTL_ALT": 1500.0,
        }
        self.mission: list[dict] = [
            dict(
                seq=0,
                frame=0,
                command=16,
                param1=0,
                param2=0,
                param3=0,
                param4=0,
                x=int(HOME[0] * 1e7),
                y=int(HOME[1] * 1e7),
                z=HOME[2],
                autocontinue=1,
                current=0,
            ),
        ]
        self._upload: dict[int, dict] | None = None
        self._upload_count = 0
        self.reject_arm = False
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._telemetry, daemon=True),
            threading.Thread(target=self._rx, daemon=True),
        ]
        self.t0 = time.time()

    def start(self) -> FakeVehicle:
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(1.0)
        self.conn.close()

    # ---------------------------------------------------------------- telemetry
    def _telemetry(self) -> None:
        mav = self.conn.mav
        n = 0
        while not self._stop.is_set():
            t = time.time() - self.t0
            if n % int(self.rate_hz) == 0:
                base = mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED | (
                    mavlink.MAV_MODE_FLAG_SAFETY_ARMED if self.armed else 0
                )
                mav.heartbeat_send(
                    mavlink.MAV_TYPE_QUADROTOR,
                    mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                    base,
                    self.mode,
                    4 if self.armed else 3,
                )
                mav.sys_status_send(0, 0, 0, 200, 12300, 500 if self.armed else 50, 87, 0, 0, 0, 0, 0, 0)
                mav.home_position_send(
                    int(HOME[0] * 1e7), int(HOME[1] * 1e7), int(HOME[2] * 1000), 0, 0, 0, [1, 0, 0, 0], 0, 0, 0
                )
                mav.gps_raw_int_send(
                    int(t * 1e6), 3, int(HOME[0] * 1e7), int(HOME[1] * 1e7), int(HOME[2] * 1000), 70, 100, 0, 0, 12
                )
            roll = 0.2 * math.sin(t)
            mav.attitude_send(int(t * 1000), roll, 0.05, 1.0, 0, 0, 0)
            mav.global_position_int_send(
                int(t * 1000), int(HOME[0] * 1e7), int(HOME[1] * 1e7), int(HOME[2] * 1000), 0, 0, 0, 0, 5730
            )
            mav.vfr_hud_send(0, 0, 57, 0, HOME[2], 0)
            n += 1
            self._stop.wait(1.0 / self.rate_hz)

    # ---------------------------------------------------------------- protocols
    def _rx(self) -> None:
        mav = self.conn.mav
        while not self._stop.is_set():
            try:
                m = self.conn.recv_match(blocking=True, timeout=0.2)
            except OSError:
                continue
            if m is None:
                continue
            kind = m.get_type()
            src = (m.get_srcSystem(), m.get_srcComponent())
            if kind == "MISSION_REQUEST_LIST":
                mav.mission_count_send(src[0], src[1], len(self.mission), 0)
            elif kind in ("MISSION_REQUEST_INT", "MISSION_REQUEST"):
                if self._upload is None and m.seq < len(self.mission):
                    it = self.mission[m.seq]
                    mav.mission_item_int_send(
                        src[0],
                        src[1],
                        it["seq"],
                        it["frame"],
                        it["command"],
                        it["current"],
                        it["autocontinue"],
                        it["param1"],
                        it["param2"],
                        it["param3"],
                        it["param4"],
                        it["x"],
                        it["y"],
                        it["z"],
                        0,
                    )
            elif kind == "MISSION_COUNT":
                self._upload = {}
                self._upload_count = m.count
                mav.mission_request_int_send(src[0], src[1], 0, 0)
            elif kind == "MISSION_ITEM_INT" and self._upload is not None:
                self._upload[m.seq] = {
                    k: getattr(m, k)
                    for k in (
                        "seq",
                        "frame",
                        "command",
                        "param1",
                        "param2",
                        "param3",
                        "param4",
                        "x",
                        "y",
                        "z",
                        "autocontinue",
                        "current",
                    )
                }
                if len(self._upload) < self._upload_count:
                    mav.mission_request_int_send(src[0], src[1], m.seq + 1, 0)
                else:
                    self.mission = [self._upload[i] for i in range(self._upload_count)]
                    self._upload = None
                    mav.mission_ack_send(src[0], src[1], mavlink.MAV_MISSION_ACCEPTED, 0)
            elif kind == "PARAM_REQUEST_LIST":
                for i, (k, v) in enumerate(self.params.items()):
                    mav.param_value_send(k.encode(), v, 9, len(self.params), i)
            elif kind == "PARAM_REQUEST_READ":
                pid = m.param_id if isinstance(m.param_id, str) else m.param_id.decode()
                if pid in self.params:
                    mav.param_value_send(
                        pid.encode(), self.params[pid], 9, len(self.params), list(self.params).index(pid)
                    )
            elif kind == "COMMAND_LONG":
                result = mavlink.MAV_RESULT_ACCEPTED
                if m.command == mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                    if self.reject_arm and m.param1 == 1:
                        result = mavlink.MAV_RESULT_FAILED
                    else:
                        self.armed = m.param1 == 1
                elif m.command == mavlink.MAV_CMD_DO_SET_MODE:
                    self.mode = int(m.param2)
                elif m.command in (mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, mavlink.MAV_CMD_REQUEST_MESSAGE):
                    pass
                else:
                    result = mavlink.MAV_RESULT_UNSUPPORTED
                mav.command_ack_send(m.command, result)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=14550)
    args = p.parse_args()
    v = FakeVehicle(args.port).start()
    print(f"fake vehicle sending to udp:127.0.0.1:{args.port}; Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        v.stop()


if __name__ == "__main__":
    main()
