"""Append-only JSONL audit log for the agent: user messages, tool calls, results, proposals."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, kind: str, **data: Any) -> None:
        record = {"time": time.time(), "kind": kind, **data}
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
