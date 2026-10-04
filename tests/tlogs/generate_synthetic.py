"""Generate battery_failsafe.tlog: a deterministic ArduCopter AUTO flight with a battery failsafe.

Story: the copter takes off in AUTO on a 6-waypoint survey box. Under a 40 A load
the pack sags, and at t=105 s the voltage falls below BATT_LOW_VOLT (10.5 V).
ArduCopter reports "Battery 1 is low", takes the BATT_FS_LOW_ACT action (2 = RTL)
and flies home, lands, and disarms. A GCS heartbeat (sysid 255) is interleaved and
~1 % of vehicle packets are dropped, to exercise filtering and link statistics.

Writes the tlog plus battery_failsafe.expected.json with the facts tests check.
Run: python tests/tlogs/generate_synthetic.py
"""

from __future__ import annotations

import json
import math
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "services" / "vehicle"))

from pymavlink.dialects.v20 import ardupilotmega as mavlink  # noqa: E402

from mavmind_vehicle.geo import bearing_deg, distance_m, offset  # noqa: E402

START = 1_790_000_000.0  # fixed epoch so the log is byte-for-byte reproducible
HOME = (-35.363262, 149.165237, 584.09)  # ArduPilot SITL default (CMAC)
DT = 0.02  # simulation step, 50 Hz
ARM_T = 10.0
AUTO_T = 12.0
FS_T = 105.0
TAKEOFF_ALT = 30.0
CRUISE = 8.0
CLIMB = 2.5
LAND_RATE = 1.0
CAPACITY_MAH = 3000.0
LOW_VOLT = 10.5

# Copter custom modes
STABILIZE, AUTO, RTL, LOITER, LAND = 0, 3, 6, 5, 9

PARAMS = {
    "BATT_MONITOR": 4.0,
    "BATT_CAPACITY": CAPACITY_MAH,
    "BATT_LOW_VOLT": LOW_VOLT,
    "BATT_CRT_VOLT": 10.0,
    "BATT_LOW_MAH": 0.0,
    "BATT_CRT_MAH": 0.0,
    "BATT_FS_LOW_ACT": 2.0,
    "BATT_FS_CRT_ACT": 1.0,
    "BATT_LOW_TIMER": 10.0,
    "FS_THR_ENABLE": 1.0,
    "FS_THR_VALUE": 975.0,
    "FS_GCS_ENABLE": 0.0,
    "FS_EKF_ACTION": 1.0,
    "FS_EKF_THRESH": 0.8,
    "FS_CRASH_CHECK": 1.0,
    "FENCE_ENABLE": 1.0,
    "FENCE_TYPE": 7.0,
    "FENCE_ACTION": 1.0,
    "FENCE_ALT_MAX": 120.0,
    "FENCE_RADIUS": 400.0,
    "RTL_ALT": 1500.0,
    "RTL_SPEED": 0.0,
    "WPNAV_SPEED": 800.0,
    "WPNAV_SPEED_UP": 250.0,
    "LAND_SPEED": 100.0,
    "SR1_POSITION": 5.0,
    "SR1_EXTRA1": 10.0,
    "SR1_EXTRA2": 4.0,
    "SR1_EXTRA3": 2.0,
    "SR1_EXT_STAT": 2.0,
}


def build_mission() -> list[dict]:
    lat, lon, _ = HOME
    pts = [(150, 0), (150, 150), (0, 150), (-150, 150), (-150, 0), (-150, -150)]
    items = [dict(cmd=mavlink.MAV_CMD_NAV_WAYPOINT, frame=0, lat=lat, lon=lon, alt=HOME[2])]
    items.append(dict(cmd=mavlink.MAV_CMD_NAV_TAKEOFF, frame=3, lat=0.0, lon=0.0, alt=TAKEOFF_ALT))
    for n, e in pts:
        la, lo = offset(lat, lon, n, e)
        items.append(dict(cmd=mavlink.MAV_CMD_NAV_WAYPOINT, frame=3, lat=la, lon=lo, alt=TAKEOFF_ALT))
    items.append(dict(cmd=mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, frame=3, lat=0.0, lon=0.0, alt=0.0))
    return items


