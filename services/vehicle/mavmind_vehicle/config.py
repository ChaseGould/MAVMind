"""Load profiles (config/profiles/*.yaml) and safety limits (config/safety.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import config_dir


@dataclass
class Profile:
    name: str
    description: str
    source: dict[str, Any]
    service: dict[str, Any] = field(default_factory=dict)
    store: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @property
    def host(self) -> str:
        return str(self.service.get("host", "127.0.0.1"))

    @property
    def port(self) -> int:
        return int(self.service.get("port", 8700))

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "source": self.source.get("type")}


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def load_profile(name_or_path: str) -> Profile:
    p = Path(name_or_path)
    if not p.suffix:
        p = profiles_dir() / f"{name_or_path}.yaml"
    data = yaml.safe_load(p.read_text()) or {}
    if "source" not in data or "type" not in data["source"]:
        raise ValueError(f"{p}: profile needs a source.type")
    return Profile(
        name=data.get("name", p.stem),
        description=data.get("description", ""),
        source=dict(data["source"]),
        service=dict(data.get("service", {})),
        store=dict(data.get("store", {})),
        path=p,
    )


def list_profiles() -> list[Profile]:
    out = []
    for p in sorted(profiles_dir().glob("*.yaml")):
        try:
            out.append(load_profile(str(p)))
        except Exception:  # noqa: BLE001 - a broken profile shouldn't hide the others
            continue
    return out


def load_safety(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else config_dir() / "safety.yaml"
    return yaml.safe_load(p.read_text()) or {}
