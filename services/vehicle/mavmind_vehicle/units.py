"""Convert raw MAVLink fields to unit-suffixed names (degE7 -> degrees, mm -> m, ...)."""

from __future__ import annotations

import json
import math
from functools import cache
from typing import Any

from .paths import shared_dir


@cache
def unit_table() -> dict[str, dict[str, dict[str, Any]]]:
    data = json.loads((shared_dir() / "units.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _convert(value: Any, spec: dict[str, Any]) -> Any:
    invalid = spec.get("invalid", [])
    scale = spec.get("scale", 1)
    if isinstance(value, list):
        return [None if v in invalid else _scale(v, scale) for v in value]
    if value in invalid:
        return None
    return _scale(value, scale)


def _scale(value: Any, scale: float) -> Any:
    if not isinstance(value, (int, float)):
        return value
    out = value * scale
    if isinstance(out, float):
        if math.isnan(out) or math.isinf(out):
            return None
        out = round(out, 7)
    return out


def convert_fields(message: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Return fields with scaled MAVLink integers converted and units in the names."""
    table = unit_table().get(message, {})
    out: dict[str, Any] = {}
    for key, value in fields.items():
        spec = table.get(key)
        if spec is None:
            out[key] = None if isinstance(value, float) and (math.isnan(value) or math.isinf(value)) else value
        else:
            out[spec["name"]] = _convert(value, spec)
    return out


def converted_name(message: str, field: str) -> str:
    spec = unit_table().get(message, {}).get(field)
    return spec["name"] if spec else field


def raw_field_for(message: str, name: str) -> tuple[str, dict[str, Any] | None]:
    """Map a field name (raw or converted) to (raw_field, spec)."""
    table = unit_table().get(message, {})
    if name in table:
        return name, table[name]
    for raw, spec in table.items():
        if spec["name"] == name:
            return raw, spec
    return name, None


def field_value(message: str, fields: dict[str, Any], name: str) -> Any:
    """Read one field by raw or converted name, applying the conversion."""
    raw, spec = raw_field_for(message, name)
    if raw not in fields:
        return None
    value = fields[raw]
    return _convert(value, spec) if spec else value
