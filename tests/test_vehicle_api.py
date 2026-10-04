"""Vehicle service end to end: REST, WebSocket, both MCP servers, and the gated approve path."""

import asyncio
import json
import socket

import httpx
import pytest
import websockets
from mcp import Client

from conftest import TLOG, free_port
from fakes.fake_vehicle import FakeVehicle
from mavmind_vehicle.api import create_app
from mavmind_vehicle.service import VehicleService
from servers import serve, wait_for, write_profile


@pytest.fixture
def replay_service(tmp_path):
    profile = write_profile(tmp_path, "replay-fast", {"type": "replay", "path": str(TLOG), "speed": 0})
    svc = VehicleService(audit_path=str(tmp_path / "audit.jsonl"))
    with serve(create_app(svc, profile=profile)) as url:
        wait_for(lambda: svc.store.count("HEARTBEAT") > 160)
        yield url, svc


@pytest.fixture
def live_service(tmp_path):
    port = free_port(socket.SOCK_DGRAM)
    profile = write_profile(
        tmp_path, "fake", {"type": "mavlink", "url": f"udpin:127.0.0.1:{port}", "stream_rate_hz": None}
    )
    svc = VehicleService(audit_path=str(tmp_path / "audit.jsonl"))
    vehicle = FakeVehicle(port)
    with serve(create_app(svc, profile=profile)) as url:
        vehicle.start()
        wait_for(lambda: svc.store.latest("HOME_POSITION") is not None and svc.store.latest("SYS_STATUS") is not None)
        yield url, svc, vehicle
    vehicle.stop()


def test_rest_endpoints(replay_service):
    url, _ = replay_service
    health = httpx.get(url + "/health").json()
    assert health == {
        "status": "ok",
        "service": "vehicle",
        "profile": "replay-fast",
        "connected": True,
        "source": "replay",
        "error": None,
    }
    state = httpx.get(url + "/api/state").json()
    assert state["vehicle_type"] == "copter" and state["home"] is not None
    names = {m["name"] for m in httpx.get(url + "/api/messages").json()["messages"]}
    assert {"ATTITUDE", "VFR_HUD", "STATUSTEXT"} <= names
    assert httpx.get(url + "/api/messages/attitude").json()["name"] == "ATTITUDE"
    assert httpx.get(url + "/api/messages/NOPE").status_code == 404
    assert len(httpx.get(url + "/api/mission").json()["items"]) == 9
    assert "RTL" in httpx.get(url + "/api/modes").json()["modes"]
    assert len(httpx.get(url + "/api/geofence").json()["polygon"]) >= 3
    kinds = {e["kind"] for e in httpx.get(url + "/api/events").json()["events"]}
    assert {"mode_change", "failsafe", "armed", "disarmed"} <= kinds
    profiles = {p["name"] for p in httpx.get(url + "/api/profiles").json()["profiles"]}
    assert {"sitl", "replay", "ground-direct", "ground-wsl", "onboard"} <= profiles
    arm = httpx.post(url + "/api/actions/arm", json={"armed": True}).json()
    assert arm["ok"] is False and "read-only" in arm["message"]


def test_websocket_streams_state_and_subscribed_messages(replay_service):
    url, _ = replay_service

    async def run():
        async with websockets.connect(url.replace("http", "ws") + "/ws") as ws:
            await ws.send(json.dumps({"type": "subscribe", "names": ["ATTITUDE"]}))
            seen = {}
            while not {"state", "messages", "message", "command", "mission"} <= set(seen):
                frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                seen.setdefault(frame["type"], frame["data"])
            return seen

    seen = asyncio.run(run())
    assert seen["message"]["name"] == "ATTITUDE" and "roll" in seen["message"]["fields"]
    assert seen["state"]["mode"] is not None
    assert seen["command"] == {"enabled": False}


def test_readonly_mcp_over_http(replay_service):
    url, _ = replay_service

    async def run():
        async with Client(url + "/mcp/readonly/") as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            state = json.loads((await c.call_tool("get_vehicle_state", {})).content[0].text)
            events = json.loads(
                (await c.call_tool("get_events", {"since_seconds_ago": 1000, "kinds": ["failsafe"]})).content[0].text
            )
            return tools, state, events

    tools, state, events = asyncio.run(run())
    assert tools == {
        "get_vehicle_state",
        "get_mission",
        "list_messages",
        "get_message",
        "get_message_history",
        "analyze_field",
        "get_statustext",
        "get_events",
        "get_params",
        "get_link_health",
        "get_home",
    }
    assert state["available"] and state["source"] == "replay:replay-fast"
    assert events["count"] >= 1


def test_command_server_is_off_by_default_and_has_only_propose(replay_service):
    url, svc = replay_service

    async def run():
        async with Client(url + "/mcp/command/") as c:
            tools = [t.name for t in (await c.list_tools()).tools]
            r = json.loads((await c.call_tool("propose_mission", {"name": "x", "items": []})).content[0].text)
            return tools, r

    tools, r = asyncio.run(run())
    assert tools == ["propose_mission"]
    assert r["accepted"] is False and "disabled" in r["reason"]
    assert svc.proposals.list() == []


def test_propose_approve_upload_readback(live_service):
    url, svc, vehicle = live_service
    assert httpx.post(url + "/api/command", json={"enabled": True}).json() == {"enabled": True}
    home = httpx.get(url + "/api/state").json()["home"]
    items = [
        {"command": "NAV_TAKEOFF", "alt_m": 25},
        {"command": "NAV_WAYPOINT", "lat": home["lat"] + 0.001, "lon": home["lon"], "alt_m": 30},
        {"command": "NAV_RETURN_TO_LAUNCH"},
    ]

    async def propose(mission_items):
        async with Client(url + "/mcp/command/") as c:
            return json.loads(
                (await c.call_tool("propose_mission", {"name": "n", "items": mission_items})).content[0].text
            )

    bad = asyncio.run(propose(items[:2]))  # no RTL/LAND
    assert bad["accepted"] and not bad["valid"] and bad["status"] == "invalid"
    assert any(c["name"] == "structure" for c in bad["failed_checks"])
    assert httpx.post(url + f"/api/proposals/{bad['proposal_id']}/approve").status_code == 409

    good = asyncio.run(propose(items))
    assert good["valid"] and good["status"] == "pending"
    pid = good["proposal_id"]
    approved = httpx.post(url + f"/api/proposals/{pid}/approve", timeout=20).json()
    assert approved["status"] == "uploaded", approved
    assert approved["upload"]["verified"] and approved["upload"]["diff"] == []
    assert len(vehicle.mission) == 4
    assert httpx.post(url + f"/api/proposals/{pid}/approve").status_code == 409  # not twice
    rejected = asyncio.run(propose(items))
    r = httpx.post(url + f"/api/proposals/{rejected['proposal_id']}/reject", json={"reason": "no"}).json()
    assert r["status"] == "rejected" and r["reject_reason"] == "no"

    kinds = [rec["kind"] for rec in httpx.get(url + "/api/audit").json()["records"]]
    for k in ("command_server", "proposal", "approve", "upload", "reject"):
        assert k in kinds, k
    arm = httpx.post(url + "/api/actions/arm", json={"armed": True}).json()
    assert arm["ok"] is True
    wait_for(lambda: svc.store.armed is True)
