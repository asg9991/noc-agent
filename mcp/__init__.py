"""Curated MCP tool catalog (client side, read-only).

The hub (zabbix-mcp-server) exposes the catalog; this package only
declares which tools the orchestrator may request, split by role.
No network access here: pure data + validation.
Secrets are never stored in this package (see agent/config.py).
"""

from mcp.catalog import (
    CALL_STYLE_FLAT,
    CALL_STYLE_PARAMS,
    MAX_TOOLS,
    MIN_TOOLS,
    all_tools,
    call_style,
    is_allowed,
    load_catalog,
    role_of,
    tools_for,
    validate_catalog,
)

__all__ = [
    "CALL_STYLE_FLAT",
    "CALL_STYLE_PARAMS",
    "MAX_TOOLS",
    "MIN_TOOLS",
    "all_tools",
    "call_style",
    "is_allowed",
    "load_catalog",
    "role_of",
    "tools_for",
    "validate_catalog",
]
