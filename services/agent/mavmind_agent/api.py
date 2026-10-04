"""Agent HTTP API: /api/chat streams NDJSON events to the desktop UI."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .audit import AuditLog
from .config import AgentConfig, load_config
from .keys import find_api_key
from .llm import LLM, AnthropicLLM
from .loop import Agent, ChatSession
from .toolbox import McpToolbox, Toolbox, ToolboxError

log = logging.getLogger(__name__)


class ChatBody(BaseModel):
    session_id: str
    message: str
    commands_enabled: bool = False


class ResetBody(BaseModel):
    session_id: str


def create_app(
    cfg: AgentConfig | None = None,
    llm: LLM | None = None,
    toolbox_factory: Any = None,
    commands_check: Any = None,
) -> FastAPI:
    cfg = cfg or load_config()
    audit = AuditLog(cfg.audit_path)
    agent = Agent(llm or AnthropicLLM(cfg), audit, cfg.max_tool_rounds)
    sessions: dict[str, ChatSession] = {}

    async def vehicle_commands_enabled() -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                r = await http.get(cfg.vehicle_url.rstrip("/") + "/api/command")
                return bool(r.json().get("enabled"))
        except Exception:  # noqa: BLE001
            return False

    def default_toolbox(commands: bool) -> Toolbox:
        servers = {"readonly": cfg.readonly_mcp_url}
        if commands:
            servers["command"] = cfg.command_mcp_url
        return McpToolbox(servers)

    make_toolbox = toolbox_factory or default_toolbox
    check_commands = commands_check or vehicle_commands_enabled

    app = FastAPI(title="MAVMind agent service")
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health() -> dict[str, Any]:
        reachable = False
        try:
            async with httpx.AsyncClient(timeout=1.5) as http:
                reachable = (await http.get(cfg.vehicle_url.rstrip("/") + "/health")).status_code == 200
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": "ok",
            "service": "agent",
            "model": cfg.model,
            "vehicle_url": cfg.vehicle_url,
            "readonly_mcp": reachable,
            "api_key": find_api_key() is not None,
        }

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        session = sessions.get(body.session_id)
        if session is None:
            session = sessions[body.session_id] = ChatSession(id=body.session_id)
        if session.lock.locked():
            raise HTTPException(409, "this chat session is already answering; wait or stop it first")
        # Commands need both switches: the chat request and the vehicle service's own flag.
        commands = body.commands_enabled and await check_commands()

        async def stream() -> AsyncIterator[bytes]:
            async with session.lock:
                try:
                    async with make_toolbox(commands) as toolbox:
                        async for event in agent.run(session, body.message, toolbox, commands):
                            yield (json.dumps(event, default=str) + "\n").encode()
                except ToolboxError as exc:
                    yield (json.dumps({"type": "error", "message": str(exc)}) + "\n").encode()
                    yield (json.dumps({"type": "done", "stop_reason": "error"}) + "\n").encode()

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/api/chat/reset")
    def reset(body: ResetBody) -> dict[str, Any]:
        sessions.pop(body.session_id, None)
        audit.write("session_reset", session=body.session_id)
        return {"ok": True}

    return app
