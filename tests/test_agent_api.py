"""Agent service end to end: fake LLM, real MCP toolbox, real vehicle service on the tlog."""

import json

import httpx
import pytest

from conftest import TLOG
from fakes.fake_llm import FakeLLM, last_tool_results, text, tool_use
from mavmind_agent.api import create_app as create_agent
from mavmind_agent.config import AgentConfig
from mavmind_vehicle.api import create_app as create_vehicle
from mavmind_vehicle.service import VehicleService
from servers import serve, wait_for, write_profile


@pytest.fixture
def vehicle(tmp_path):
    profile = write_profile(tmp_path, "replay-fast", {"type": "replay", "path": str(TLOG), "speed": 0})
    svc = VehicleService(audit_path=str(tmp_path / "vehicle_audit.jsonl"))
    with serve(create_vehicle(svc, profile=profile)) as url:
        wait_for(lambda: svc.store.count("HEARTBEAT") > 160)
        yield url, svc


def chat(url, message, commands=False, session="s1"):
    with httpx.stream(
        "POST",
        url + "/api/chat",
        json={"session_id": session, "message": message, "commands_enabled": commands},
        timeout=30,
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def test_chat_answers_from_real_mcp_tools(vehicle, tmp_path):
    vurl, _ = vehicle
    captured = {}

    def answer(history):
        captured["events"] = json.loads(last_tool_results(history)[0]["content"])
        return {"content": [text("It switched to RTL because of a low battery failsafe.")], "stop_reason": "end_turn"}

    llm = FakeLLM(
        [
            {
                "content": [tool_use("t1", "get_events", {"kinds": ["mode_change"], "since_seconds_ago": 1000})],
                "stop_reason": "tool_use",
            },
            answer,
        ]
    )
    cfg = AgentConfig(vehicle_url=vurl, audit_log=str(tmp_path / "agent_audit.jsonl"))
    with serve(create_agent(cfg, llm=llm)) as aurl:
        health = httpx.get(aurl + "/health").json()
        assert health["readonly_mcp"] is True and health["model"] == "claude-opus-5-5"
        events = chat(aurl, "Why did it switch to RTL?")
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "text_delta", "done"]
    rtl = [e for e in captured["events"]["events"] if e["data"].get("to") == "RTL"]
    assert "Battery 1 is low" in rtl[0]["data"]["possible_cause"]
    # read-only tools only, since commands were not enabled
    assert "propose_mission" not in llm.calls[0]["tools"] and "get_vehicle_state" in llm.calls[0]["tools"]


def test_commands_need_both_switches(vehicle, tmp_path):
    vurl, svc = vehicle
    llm = FakeLLM([{"content": [text("ok")], "stop_reason": "end_turn"}] * 2)
    cfg = AgentConfig(vehicle_url=vurl, audit_log=str(tmp_path / "agent_audit.jsonl"))
    with serve(create_agent(cfg, llm=llm)) as aurl:
        chat(aurl, "hi", commands=True)  # vehicle flag still off
        assert "propose_mission" not in llm.calls[-1]["tools"]
        httpx.post(vurl + "/api/command", json={"enabled": True})
        chat(aurl, "hi", commands=True, session="s2")
        assert "propose_mission" in llm.calls[-1]["tools"]


def test_vehicle_unreachable_is_reported(tmp_path):
    cfg = AgentConfig(vehicle_url="http://127.0.0.1:9", audit_log=str(tmp_path / "a.jsonl"))
    with serve(create_agent(cfg, llm=FakeLLM([]))) as aurl:
        events = chat(aurl, "hi")
    assert events[0]["type"] == "error" and "cannot reach" in events[0]["message"]
