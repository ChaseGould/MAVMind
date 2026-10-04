"""VehicleService: owns the active profile, source, store, proposals, and WebSocket fan-out."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pymavlink import mavutil

from .audit import AuditLog
from .config import Profile, load_profile, load_safety
from .messages import MavMessage, MissionItem
from .proposals import Proposal, ProposalManager
from .sources import BaseSource, create_source
from .state import home_position, state_frame
from .store import Event, TelemetryStore
from .units import convert_fields
from .validator import VehicleContext

log = logging.getLogger(__name__)

STATE_HZ = 10.0
MESSAGE_PUSH_MIN_DT = 0.1


@dataclass(eq=False)
class WsClient:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=500))
    subscriptions: set[str] = field(default_factory=set)
    last_push: dict[str, float] = field(default_factory=dict)

    def push(self, frame: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            # Slow client: drop the oldest frame rather than block the link.
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(frame)


class VehicleService:
    def __init__(self, safety: dict[str, Any] | None = None, audit_path: str = "logs/vehicle_audit.jsonl") -> None:
        self.safety = safety if safety is not None else load_safety()
        self.audit = AuditLog(audit_path)
        self.store = TelemetryStore()
        self.profile: Profile | None = None
        self.source: BaseSource | None = None
        self.command_enabled = False
        self.connect_error: str | None = None
        self.proposals = ProposalManager(self.safety, self.vehicle_context, self.audit)
        self.clients: set[WsClient] = set()
        self._tasks: list[asyncio.Task[Any]] = []
        self._source_tasks: list[asyncio.Task[Any]] = []
        self._connect_lock = asyncio.Lock()
        self.store.add_message_listener(self._on_message)
        self.store.add_event_listener(self._on_event)
        self.store.add_mission_listener(self._on_mission)
        self.proposals.add_listener(self._on_proposal)

    # ---------------------------------------------------------------- context
    @property
    def source_label(self) -> str:
        if self.source is None:
            return "disconnected"
        return f"{self.source.source_type}:{self.profile.name if self.profile else '?'}"

    @property
    def connected(self) -> bool:
        return self.source is not None and self.source.connected

    def vehicle_context(self) -> VehicleContext:
        home = home_position(self.store)
        frame = self.state()
        return VehicleContext(
            home=(home["lat"], home["lon"], home["alt_msl_m"]) if home else None,
            battery_remaining_pct=frame["battery_remaining_pct"],
            vehicle_type=self.store.vehicle_type,
        )

    def state(self) -> dict[str, Any]:
        return state_frame(
            self.store,
            self.profile.name if self.profile else None,
            self.source.source_type if self.source else None,
            self.connected,
        )

    def available_modes(self) -> list[str]:
        if self.store.mav_type is None:
            return []
        mapping = mavutil.mode_mapping_byname(self.store.mav_type) or {}
        return sorted(mapping, key=lambda m: mapping[m])

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._state_loop()))
        self._tasks.append(asyncio.create_task(self._summary_loop()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.disconnect()

    async def connect(self, profile_name: str) -> None:
        async with self._connect_lock:
            await self._disconnect()
            profile = load_profile(profile_name)
            source = create_source(profile.source)
            self.store.reset()
            self.store.live = source.is_live
            if profile.store:
                self.store.history_s = float(profile.store.get("history_s", self.store.history_s))
                hz = float(profile.store.get("history_max_hz", 1 / self.store.history_min_dt))
                self.store.history_min_dt = 1.0 / hz if hz > 0 else 0.0
            source.on_message(self.store.ingest)
            self.profile, self.source = profile, source
            self.connect_error = None
            try:
                await source.connect()
            except Exception as exc:
                self.connect_error = str(exc)
                self.audit.write("connect", profile=profile.name, ok=False, error=str(exc))
                raise
            self.audit.write("connect", profile=profile.name, ok=True, source=source.source_type)
            self._source_tasks.append(asyncio.create_task(self._after_connect(source)))
            if source.is_live:
                self._source_tasks.append(asyncio.create_task(self._link_watch()))

    async def disconnect(self) -> None:
        async with self._connect_lock:
            await self._disconnect()

    async def _disconnect(self) -> None:
        for t in self._source_tasks:
            t.cancel()
        self._source_tasks.clear()
        if self.source is not None:
            with contextlib.suppress(Exception):
                await self.source.close()
            self.audit.write("disconnect", profile=self.profile.name if self.profile else None)
        self.source = None

    async def _after_connect(self, source: BaseSource) -> None:
        """Once the vehicle is heard, fetch the mission so the map and tools have it."""
        if not source.is_live:
            return
        if not await source.wait_heartbeat(60):
            return
        await asyncio.sleep(1.0)
        with contextlib.suppress(Exception):
            self.store.set_mission(await source.download_mission())

    async def _link_watch(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self.store.check_link()

    async def refresh_mission(self) -> list[MissionItem]:
        if self.source is None:
            raise RuntimeError("not connected")
        items = await self.source.download_mission()
        if items or self.source.is_live:
            self.store.set_mission(items)
        return self.store.mission()

    # --------------------------------------------------------------- actions
    async def arm(self, armed: bool) -> tuple[bool, str]:
        if self.source is None:
            return False, "not connected"
        ok = await self.source.arm(armed)
        msg = "ok" if ok else (self.source.last_error or "rejected")
        self.audit.write("action_arm", armed=armed, ok=ok, message=msg, origin="ui")
        return ok, msg

    async def set_mode(self, mode: str) -> tuple[bool, str]:
        if self.source is None:
            return False, "not connected"
        ok = await self.source.set_mode(mode)
        msg = "ok" if ok else (self.source.last_error or "rejected")
        self.audit.write("action_mode", mode=mode, ok=ok, message=msg, origin="ui")
        return ok, msg

    def set_command_enabled(self, enabled: bool) -> None:
        self.command_enabled = enabled
        self.audit.write("command_server", enabled=enabled, origin="ui")
        self._broadcast({"type": "command", "data": {"enabled": enabled}})

    async def approve(self, pid: str) -> Proposal:
        return await self.proposals.approve(pid, self.source)

    # ------------------------------------------------------------ websockets
    def add_client(self) -> WsClient:
        c = WsClient()
        self.clients.add(c)
        c.push({"type": "command", "data": {"enabled": self.command_enabled}})
        c.push({"type": "mission", "data": self.mission_payload()})
        for p in self.proposals.list()[:20]:
            c.push({"type": "proposal", "data": p.to_dict()})
        return c

    def remove_client(self, c: WsClient) -> None:
        self.clients.discard(c)

    def _broadcast(self, frame: dict[str, Any]) -> None:
        for c in list(self.clients):
            c.push(frame)

    def mission_payload(self) -> dict[str, Any]:
        return {"items": [it.to_api() for it in self.store.mission()], "current_seq": self.store.mission_current_seq}

    def message_summaries(self) -> list[dict[str, Any]]:
        s = self.store
        return [
            {"name": n, "rate_hz": round(s.rate(n), 2), "age_s": round(s.age(n) or 0.0, 2), "count": s.count(n)}
            for n in s.names()
        ]

    def message_detail(self, msg: MavMessage) -> dict[str, Any]:
        return {
            "name": msg.name,
            "timestamp": msg.timestamp,
            "age_s": round(max(0.0, self.store.now() - msg.timestamp), 2),
            "rate_hz": round(self.store.rate(msg.name), 2),
            "sysid": msg.sysid,
            "compid": msg.compid,
            "fields": msg.fields,
            "converted": convert_fields(msg.name, msg.fields),
        }

    def _on_message(self, msg: MavMessage) -> None:
        if not self.clients:
            return
        now = time.monotonic()
        detail = None
        for c in list(self.clients):
            if msg.name in c.subscriptions and now - c.last_push.get(msg.name, 0.0) >= MESSAGE_PUSH_MIN_DT:
                c.last_push[msg.name] = now
                detail = detail or self.message_detail(msg)
                c.push({"type": "message", "data": detail})

    def _on_event(self, ev: Event) -> None:
        self._broadcast({"type": "event", "data": ev.to_dict()})

    def _on_mission(self, _items: list[MissionItem]) -> None:
        self._broadcast({"type": "mission", "data": self.mission_payload()})

    def _on_proposal(self, p: Proposal) -> None:
        self._broadcast({"type": "proposal", "data": p.to_dict()})

    async def _state_loop(self) -> None:
        last_seq = None
        while True:
            await asyncio.sleep(1.0 / STATE_HZ)
            if not self.clients:
                continue
            try:
                frame = self.state()
            except Exception:  # noqa: BLE001
                log.exception("state frame failed")
                continue
            self._broadcast({"type": "state", "data": frame})
            if frame["mission_current_seq"] != last_seq:
                last_seq = frame["mission_current_seq"]
                self._broadcast({"type": "mission", "data": self.mission_payload()})

    async def _summary_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if self.clients:
                self._broadcast({"type": "messages", "data": self.message_summaries()})
