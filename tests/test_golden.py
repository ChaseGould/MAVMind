"""Golden questions against the real model (marker: llm). Needs Anthropic credentials.

pytest -m llm tests/test_golden.py
"""

import os

import pytest

from conftest import TLOG
from golden import ask, check, load_questions
from mavmind_agent.api import create_app as create_agent
from mavmind_agent.config import AgentConfig
from mavmind_agent.keys import find_api_key
from mavmind_vehicle.api import create_app as create_vehicle
from mavmind_vehicle.service import VehicleService
from servers import serve, wait_for, write_profile

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not (find_api_key() or os.environ.get("ANTHROPIC_AUTH_TOKEN")), reason="needs ANTHROPIC_API_KEY"
    ),
]


@pytest.fixture(scope="module")
def agent_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("golden")
    profile = write_profile(tmp, "golden-replay", {"type": "replay", "path": str(TLOG), "speed": 0})
    svc = VehicleService(audit_path=str(tmp / "vehicle_audit.jsonl"))
    with serve(create_vehicle(svc, profile=profile)) as vurl:
        wait_for(lambda: svc.store.count("HEARTBEAT") > 160)
        cfg = AgentConfig(vehicle_url=vurl, audit_log=str(tmp / "agent_audit.jsonl"))
        if os.environ.get("MAVMIND_MODEL"):
            cfg.model = os.environ["MAVMIND_MODEL"]
        with serve(create_agent(cfg)) as aurl:
            yield aurl


@pytest.mark.parametrize("q", load_questions(), ids=lambda q: q["id"])
def test_golden_question(agent_url, q):
    result = ask(agent_url, q["question"])
    problems = check(q, result)
    assert not problems, f"{q['id']}: {problems}\n--- answer ---\n{result['answer']}"
