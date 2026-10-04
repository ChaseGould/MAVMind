"""Live checks against ArduPilot SITL (marker: sitl).

Start SITL with two outputs, one for the vehicle service and one for this test's "pilot":

    sim_vehicle.py -v ArduCopter --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551
    MAVMIND_SITL=1 pytest -m sitl tests/sitl

Milestone 3: the HUD state frame tracks SITL attitude through a scripted flight.
Milestone 8: an approved mission uploads, reads back identically, and flies.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time

import httpx
import pytest
import websockets
from mcp import Client
from pymavlink import mavutil

from mavmind_vehicle.api import create_app
from mavmind_vehicle.service import VehicleService
from servers import serve, wait_for, write_profile

pytestmark = [
    pytest.mark.sitl,
    pytest.mark.skipif(not os.environ.get("MAVMIND_SITL"), reason="set MAVMIND_SITL=1 with SITL running"),
]

VEHICLE_URL = os.environ.get("MAVMIND_SITL_VEHICLE", "udpin:0.0.0.0:14550")
PILOT_URL = os.environ.get("MAVMIND_SITL_PILOT", "udpin:0.0.0.0:14551")


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sitl")
    profile = write_profile(
        tmp,
        "sitl-test",
        {"type": "mavlink", "url": VEHICLE_URL, "stream_rate_hz": 10, "message_rates": {"ATTITUDE": 20}},
    )
    svc = VehicleService(audit_path=str(tmp / "audit.jsonl"))
    with serve(create_app(svc, profile=profile)) as url:
        wait_for(
            lambda: svc.store.latest("HOME_POSITION") is not None and svc.store.latest("EKF_STATUS_REPORT"), timeout=120
        )
        yield url, svc


@pytest.fixture(scope="module")
def pilot():
    conn = mavutil.mavlink_connection(PILOT_URL, source_system=254)
    conn.wait_heartbeat(timeout=30)
    yield conn
    conn.close()


def pilot_command(conn, command, *params):
    p = list(params) + [0] * (7 - len(params))
    conn.mav.command_long_send(conn.target_system, conn.target_component, command, 0, *p)
    return conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)


def wait_ready(url, timeout=180):
    """Wait for the EKF and GPS to be good enough to arm."""

    def ready():
        s = httpx.get(url + "/api/state").json()
        return s["ekf_ok"] and (s["gps_fix_type"] or 0) >= 3

    wait_for(ready, timeout=timeout, interval=1.0)


def test_hud_tracks_sitl_attitude(service, pilot):
    url, _ = service
    wait_ready(url)
    assert httpx.post(url + "/api/actions/mode", json={"mode": "GUIDED"}).json()["ok"]
    ok = False
    for _ in range(10):  # pre-arm checks can take a moment after EKF is ready
        if httpx.post(url + "/api/actions/arm", json={"armed": True}).json()["ok"]:
            ok = True
            break
        time.sleep(3)
    assert ok
    pilot_command(pilot, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 20)
    time.sleep(12)
    # Fly a scripted manoeuvre: yaw and translate so attitude changes.
    for i in range(3):
        pilot.mav.set_position_target_local_ned_send(
            0,
            pilot.target_system,
            pilot.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            0b0000111111000111,
            0,
            0,
            0,
            6 if i % 2 == 0 else -6,
            3,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        time.sleep(4)

    async def compare():
        errors = []
        async with websockets.connect(url.replace("http", "ws") + "/ws") as ws:
            end = time.time() + 10
            while time.time() < end:
                frame = json.loads(await ws.recv())
                if frame["type"] != "state":
                    continue
                truth = pilot.recv_match(type="ATTITUDE", blocking=True, timeout=1)
                if truth is None or frame["data"]["roll_deg"] is None:
                    continue
                errors.append(abs(frame["data"]["roll_deg"] - math.degrees(truth.roll)))
                errors.append(abs(frame["data"]["pitch_deg"] - math.degrees(truth.pitch)))
        return errors

    errors = asyncio.run(compare())
    assert len(errors) > 20
    # 10 Hz frames vs the latest truth sample: allow a little lag.
    assert sorted(errors)[int(len(errors) * 0.9)] < 3.0
    httpx.post(url + "/api/actions/mode", json={"mode": "LAND"})
    wait_for(lambda: httpx.get(url + "/api/state").json()["armed"] is False, timeout=120, interval=1.0)


def test_approved_mission_flies(service, pilot):
    url, svc = service
    wait_ready(url)
    httpx.post(url + "/api/command", json={"enabled": True})
    home = httpx.get(url + "/api/state").json()["home"]
    dlat = 60 / 111320
    items = [
        {"command": "NAV_TAKEOFF", "alt_m": 20},
        {"command": "NAV_WAYPOINT", "lat": home["lat"] + dlat, "lon": home["lon"], "alt_m": 25},
        {"command": "NAV_WAYPOINT", "lat": home["lat"] + dlat, "lon": home["lon"] + dlat, "alt_m": 25},
        {"command": "NAV_RETURN_TO_LAUNCH"},
    ]

    async def propose():
        async with Client(url + "/mcp/command/") as c:
            r = await c.call_tool("propose_mission", {"name": "sitl box", "items": items})
            return json.loads(r.content[0].text)

    proposal = asyncio.run(propose())
    assert proposal["valid"], proposal["failed_checks"]
    approved = httpx.post(url + f"/api/proposals/{proposal['proposal_id']}/approve", timeout=60).json()
    assert approved["status"] == "uploaded" and approved["upload"]["verified"], approved

    assert httpx.post(url + "/api/actions/mode", json={"mode": "GUIDED"}).json()["ok"]
    wait_for(lambda: httpx.post(url + "/api/actions/arm", json={"armed": True}).json()["ok"], timeout=60, interval=3)
    assert httpx.post(url + "/api/actions/mode", json={"mode": "AUTO"}).json()["ok"]
    pilot_command(pilot, mavutil.mavlink.MAV_CMD_MISSION_START, 0, 0)

    def reached() -> set[int]:
        return {e.data.get("seq") for e in svc.store.events(kinds={"mission_progress"}) if "Reached" in e.message}

    wait_for(lambda: {2, 3} <= reached(), timeout=180, interval=1.0)
    wait_for(lambda: svc.store.armed is False, timeout=240, interval=1.0)  # RTL, land, auto-disarm
