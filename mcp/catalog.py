"""Loader/validator for the curated MCP tool catalog.

Thin lookup only: loads mcp/curated-tools.json once and answers
"may L2 request this tool?". No network, no MCP client here.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("curated-tools.json")

MIN_TOOLS = 15
MAX_TOOLS = 25

CALL_STYLE_PARAMS = "params"  # core tools: arguments = {"params": {...}}
CALL_STYLE_FLAT = "flat"  # extensions: arguments passed flat

# Substrings that never belong in a read-only curated list.
_WRITE_MARKERS = ("create", "update", "delete", "acknowledge", "login", "script")


def _catalog_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else CATALOG_PATH


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> dict[str, Any]:
    with open(path_str, encoding="utf-8") as fh:
        return json.load(fh)


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Load the curated catalog data (cached per path)."""
    return _load_cached(str(_catalog_path(path)))


def all_tools(path: str | Path | None = None) -> list[str]:
    """Every curated tool name, operator first then technician."""
    data = load_catalog(path)
    names: list[str] = []
    for role_tools in data["roles"].values():
        names.extend(entry["name"] for entry in role_tools)
    return names


def tools_for(role: str, path: str | Path | None = None) -> list[str]:
    """Tool names for one role ('operator' | 'technician')."""
    data = load_catalog(path)
    return [entry["name"] for entry in data["roles"][role]]


def role_of(tool_name: Any, path: str | Path | None = None) -> str | None:
    """Role owning the tool, or None when not curated."""
    if not isinstance(tool_name, str):
        return None
    data = load_catalog(path)
    for role, role_tools in data["roles"].items():
        if any(entry["name"] == tool_name for entry in role_tools):
            return role
    return None


def is_allowed(tool_name: Any, path: str | Path | None = None) -> bool:
    """Exact, case-sensitive membership check. Non-strings are rejected."""
    return role_of(tool_name, path) is not None


def call_style(tool_name: Any, path: str | Path | None = None) -> str | None:
    """'params' (wrapper) or 'flat' for curated tools, else None."""
    if not isinstance(tool_name, str):
        return None
    data = load_catalog(path)
    for role_tools in data["roles"].values():
        for entry in role_tools:
            if entry["name"] == tool_name:
                return entry["args"]
    return None


def validate_catalog(data: dict[str, Any] | None = None) -> int:
    """Check count bounds (15-25), uniqueness, and read-only shape.

    Returns the total tool count. Raises ValueError on violation.
    Hub existence is NOT checked (no network in this step).
    """
    data = data if data is not None else load_catalog()
    roles = data.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise ValueError("catalog needs a non-empty 'roles' mapping")
    names: list[str] = []
    for role, role_tools in roles.items():
        if not isinstance(role_tools, list) or not role_tools:
            raise ValueError(f"role {role!r} needs a non-empty tool list")
        for entry in role_tools:
            name = entry.get("name") if isinstance(entry, dict) else None
            args = entry.get("args") if isinstance(entry, dict) else None
            if not name or not isinstance(name, str):
                raise ValueError(f"role {role!r} has an entry without a name")
            if args not in (CALL_STYLE_PARAMS, CALL_STYLE_FLAT):
                raise ValueError(f"tool {name!r} needs args 'params' or 'flat'")
            lowered = name.lower()
            if lowered == "raw_api_call" or any(m in lowered for m in _WRITE_MARKERS):
                raise ValueError(f"tool {name!r} looks like a write/admin call")
            names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("catalog has duplicate tool names")
    if not (MIN_TOOLS <= len(names) <= MAX_TOOLS):
        raise ValueError(
            f"catalog holds {len(names)} tools, bounds are {MIN_TOOLS}-{MAX_TOOLS}"
        )
    return len(names)
