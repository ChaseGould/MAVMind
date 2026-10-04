from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path

import pytest

from mavmind_vehicle.sources.replay import iter_tlog
from mavmind_vehicle.store import TelemetryStore

TLOG = Path(__file__).parent / "tlogs" / "battery_failsafe.tlog"
EXPECTED = json.loads((Path(__file__).parent / "tlogs" / "battery_failsafe.expected.json").read_text())


@pytest.fixture(scope="session")
def expected() -> dict:
    return EXPECTED


@pytest.fixture(scope="session")
def tlog_messages() -> list:
    return list(iter_tlog(TLOG))


def store_until(messages: list, t_rel: float | None = None) -> TelemetryStore:
    """A replay store fed up to t_rel seconds into the log (None = whole log)."""
    store = TelemetryStore(live=False)
    cutoff = None if t_rel is None else EXPECTED["start_time"] + t_rel
    for m in messages:
        if cutoff is not None and m.timestamp > cutoff:
            break
        store.ingest(m)
    return store


@pytest.fixture
def full_store(tlog_messages) -> TelemetryStore:
    return store_until(tlog_messages)


@dataclass
class Ctx:
    store: TelemetryStore
    source: object | None = None
    source_label: str = "replay:test"


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
