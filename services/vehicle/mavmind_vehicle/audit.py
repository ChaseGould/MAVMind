"""Append-only JSONL audit log: tool calls, proposals, approvals, uploads, vehicle actions."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .paths import resolve


class AuditLog:
    def __init__(self, path: str | Path = "logs/vehicle_audit.jsonl") -> None:
        self.path = resolve(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, kind: str, **data: Any) -> None:
        record = {"time": time.time(), "kind": kind, **data}
        line = json.dumps(record, default=str, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
