"""The agent loop: user message -> Claude -> MCP tool calls -> ... -> answer, as a stream of UI events."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLog
from .llm import LLM
from .prompts import system_prompt
from .toolbox import Toolbox

log = logging.getLogger(__name__)

PROPOSE_TOOL = "propose_mission"


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _get(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _valid_input(value: Any) -> bool:
    return isinstance(value, dict)


class Agent:
    def __init__(self, llm: LLM, audit: AuditLog, max_tool_rounds: int = 25) -> None:
        self.llm = llm
        self.audit = audit
        self.max_tool_rounds = max_tool_rounds

    async def run(
        self, session: ChatSession, text: str, toolbox: Toolbox, commands_enabled: bool
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one user turn. History stays append-only; a failed turn is rolled back whole."""
        start_len = len(session.messages)
        session.messages.append({"role": "user", "content": text})
        self.audit.write("user_message", session=session.id, text=text, commands_enabled=commands_enabled)
        system = system_prompt(commands_enabled)
        tools = toolbox.tool_defs()
        try:
            for _round in range(self.max_tool_rounds):
                final = None
                async for kind, payload in self.llm.stream(system, tools, session.messages):
                    if kind == "text":
                        yield {"type": "text_delta", "text": payload}
                    elif kind == "retry":
                        yield {"type": "notice", "message": "retrying the model turn"}
                    elif kind == "message":
                        final = payload
                if final is None:
                    raise RuntimeError("model stream ended without a message")
                content = _get(final, "content", [])
                stop = _get(final, "stop_reason")
                session.messages.append({"role": "assistant", "content": content})

                if stop == "refusal":
                    self.audit.write("refusal", session=session.id)
                    yield {"type": "error", "message": "The model declined this request."}
                    yield {"type": "done", "stop_reason": stop}
                    return
                if stop == "pause_turn":
                    continue
                tool_uses = [b for b in content if _get(b, "type") == "tool_use"]
                if not tool_uses:
                    text_out = "".join(_get(b, "text", "") for b in content if _get(b, "type") == "text")
                    self.audit.write("assistant_message", session=session.id, text=text_out, stop_reason=stop)
                    yield {"type": "done", "stop_reason": stop}
                    return
                if stop == "max_tokens":
                    raise RuntimeError("the model ran out of output tokens while writing a tool call")

                for b in tool_uses:
                    yield {"type": "tool_call", "id": _get(b, "id"), "name": _get(b, "name"), "input": _get(b, "input")}
                outputs = await asyncio.gather(*(self._call(session, toolbox, b) for b in tool_uses))
                results = []
                for b, (out_text, is_error, proposal) in zip(tool_uses, outputs):
                    yield {
                        "type": "tool_result",
                        "id": _get(b, "id"),
                        "name": _get(b, "name"),
                        "output": out_text,
                        "is_error": is_error,
                    }
                    if proposal is not None:
                        yield {"type": "proposal", "proposal": proposal}
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": _get(b, "id"),
                            "content": self._for_model(_get(b, "name"), out_text),
                            "is_error": is_error,
                        }
                    )
                # All results for one assistant turn go back in a single user message.
                session.messages.append({"role": "user", "content": results})
            raise RuntimeError(f"stopped after {self.max_tool_rounds} tool rounds without an answer")
        except (GeneratorExit, asyncio.CancelledError):
            # Client stopped the stream mid-turn: drop the partial turn so history stays valid.
            del session.messages[start_len:]
            self.audit.write("turn_cancelled", session=session.id)
            raise
        except Exception as exc:
            del session.messages[start_len:]
            self.audit.write("turn_error", session=session.id, error=str(exc))
            log.exception("chat turn failed")
            yield {"type": "error", "message": _describe(exc)}

    async def _call(self, session: ChatSession, toolbox: Toolbox, block: Any) -> tuple[str, bool, dict | None]:
        name = _get(block, "name")
        args = _get(block, "input")
        if not _valid_input(args):
            text = json.dumps({"INVALID_JSON": json.dumps(args, default=str)})
            self.audit.write(
                "tool_call", session=session.id, tool=name, args=args, is_error=True, error="invalid input"
            )
            return text, True, None
        started = time.monotonic()
        text, is_error = await toolbox.call(name, args)
        self.audit.write(
            "tool_call",
            session=session.id,
            tool=name,
            args=args,
            is_error=is_error,
            duration_s=round(time.monotonic() - started, 3),
            result=text[:2000],
        )
        proposal = None
        if name == PROPOSE_TOOL and not is_error:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {}
            proposal = data.get("proposal")
            if proposal is not None:
                self.audit.write(
                    "proposal_event", session=session.id, proposal_id=proposal.get("id"), status=proposal.get("status")
                )
        return text, is_error, proposal

    @staticmethod
    def _for_model(name: str, text: str) -> str:
        """The UI gets the full proposal; the model gets the verdict without the bulky item expansion."""
        if name != PROPOSE_TOOL:
            return text
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        data.pop("proposal", None)
        return json.dumps(data)


def _describe(exc: Exception) -> str:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "Anthropic API authentication failed. Set ANTHROPIC_API_KEY for the agent service."
    if isinstance(exc, anthropic.RateLimitError):
        return "Rate limited by the Anthropic API. Wait a moment and try again."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Cannot reach the Anthropic API. Check the network connection."
    if isinstance(exc, TypeError) and "authentication" in str(exc).lower():
        return (
            "No Anthropic credentials for the agent service. Set ANTHROPIC_API_KEY (or store the key in the "
            "OS keychain under service 'mavmind') and restart the agent."
        )
    return str(exc)
