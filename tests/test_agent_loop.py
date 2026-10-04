import json

import pytest

from fakes.fake_llm import FakeLLM, last_tool_results, text, tool_use
from mavmind_agent.audit import AuditLog
from mavmind_agent.loop import Agent, ChatSession


class FakeToolbox:
    def __init__(self, results: dict[str, str]):
        self.results = results
        self.calls = []

    def tool_defs(self):
        return [{"name": n, "description": "", "input_schema": {"type": "object"}} for n in self.results]

    async def call(self, name, args):
        self.calls.append((name, args))
        return self.results[name], False


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


async def collect(agen):
    return [e async for e in agen]


def msg(content, stop="end_turn"):
    return {"content": content, "stop_reason": stop}


async def test_tool_round_then_answer(audit):
    llm = FakeLLM(
        [
            msg(
                [text("Checking."), tool_use("t1", "get_vehicle_state", {}), tool_use("t2", "get_home", {})], "tool_use"
            ),
            lambda history: msg([text(f"Got {len(last_tool_results(history))} results.")]),
        ]
    )
    tb = FakeToolbox({"get_vehicle_state": '{"mode":"AUTO"}', "get_home": '{"distance_m":10}'})
    session = ChatSession()
    events = await collect(Agent(llm, audit).run(session, "status?", tb, False))
    types = [e["type"] for e in events]
    assert types == ["text_delta", "tool_call", "tool_call", "tool_result", "tool_result", "text_delta", "done"]
    assert events[-2]["text"] == "Got 2 results."
    # parallel tool results go back in ONE user message
    assert [m["role"] for m in session.messages] == ["user", "assistant", "user", "assistant"]
    assert len(session.messages[2]["content"]) == 2
    assert "Mission proposals are disabled" in llm.calls[0]["system"]
    log = (audit.path.read_text()).splitlines()
    assert sum(1 for line in log if '"tool_call"' in line) == 2


async def test_proposal_event_and_model_sees_verdict_only(audit):
    proposal = {"id": "abc", "status": "pending", "items": [{"seq": 1}] * 50}
    result = json.dumps(
        {"accepted": True, "proposal_id": "abc", "valid": True, "failed_checks": [], "proposal": proposal}
    )
    seen = {}

    def answer(history):
        seen["content"] = last_tool_results(history)[0]["content"]
        return msg([text("Proposed; waiting for your approval.")])

    llm = FakeLLM([msg([tool_use("t1", "propose_mission", {"name": "x", "items": []})], "tool_use"), answer])
    events = await collect(
        Agent(llm, audit).run(ChatSession(), "survey", FakeToolbox({"propose_mission": result}), True)
    )
    props = [e for e in events if e["type"] == "proposal"]
    assert props and props[0]["proposal"]["id"] == "abc"
    assert "proposal" not in json.loads(seen["content"])
    assert "Mission proposals are enabled" in llm.calls[0]["system"]


async def test_invalid_tool_input_is_an_error_result(audit):
    llm = FakeLLM([msg([tool_use("t1", "get_home", "not-a-dict")], "tool_use"), msg([text("ok")])])
    tb = FakeToolbox({"get_home": "{}"})
    events = await collect(Agent(llm, audit).run(ChatSession(), "q", tb, False))
    res = next(e for e in events if e["type"] == "tool_result")
    assert res["is_error"] and "INVALID_JSON" in res["output"]
    assert tb.calls == []


async def test_refusal_stops(audit):
    llm = FakeLLM([msg([], "refusal")])
    events = await collect(Agent(llm, audit).run(ChatSession(), "q", FakeToolbox({}), False))
    assert [e["type"] for e in events] == ["error", "done"]


async def test_failure_rolls_back_the_whole_turn(audit):
    llm = FakeLLM([msg([tool_use("t1", "get_home", {})], "tool_use")])  # runs out on the 2nd call
    session = ChatSession()
    session.messages = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": [text("hi")]}]
    events = await collect(Agent(llm, audit).run(session, "q", FakeToolbox({"get_home": "{}"}), False))
    assert events[-1]["type"] == "error"
    assert len(session.messages) == 2  # history unchanged, still valid


async def test_tool_round_limit(audit):
    loop_turn = msg([tool_use("t", "get_home", {})], "tool_use")
    llm = FakeLLM([loop_turn] * 3)
    events = await collect(
        Agent(llm, audit, max_tool_rounds=3).run(ChatSession(), "q", FakeToolbox({"get_home": "{}"}), False)
    )
    assert events[-1]["type"] == "error" and "tool rounds" in events[-1]["message"]
