"""FastAPI app: REST + WebSocket for the desktop UI, and the two MCP servers for the agent.

Approve/reject and arm/mode endpoints are for the UI only. The agent reaches the vehicle
exclusively through the MCP servers mounted under /mcp.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from .config import list_profiles
from .mcp_command import build_command_server
from .mcp_readonly import build_readonly_server
from .proposals import ProposalError
from .service import VehicleService

log = logging.getLogger(__name__)


class ConnectBody(BaseModel):
    profile: str


class ArmBody(BaseModel):
    armed: bool


class ModeBody(BaseModel):
    mode: str


class CommandBody(BaseModel):
    enabled: bool


class RejectBody(BaseModel):
    reason: str | None = None


def create_app(
    service: VehicleService | None = None,
    profile: str | None = None,
    host: str = "127.0.0.1",
    cors_origins: list[str] | None = None,
) -> FastAPI:
    svc = service or VehicleService()
    readonly = build_readonly_server(svc, svc.audit)
    command = build_command_server(svc, svc.audit)
    local = host in ("127.0.0.1", "localhost", "::1")
    security = None if local else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp_kwargs: dict[str, Any] = {
        "streamable_http_path": "/",
        "stateless_http": True,
        "json_response": True,
        "host": host,
    }
    if security is not None:
        mcp_kwargs["transport_security"] = security
    readonly_app = readonly.streamable_http_app(**mcp_kwargs)
    command_app = command.streamable_http_app(**mcp_kwargs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(readonly.session_manager.run())
            await stack.enter_async_context(command.session_manager.run())
            await svc.start()
            if profile:
                try:
                    await svc.connect(profile)
                except Exception as exc:  # noqa: BLE001 - keep serving so the UI can pick another profile
                    log.error("could not connect profile %s: %s", profile, exc)
            try:
                yield
            finally:
                await svc.stop()

    app = FastAPI(title="MAVMind vehicle service", lifespan=lifespan)
    app.state.service = svc
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/mcp/readonly", readonly_app)
    app.mount("/mcp/command", command_app)

    # ---------------------------------------------------------------- status
    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "vehicle",
            "profile": svc.profile.name if svc.profile else None,
            "connected": svc.connected,
            "source": svc.source.source_type if svc.source else None,
            "error": svc.connect_error,
        }

    @app.get("/api/profiles")
    def profiles() -> dict[str, Any]:
        return {
            "active": svc.profile.name if svc.profile else None,
            "profiles": [p.summary() for p in list_profiles()],
        }

    @app.post("/api/connect")
    async def connect(body: ConnectBody) -> dict[str, Any]:
        try:
            await svc.connect(body.profile)
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"connect failed: {exc}") from exc
        return {"ok": True, "profile": body.profile, "message": f"connected via {svc.source_label}"}

    @app.post("/api/disconnect")
    async def disconnect() -> dict[str, Any]:
        await svc.disconnect()
        return {"ok": True}

    # ------------------------------------------------------------- telemetry
    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return svc.state()

    @app.get("/api/messages")
    def messages() -> dict[str, Any]:
        return {"messages": svc.message_summaries()}

    @app.get("/api/messages/{name}")
    def message(name: str) -> dict[str, Any]:
        msg = svc.store.latest(name.upper())
        if msg is None:
            raise HTTPException(404, f"{name.upper()} not received")
        return svc.message_detail(msg)

    @app.get("/api/mission")
    def mission() -> dict[str, Any]:
        return svc.mission_payload()

    @app.post("/api/mission/refresh")
    async def mission_refresh() -> dict[str, Any]:
        try:
            await svc.refresh_mission()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"mission download failed: {exc}") from exc
        return svc.mission_payload()

    @app.get("/api/geofence")
    def geofence() -> dict[str, Any]:
        fence = svc.safety.get("geofence", {})
        alt = svc.safety.get("altitude", {})
        return {
            "enabled": fence.get("enabled", True),
            "polygon": fence.get("polygon", []),
            "max_alt_m": alt.get("max_m"),
            "min_alt_m": alt.get("min_m"),
            "max_distance_from_home_m": svc.safety.get("max_distance_from_home_m"),
        }

    @app.get("/api/events")
    def events(since: float | None = None) -> dict[str, Any]:
        return {"events": [e.to_dict() for e in svc.store.events(since=since)]}

    @app.get("/api/modes")
    def modes() -> dict[str, Any]:
        return {"modes": svc.available_modes()}

    # --------------------------------------------- operator actions (UI only)
    @app.post("/api/actions/arm")
    async def arm(body: ArmBody) -> dict[str, Any]:
        ok, msg = await svc.arm(body.armed)
        return {"ok": ok, "message": msg}

    @app.post("/api/actions/mode")
    async def mode(body: ModeBody) -> dict[str, Any]:
        ok, msg = await svc.set_mode(body.mode)
        return {"ok": ok, "message": msg}

    @app.get("/api/command")
    def command_state() -> dict[str, Any]:
        return {"enabled": svc.command_enabled}

    @app.post("/api/command")
    def command_set(body: CommandBody) -> dict[str, Any]:
        svc.set_command_enabled(body.enabled)
        return {"enabled": svc.command_enabled}

    @app.get("/api/proposals")
    def proposals() -> dict[str, Any]:
        return {"proposals": [p.to_dict() for p in svc.proposals.list()]}

    @app.get("/api/proposals/{pid}")
    def proposal(pid: str) -> dict[str, Any]:
        try:
            return svc.proposals.get(pid).to_dict()
        except ProposalError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/proposals/{pid}/approve")
    async def approve(pid: str) -> dict[str, Any]:
        try:
            p = await svc.approve(pid)
        except ProposalError as exc:
            raise HTTPException(409, str(exc)) from exc
        return p.to_dict()

    @app.post("/api/proposals/{pid}/reject")
    def reject(pid: str, body: RejectBody | None = None) -> dict[str, Any]:
        try:
            return svc.proposals.reject(pid, body.reason if body else None).to_dict()
        except ProposalError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/audit")
    def audit(limit: int = 200) -> dict[str, Any]:
        return {"records": svc.audit.read(limit)}

    # ------------------------------------------------------------- websocket
    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        client = svc.add_client()

        async def reader() -> None:
            while True:
                data = await socket.receive_json()
                if isinstance(data, dict) and data.get("type") == "subscribe":
                    names = data.get("names") or []
                    client.subscriptions = {str(n).upper() for n in names}
                    for n in client.subscriptions:
                        msg = svc.store.latest(n)
                        if msg is not None:
                            client.push({"type": "message", "data": svc.message_detail(msg)})

        reader_task = asyncio.create_task(reader())
        try:
            while True:
                getter = asyncio.create_task(client.queue.get())
                done, _ = await asyncio.wait({getter, reader_task}, return_when=asyncio.FIRST_COMPLETED)
                if reader_task in done:
                    getter.cancel()
                    break
                await socket.send_json(getter.result())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader_task.cancel()
            with contextlib.suppress(BaseException):
                await reader_task
            svc.remove_client(client)

    return app
