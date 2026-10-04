"""A scripted stand-in for the Claude call, for deterministic agent tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

Turn = Callable[[list[dict[str, Any]]], dict[str, Any]] | dict[str, Any]


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def tool_use(id_: str, name: str, input_: Any) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


class FakeLLM:
    """Each call pops the next scripted turn. A turn is a message dict or a function of the history."""

    def __init__(self, turns: list[Turn]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def stream(self, system: str, tools: list[dict], messages: list[dict]) -> AsyncIterator[tuple[str, Any]]:
        self.calls.append({"system": system, "tools": [t["name"] for t in tools], "messages": list(messages)})
        if not self.turns:
            raise RuntimeError("FakeLLM ran out of scripted turns")
        turn = self.turns.pop(0)
        msg = turn(messages) if callable(turn) else turn
        for block in msg["content"]:
            if block["type"] == "text":
                yield "text", block["text"]
        yield "message", msg


def last_tool_results(messages: list[dict]) -> list[dict]:
    content = messages[-1]["content"]
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
