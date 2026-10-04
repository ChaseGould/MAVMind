"""The TelemetrySource interface and shared plumbing for adapters."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Protocol, runtime_checkable

from pymavlink import mavutil

from ..messages import MavMessage, MissionItem, UploadResult

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


@runtime_checkable
class TelemetrySource(Protocol):
    async def connect(self) -> None: ...
    def on_message(self, cb: Callable[[MavMessage], None]) -> None: ...
    async def get_params(self, names: list[str]) -> dict[str, float]: ...
    async def download_mission(self) -> list[MissionItem]: ...
    # used only by the approve flow and UI buttons, never by the LLM
    async def upload_mission(self, items: list[MissionItem]) -> UploadResult: ...
    async def set_mode(self, mode: str) -> bool: ...
    async def arm(self, armed: bool) -> bool: ...


def is_prefix(name: str) -> bool:
    return name.endswith("_") or name.endswith("*")


def match_params(params: dict[str, float], names: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for n in names:
        if is_prefix(n):
            prefix = n.rstrip("*").upper()
            out.update({k: v for k, v in params.items() if k.startswith(prefix)})
        elif n.upper() in params:
            out[n.upper()] = params[n.upper()]
    return dict(sorted(out.items()))


class BaseSource:
    """Callback fan-out, a waiter mechanism for request/response protocols, and vehicle bookkeeping."""

    source_type = "base"
    is_live = True
    read_only = False

    def __init__(self) -> None:
        self._callbacks: list[Callable[[MavMessage], None]] = []
        self._waiters: list[tuple[Callable[[MavMessage], bool], asyncio.Future[MavMessage]]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.params: dict[str, float] = {}
        self.param_count: int | None = None
        self.target_system: int = 1
        self.target_component: int = 1
        self.mav_type: int | None = None
        self.connected = False
        self.last_error: str | None = None

    def on_message(self, cb: Callable[[MavMessage], None]) -> None:
        self._callbacks.append(cb)

    async def close(self) -> None:
        self.connected = False

    # Adapters call this on the event loop thread for every decoded message.
    def _dispatch(self, msg: MavMessage) -> None:
        f = msg.fields
        if msg.name == "HEARTBEAT" and f.get("autopilot") not in (None, 8) and f.get("type") != 6:
            self.target_system, self.target_component = msg.sysid, msg.compid
            self.mav_type = f.get("type")
        elif msg.name == "PARAM_VALUE":
            self.params[str(f.get("param_id", "")).strip("\x00")] = float(f.get("param_value", 0.0))
            self.param_count = f.get("param_count")
        for pred, fut in list(self._waiters):
            if not fut.done():
                try:
                    if pred(msg):
                        fut.set_result(msg)
                except Exception:  # noqa: BLE001
                    log.exception("waiter predicate failed")
        self._waiters = [(p, f) for p, f in self._waiters if not f.done()]
        for cb in self._callbacks:
            try:
                cb(msg)
            except Exception:  # noqa: BLE001
                log.exception("message callback failed")

    def _dispatch_threadsafe(self, msg: MavMessage) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._dispatch, msg)

    def _waiter(self, pred: Callable[[MavMessage], bool]) -> asyncio.Future[MavMessage]:
        fut: asyncio.Future[MavMessage] = asyncio.get_running_loop().create_future()
        self._waiters.append((pred, fut))
        return fut

    async def _request(
        self,
        send: Callable[[], Any],
        pred: Callable[[MavMessage], bool],
        timeout: float = 2.0,
        retries: int = 3,
    ) -> MavMessage:
        """Send, then wait for a matching reply; resend on timeout."""
        for attempt in range(retries):
            fut = self._waiter(pred)
            send()
            try:
                return await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                log.debug("request timed out (attempt %d/%d)", attempt + 1, retries)
        raise SourceError("no reply from vehicle")

    async def wait_heartbeat(self, timeout: float = 30.0) -> bool:
        fut = self._waiter(
            lambda m: m.name == "HEARTBEAT" and m.fields.get("autopilot") != 8 and m.fields.get("type") != 6
        )
        try:
            await asyncio.wait_for(fut, timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def mode_mapping(self) -> dict[str, int]:
        if self.mav_type is None:
            return {}
        return mavutil.mode_mapping_byname(self.mav_type) or {}

    def available_modes(self) -> list[str]:
        mapping = self.mode_mapping()
        return sorted(mapping, key=lambda m: mapping[m])
