"""Locate the repo's shared/ and config/ directories."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path


@cache
def repo_root() -> Path:
    env = os.environ.get("MAVMIND_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared" / "mission_schema.json").exists():
            return parent
    return Path.cwd()


def shared_dir() -> Path:
    return repo_root() / "shared"


def config_dir() -> Path:
    env = os.environ.get("MAVMIND_CONFIG")
    return Path(env).resolve() if env else repo_root() / "config"


def resolve(path: str | os.PathLike[str]) -> Path:
    """Resolve a config-relative path against the repo root."""
    p = Path(path)
    return p if p.is_absolute() else repo_root() / p
