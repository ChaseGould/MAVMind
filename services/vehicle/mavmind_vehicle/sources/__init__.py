"""TelemetrySource adapters. Nothing above this package knows which link is in use."""

from __future__ import annotations

from typing import Any

from .base import BaseSource, SourceError, TelemetrySource


def create_source(cfg: dict[str, Any]) -> BaseSource:
    """Build a source from a profile's `source:` block."""
    kind = cfg.get("type")
    if kind == "mavlink":
        from .mavlink import MavlinkSource

        return MavlinkSource(**{k: v for k, v in cfg.items() if k != "type"})
    if kind == "replay":
        from .replay import ReplaySource

        return ReplaySource(**{k: v for k, v in cfg.items() if k != "type"})
    if kind == "mavros":
        from .mavros import MavrosSource

        return MavrosSource(**{k: v for k, v in cfg.items() if k != "type"})
    raise ValueError(f"unknown source type: {kind!r}")


__all__ = ["BaseSource", "SourceError", "TelemetrySource", "create_source"]