class Writer:
    def __init__(self, path: Path, rng: random.Random) -> None:
        self.f = path.open("wb")
        self.veh = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        self.gcs = mavlink.MAVLink(None, srcSystem=255, srcComponent=190)
        self.rng = rng
        self.counts: dict[str, int] = {}
        self.dropped = 0

    def _write(self, mav: mavlink.MAVLink, msg, t: float, droppable: bool) -> None:
        buf = msg.pack(mav)
        mav.seq = (mav.seq + 1) % 256
        if droppable and self.rng.random() < 0.01:
            self.dropped += 1
            return
        self.f.write(struct.pack(">Q", int(round(t * 1e6))) + buf)
        self.counts[msg.get_type()] = self.counts.get(msg.get_type(), 0) + 1

    def vehicle(self, msg, t: float, droppable: bool = True) -> None:
        self._write(self.veh, msg, START + t, droppable)

    def ground(self, msg, t: float) -> None:
        self._write(self.gcs, msg, START + t, False)

    def close(self) -> None:
        self.f.close()


def main() -> None:
    rng = random.Random(7)
    out = HERE / "battery_failsafe.tlog"
    w = Writer(out, rng)
    v, g = w.veh, w.gcs
    mission = build_mission()
    home_lat, home_lon, home_alt = HOME

    # Vehicle state
    lat, lon, alt_rel = home_lat, home_lon, 0.0
    heading = 0.0
    armed = False
    mode = LOITER
    seq_current = 0
    target_idx = 1
    consumed_mah = 0.0
    phase = "ground"
    voltage = 12.45
    gs = climb = 0.0
    landed_t = None
    events: dict = {"statustext": []}
    facts: dict = {}

    def statustext(t: float, sev: int, text: str) -> None:
        w.vehicle(v.statustext_encode(sev, text.encode()), t, droppable=False)
        events["statustext"].append({"t": round(t, 2), "severity": sev, "text": text})

    t = 0.0
    end_t = None
    step = 0
    while end_t is None or t < end_t:
        t = round(step * DT, 4)
        step += 1
        tick = lambda hz, step=step: step % int(round(1 / (hz * DT))) == 0

        # ------------------------------------------------------------ script
        if t == 0.5:
            statustext(0.5, 6, "ArduCopter V4.5.7 (2a3dc4b7)")
            statustext(0.6, 6, "Frame: QUAD/X")
        if t == 1.0:
            for i, (name, val) in enumerate(PARAMS.items()):
                w.vehicle(v.param_value_encode(name.encode(), val, 9, len(PARAMS), i), t + i * 0.002, False)
        if t == 2.0:
            # A GCS downloads the mission: vehicle answers with MISSION_COUNT and the items.
            w.ground(g.mission_request_list_encode(1, 1, 0), t)
            w.vehicle(v.mission_count_encode(255, 190, len(mission), 0), t + 0.01, False)
            for i, it in enumerate(mission):
                w.ground(g.mission_request_int_encode(1, 1, i, 0), t + 0.02 + i * 0.02)
                w.vehicle(
                    v.mission_item_int_encode(
                        255,
                        190,
                        i,
                        it["frame"],
                        it["cmd"],
                        1 if i == 0 else 0,
                        1,
                        0,
                        0,
                        0,
                        0,
                        int(round(it["lat"] * 1e7)),
                        int(round(it["lon"] * 1e7)),
                        it["alt"],
                        0,
                    ),
                    t + 0.03 + i * 0.02,
                    False,
                )
            w.ground(g.mission_ack_encode(1, 1, 0, 0), t + 0.3)
        if t == 3.0:
            statustext(3.0, 6, "EKF3 IMU0 is using GPS")
        if t == ARM_T:
            armed = True
            statustext(t, 6, "Arming motors")
        if t == AUTO_T:
            mode = AUTO
            phase = "takeoff"
            seq_current = 1
            statustext(t, 6, "Mission: 1 Takeoff")
        if phase in ("takeoff", "cruise") and t >= FS_T and "failsafe_t" not in facts:
            statustext(t, 2, f"Battery 1 is low {voltage:.2f}V used {consumed_mah:.0f} mAh")
            facts.update(
                failsafe_t=round(t, 2),
                failsafe_voltage_v=round(voltage, 2),
                failsafe_consumed_mah=round(consumed_mah),
                failsafe_remaining_pct=round(100 - consumed_mah / CAPACITY_MAH * 100),
                failsafe_seq=seq_current,
                failsafe_alt_rel_m=round(alt_rel, 1),
                failsafe_dist_home_m=round(distance_m(lat, lon, home_lat, home_lon), 1),
                failsafe_mode_from="AUTO",
            )
            mode = RTL
            phase = "rtl"
            facts["rtl_t"] = round(t + 0.1, 2)

        # ---------------------------------------------------------- dynamics
        if armed and phase == "takeoff":
            climb = CLIMB
            alt_rel = min(TAKEOFF_ALT, alt_rel + CLIMB * DT)
            gs = 0.0
            if alt_rel >= TAKEOFF_ALT:
                phase = "cruise"
                seq_current = target_idx = 2
                statustext(t, 6, "Mission: 2 WP")
        elif phase == "cruise":
            tgt = mission[target_idx]
            d = distance_m(lat, lon, tgt["lat"], tgt["lon"])
            heading = bearing_deg(lat, lon, tgt["lat"], tgt["lon"])
            move = min(d, CRUISE * DT)
            gs, climb = CRUISE, 0.0
            rad = math.radians(heading)
            lat, lon = offset(lat, lon, move * math.cos(rad), move * math.sin(rad))
            if d < 1.0:
                w.vehicle(v.mission_item_reached_encode(target_idx), t, False)
                statustext(t, 6, f"Reached command #{target_idx}")
                target_idx += 1
                seq_current = target_idx
                if mission[target_idx]["cmd"] == mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH:
                    mode, phase = RTL, "rtl"
                else:
                    statustext(t, 6, f"Mission: {target_idx} WP")
        elif phase == "rtl":
            d = distance_m(lat, lon, home_lat, home_lon)
            if d > 0.5:
                heading = bearing_deg(lat, lon, home_lat, home_lon)
                move = min(d, CRUISE * DT)
                rad = math.radians(heading)
                lat, lon = offset(lat, lon, move * math.cos(rad), move * math.sin(rad))
                gs, climb = CRUISE, 0.0
            else:
                gs, climb = 0.0, -LAND_RATE
                alt_rel = max(0.0, alt_rel - LAND_RATE * DT)
                if alt_rel <= 0.0:
                    phase = "landed"
                    landed_t = t
                    statustext(t, 6, "Land complete")
        elif phase == "landed" and t >= (landed_t or 0) + 2.0 and armed:
            armed = False
            mode = LAND
            statustext(t, 6, "Disarming motors")
            facts["disarm_t"] = round(t, 2)
            end_t = t + 6.0
            gs = climb = 0.0

        current = 0.6 if not armed else (40.0 if phase in ("takeoff", "cruise", "rtl") else 8.0)
        consumed_mah += current * DT / 3.6
        if armed and phase != "landed":
            sag = 0.0207 if t < FS_T else 0.004
            voltage -= sag * DT
        elif not armed:
            voltage = min(voltage + 0.01 * DT, 12.45) if t < ARM_T else voltage
        remaining = max(0, round(100 - consumed_mah / CAPACITY_MAH * 100))

        roll = 0.03 * math.sin(t * 0.7) if armed else 0.0
        pitch = -0.087 if gs > 1 else 0.0
        yaw = math.radians(heading if heading <= 180 else heading - 360)
        alt_msl = home_alt + alt_rel

        # --------------------------------------------------------- telemetry
        if tick(1):
            base = mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED | (mavlink.MAV_MODE_FLAG_SAFETY_ARMED if armed else 0)
            state = mavlink.MAV_STATE_ACTIVE if armed else mavlink.MAV_STATE_STANDBY
            w.vehicle(v.heartbeat_encode(2, 3, base, mode, state), t, droppable=False)
            w.ground(g.heartbeat_encode(6, 8, 0, 0, 4), t + 0.005)
            w.vehicle(v.mission_current_encode(seq_current, len(mission) - 1, 2 if mode == AUTO else 0, 1), t + 0.001)
            w.vehicle(
                v.radio_status_encode(
                    max(60, int(200 - distance_m(lat, lon, home_lat, home_lon) * 0.2)),
                    max(60, int(195 - distance_m(lat, lon, home_lat, home_lon) * 0.2)),
                    100,
                    40,
                    42,
                    0,
                    0,
                ),
                t + 0.002,
            )
            flags = 831 if t > 3 else 0x01  # 831 = healthy ArduPilot EKF
            w.vehicle(v.ekf_status_report_encode(flags, 0.08, 0.05, 0.04, 0.03, 0.0, 0.0), t + 0.003)
            w.vehicle(
                v.vibration_encode(
                    int(t * 1e6), 6.5 if armed else 0.1, 6.0 if armed else 0.1, 9.0 if armed else 0.2, 0, 0, 0
                ),
                t + 0.004,
            )
            w.vehicle(v.system_time_encode(int((START + t) * 1e6), int(t * 1000)), t + 0.006)
            w.vehicle(v.scaled_pressure_encode(int(t * 1000), 1013.25 - alt_rel * 0.12, 0.0, 2150), t + 0.007)
            w.vehicle(v.power_status_encode(5020, 5100, 3), t + 0.008)
            w.vehicle(v.wind_encode(225.0, 3.2, 0.0), t + 0.009)
            w.vehicle(
                v.battery_status_encode(
                    0,
                    1,
                    3,
                    2850,
                    [int(voltage * 1000 / 3)] * 3 + [65535] * 7,
                    int(current * 100),
                    int(consumed_mah),
                    int(voltage * consumed_mah * 3.6 / 100),
                    remaining,
                    0,
                    2 if voltage < LOW_VOLT else 1,
                ),
                t + 0.011,
            )
        if tick(1 / 10) and t >= 3:
            w.vehicle(
                v.home_position_encode(
                    int(home_lat * 1e7), int(home_lon * 1e7), int(home_alt * 1000), 0, 0, 0, [1, 0, 0, 0], 0, 0, 0
                ),
                t + 0.012,
            )
        if tick(10):
            w.vehicle(v.attitude_encode(int(t * 1000), roll, pitch, yaw, 0.0, 0.0, 0.0), t)
        if tick(5):
            vn = gs * math.cos(math.radians(heading))
            ve = gs * math.sin(math.radians(heading))
            w.vehicle(
                v.global_position_int_encode(
                    int(t * 1000),
                    int(round(lat * 1e7)),
                    int(round(lon * 1e7)),
                    int(alt_msl * 1000),
                    int(alt_rel * 1000),
                    int(vn * 100),
                    int(ve * 100),
                    int(-climb * 100),
                    int(heading * 100) % 36000,
                ),
                t + 0.001,
            )
            w.vehicle(
                v.gps_raw_int_encode(
                    int(t * 1e6),
                    3 if t > 2 else 1,
                    int(round(lat * 1e7)),
                    int(round(lon * 1e7)),
                    int(alt_msl * 1000),
                    80,
                    120,
                    int(gs * 100),
                    int(heading * 100) % 36000,
                    14 if t > 2 else 4,
                ),
                t + 0.002,
            )
        if tick(4):
            throttle = 0 if not armed else (55 if phase in ("takeoff", "cruise", "rtl") else 20)
            w.vehicle(v.vfr_hud_encode(gs, gs, int(heading) % 360, throttle, alt_msl, climb), t + 0.003)
        if tick(2):
            w.vehicle(
                v.sys_status_encode(
                    0x3FFFFF,
                    0x3FFFFF,
                    0x3FFFFF,
                    250,
                    int(voltage * 1000),
                    int(current * 100),
                    remaining,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ),
                t + 0.004,
            )
            if mode == AUTO and target_idx < len(mission) and phase == "cruise":
                tgt = mission[target_idx]
                wp_dist = int(distance_m(lat, lon, tgt["lat"], tgt["lon"]))
                tb = int(bearing_deg(lat, lon, tgt["lat"], tgt["lon"]))
            else:
                wp_dist, tb = 0, int(heading)
            w.vehicle(
                v.nav_controller_output_encode(
                    math.degrees(roll), math.degrees(pitch), int(heading), tb, wp_dist, 0.0, 0.0, 0.0
                ),
                t + 0.005,
            )
            pwm = 1000 if not armed else (1550 if gs > 0 or climb else 1400)
            w.vehicle(v.servo_output_raw_encode(int(t * 1e6), 0, pwm, pwm, pwm, pwm, 0, 0, 0, 0), t + 0.006)
            w.vehicle(
                v.rc_channels_encode(
                    int(t * 1000),
                    8,
                    1500,
                    1500,
                    1000 if not armed else 1500,
                    1500,
                    1800,
                    1000,
                    1000,
                    1000,
                    *([0] * 10),
                    255,
                ),
                t + 0.007,
            )
            w.vehicle(
                v.ahrs2_encode(roll, pitch, yaw, alt_msl, int(round(lat * 1e7)), int(round(lon * 1e7))), t + 0.008
            )

    w.close()

    duration = t
    expected = {
        "file": out.name,
        "start_time": START,
        "duration_s": round(duration, 2),
        "home": {"lat": home_lat, "lon": home_lon, "alt_msl_m": home_alt},
        "vehicle": {"sysid": 1, "type": "copter", "autopilot": "ArduPilot", "firmware": "ArduCopter V4.5.7"},
        "nominal_rates_hz": {
            "HEARTBEAT": 1,
            "ATTITUDE": 10,
            "GLOBAL_POSITION_INT": 5,
            "GPS_RAW_INT": 5,
            "VFR_HUD": 4.17,
            "SYS_STATUS": 2,
            "NAV_CONTROLLER_OUTPUT": 2,
            "SERVO_OUTPUT_RAW": 2,
            "RC_CHANNELS": 2,
            "AHRS2": 2,
            "MISSION_CURRENT": 1,
            "RADIO_STATUS": 1,
            "EKF_STATUS_REPORT": 1,
            "VIBRATION": 1,
            "SYSTEM_TIME": 1,
            "SCALED_PRESSURE": 1,
            "POWER_STATUS": 1,
            "WIND": 1,
            "BATTERY_STATUS": 1,
            "HOME_POSITION": 0.1,
        },
        "message_counts": dict(sorted(w.counts.items())),
        "dropped_vehicle_packets": w.dropped,
        "params": PARAMS,
        "mission": [
            {
                "seq": i,
                "command": mavlink.enums["MAV_CMD"][it["cmd"]].name[8:],
                "lat": it["lat"],
                "lon": it["lon"],
                "alt": it["alt"],
            }
            for i, it in enumerate(mission)
        ],
        "facts": {"arm_t": ARM_T, "auto_t": AUTO_T, **facts},
        "statustext": events["statustext"],
    }
    (HERE / "battery_failsafe.expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes, {sum(w.counts.values())} messages, {duration:.1f}s)")
    print(json.dumps(expected["facts"], indent=2))


if __name__ == "__main__":
    main()
