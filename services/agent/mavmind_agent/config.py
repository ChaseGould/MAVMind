"""Agent configuration: config/agent.yaml plus environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml


@cache
def repo_root() -> Path:
    env = os.environ.get("MAVMIND_ROOT")
    if env:
        return Path(env).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "shared" / "mission_schema.json").exists():
            return parent
    return Path.cwd()


def config_dir() -> Path:
    env = os.environ.get("MAVMIND_CONFIG")
    return Path(env).resolve() if env else repo_root() / "config"


@dataclass
class AgentConfig:
    model: str = "claude-opus-5-5"
    effort: str | None = "medium"
    max_tokens: int = 16000
    fallbacks: str | None = "default"
    max_tool_rounds: int = 25
    host: str = "127.0.0.1"
    port: int = 8701
    vehicle_url: str = "http://127.0.0.1:8700"
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    audit_log: str = "logs/agent_audit.jsonl"

    @property
    def readonly_mcp_url(self) -> str:
        return self.vehicle_url.rstrip("/") + "/mcp/readonly/"

    @property
    def command_mcp_url(self) -> str:
        return self.vehicle_url.rstrip("/") + "/mcp/command/"

    @property
    def audit_path(self) -> Path:
        p = Path(self.audit_log)
        return p if p.is_absolute() else repo_root() / p


def load_config(path: str | Path | None = None) -> AgentConfig:
    p = Path(path) if path else config_dir() / "agent.yaml"
    data: dict[str, Any] = yaml.safe_load(p.read_text()) if p.exists() else {}
    cfg = AgentConfig(**{k: v for k, v in (data or {}).items() if k in AgentConfig.__dataclass_fields__})
    if os.environ.get("MAVMIND_VEHICLE_URL"):
        cfg.vehicle_url = os.environ["MAVMIND_VEHICLE_URL"]
    if os.environ.get("MAVMIND_MODEL"):
        cfg.model = os.environ["MAVMIND_MODEL"]
    if os.environ.get("MAVMIND_AGENT_PORT"):
        cfg.port = int(os.environ["MAVMIND_AGENT_PORT"])
    return cfg
