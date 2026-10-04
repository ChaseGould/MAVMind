"""MavlinkSource against a fake ArduCopter speaking real MAVLink over UDP."""

import asyncio
import socket

import pytest

from conftest import free_port
from fakes.fake_vehicle import FakeVehicle
from mavmind_vehicle.messages import MissionItem
from mavmind_vehicle.sources.mavlink import MavlinkSource
from mavmind_vehicle.store import TelemetryStore
from mavmind_vehicle.validator import VehicleContext, validate_mission
from mavmind_vehicle.config import load_safety


@pytest.fixture
async def link():
    port = free_port(socket.SOCK_DGRAM)
    source = MavlinkSource(url=f"udpin:127.0.0.1:{port}", stream_rate_hz=None, command_timeout_s=1.5)
    store = TelemetryStore()
    source.on_message(store.ingest)
    await source.connect()
    vehicle = FakeVehicle(port).start()
    assert await source.wait_heartbeat(10)
    await asyncio.sleep(0.3)
    yield source, store, vehicle
    vehicle.stop()
    await source.close()


async def test_telemetry_flows_into_store(link):
    source, store, _ = link
    await asyncio.sleep(1.2)
    assert store.mode == "LOITER" and store.armed is False and store.vehicle_type == "copter"
    assert store.rate("ATTITUDE") > 5
    assert source.target_system == 1


async def test_download_mission(link):
    source, _, _ = link
    items = await source.download_mission()
    assert len(items) == 1 and items[0].seq == 0


async def test_upload_then_readback_matches(link):
    source, _, vehicle = link
    home = (-35.363262, 149.165237, 584.0)
    mission = {
        "name": "t",
        "items": [
            {"command": "NAV_TAKEOFF", "alt_m": 20},
            {"command": "NAV_WAYPOINT", "lat": -35.3620, "lon": 149.1650, "alt_m": 25},
            {"command": "DO_SET_SERVO", "servo": 9, "pwm": 1900},
            {"command": "NAV_RETURN_TO_LAUNCH"},
        ],
    }
    result = validate_mission(mission, load_safety(), VehicleContext(home, 90))
    assert result.ok
    up = await source.upload_mission(result.items)
    assert up.ok, up.message
    assert len(vehicle.mission) == 5
    back = await source.download_mission()
    from mavmind_vehicle.validator import diff_missions

    assert diff_missions(result.items, back) == []
    assert back[3].param1 == 9 and back[3].param2 == 1900


async def test_params_exact_and_prefix(link):
    source, _, _ = link
    assert await source.get_params(["BATT_LOW_VOLT"]) == {"BATT_LOW_VOLT": 10.5}
    fs = await source.get_params(["FS_", "BATT_"])
    assert set(fs) == {"FS_THR_ENABLE", "BATT_LOW_VOLT", "BATT_FS_LOW_ACT"}


async def test_arm_and_mode(link):
    source, store, vehicle = link
    assert await source.set_mode("guided")
    assert await source.arm(True)
    await asyncio.sleep(1.2)
    assert store.armed is True and store.mode == "GUIDED"
    assert not await source.set_mode("NOT_A_MODE")
    assert "unknown mode" in source.last_error
    vehicle.reject_arm = True
    assert await source.arm(False)
    assert not await source.arm(True)
    assert "FAILED" in source.last_error


async def test_upload_without_vehicle_fails_cleanly():
    port = free_port(socket.SOCK_DGRAM)
    source = MavlinkSource(url=f"udpout:127.0.0.1:{port}", stream_rate_hz=None, command_timeout_s=0.3)
    await source.connect()
    try:
        r = await source.upload_mission([MissionItem(0, 16)])
        assert not r.ok
    finally:
        await source.close()
