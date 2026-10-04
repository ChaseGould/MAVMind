"""Proposal lifecycle: propose (LLM) -> validate (code) -> approve/reject (human, UI) -> upload -> readback diff.

The LLM can only reach `propose`. `approve` is called from the REST API that only the UI uses.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .audit import AuditLog
from .messages import MissionItem
from .validator import ValidationResult, VehicleContext, diff_missions, validate_mission


@dataclass
class Proposal:
    id: str
    created_at: float
    mission: Any
    validation: ValidationResult
    status: str  # invalid | pending | uploading | uploaded | upload_failed | rejected
    upload: dict[str, Any] | None = None
    reject_reason: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def items(self) -> list[MissionItem]:
        return self.validation.items

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "status": self.status,
            "mission": self.mission,
            "items": [it.to_api() for it in self.items[1:]],
            "validation": self.validation.to_dict(),
            "upload": self.upload,
            "reject_reason": self.reject_reason,
        }


class ProposalError(RuntimeError):
    pass


class ProposalManager:
    def __init__(
        self,
        limits: dict[str, Any],
        vehicle_context: Callable[[], VehicleContext],
        audit: AuditLog,
    ) -> None:
        self.limits = limits
        self.vehicle_context = vehicle_context
        self.audit = audit
        self._proposals: dict[str, Proposal] = {}
        self._listeners: list[Callable[[Proposal], None]] = []
        self._upload_lock = asyncio.Lock()

    def add_listener(self, cb: Callable[[Proposal], None]) -> None:
        self._listeners.append(cb)

    def _notify(self, p: Proposal) -> None:
        for cb in list(self._listeners):
            cb(p)

    def list(self) -> list[Proposal]:
        return sorted(self._proposals.values(), key=lambda p: p.created_at, reverse=True)

    def get(self, pid: str) -> Proposal:
        try:
            return self._proposals[pid]
        except KeyError:
            raise ProposalError(f"unknown proposal {pid}") from None

    def propose(self, mission: Any, origin: str = "llm") -> Proposal:
        result = validate_mission(mission, self.limits, self.vehicle_context())
        p = Proposal(
            id=uuid.uuid4().hex[:12],
            created_at=time.time(),
            mission=mission,
            validation=result,
            status="pending" if result.ok else "invalid",
        )
        self._proposals[p.id] = p
        self.audit.write(
            "proposal",
            id=p.id,
            origin=origin,
            status=p.status,
            mission=mission,
            failures=[c.name for c in result.failures()],
        )
        self._notify(p)
        return p

    def reject(self, pid: str, reason: str | None = None) -> Proposal:
        p = self.get(pid)
        if p.status not in ("pending", "invalid"):
            raise ProposalError(f"proposal {pid} is {p.status}; only pending or invalid proposals can be rejected")
        p.status = "rejected"
        p.reject_reason = reason
        self.audit.write("reject", id=pid, reason=reason)
        self._notify(p)
        return p

    async def approve(self, pid: str, source: Any) -> Proposal:
        """Human approval from the UI: re-validate, upload, read back, diff."""
        p = self.get(pid)
        if p.status != "pending":
            raise ProposalError(f"proposal {pid} is {p.status}; only pending proposals can be approved")
        if source is None or getattr(source, "read_only", False):
            raise ProposalError("the current link is read-only; nothing can be uploaded")
        async with self._upload_lock:
            # Re-validate against the vehicle's state now; it may have changed since the proposal.
            recheck = validate_mission(p.mission, self.limits, self.vehicle_context())
            if not recheck.ok:
                p.validation = recheck
                p.status = "invalid"
                self.audit.write("approve_blocked", id=pid, failures=[c.name for c in recheck.failures()])
                self._notify(p)
                raise ProposalError(
                    "mission no longer passes validation: " + "; ".join(c.message for c in recheck.failures())
                )
            p.validation = recheck
            p.status = "uploading"
            self.audit.write("approve", id=pid)
            self._notify(p)
            try:
                result = await source.upload_mission(p.items)
            except Exception as exc:  # noqa: BLE001
                result = None
                message = f"upload error: {exc}"
            else:
                message = result.message
            if result is None or not result.ok:
                p.status = "upload_failed"
                p.upload = {"ok": False, "message": message, "verified": False, "diff": []}
                self.audit.write("upload", id=pid, ok=False, message=message)
                self._notify(p)
                return p
            try:
                readback = await source.download_mission()
                diff = diff_missions(p.items, readback)
                verified = not diff
            except Exception as exc:  # noqa: BLE001
                readback, diff, verified = [], [f"readback failed: {exc}"], False
            p.status = "uploaded" if verified else "upload_failed"
            p.upload = {
                "ok": verified,
                "message": message if verified else "uploaded, but the readback does not match the approved mission",
                "verified": verified,
                "diff": diff,
            }
            self.audit.write("upload", id=pid, ok=verified, message=message, diff=diff, readback_count=len(readback))
            self._notify(p)
            p.history.append({"time": time.time(), "readback": [it.to_api() for it in readback]})
            return p
