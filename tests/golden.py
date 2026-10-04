"""Ask the golden questions through an agent service and check the answers contain the known facts."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

QUESTIONS = Path(__file__).parent / "golden_questions.yaml"


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["questions"]


def ask(agent_url: str, question: str, timeout: float = 240.0) -> dict[str, Any]:
    session = f"golden-{uuid.uuid4().hex[:8]}"
    text, tools, errors = [], [], []
    with httpx.stream(
        "POST",
        agent_url.rstrip("/") + "/api/chat",
        json={"session_id": session, "message": question, "commands_enabled": False},
        timeout=timeout,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev["type"] == "text_delta":
                text.append(ev["text"])
            elif ev["type"] == "tool_call":
                tools.append(ev["name"])
            elif ev["type"] == "error":
                errors.append(ev["message"])
    return {"answer": "".join(text), "tools": tools, "errors": errors}


def check(q: dict[str, Any], result: dict[str, Any]) -> list[str]:
    problems = list(result["errors"])
    answer = result["answer"]
    for alternatives in q.get("must", []):
        if not any(re.search(p, answer, re.IGNORECASE) for p in alternatives):
            problems.append(f"answer matches none of {alternatives}")
    for tool in q.get("tools", []):
        if tool not in result["tools"]:
            problems.append(f"expected a {tool} call; got {result['tools']}")
    return problems
