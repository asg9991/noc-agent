"""Thin MCP client for L2 (read-only, lab).

Talks to the initMAX zabbix-mcp hub over streamable HTTP. The curated
allowlist in mcp/catalog.py is the gate: anything not listed never leaves
this process (PermissionError). No bearer is ever logged or persisted.

Lab: base_url http://127.0.0.1:8080/mcp, bearer from MCP_BEARER env or
/tmp/.mcp_bearer (600, outside the repo). Prod: same shape against the
dedicated VM over LAN/tunnel.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from mcp.catalog import call_style, is_allowed

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_MCP_URL = "http://127.0.0.1:8080/mcp"
BEARER_FILE = Path("/tmp/.mcp_bearer")

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def resolve_bearer(explicit: str = "") -> str:
    """Bearer without ever printing it. Explicit > env > /tmp file."""
    if explicit:
        return explicit
    env = os.getenv("MCP_BEARER", "").strip()
    if env:
        return env
    try:
        return BEARER_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _extract_jsonrpc(text: str) -> dict[str, Any]:
    """Parse plain JSON or SSE (data: {...}) frames into the envelope."""
    text = text.strip()
    if not text:
        raise RuntimeError("Empty MCP response")
    if text.startswith("{"):
        return json.loads(text)
    payload = ""
    for line in text.splitlines():
        if line.startswith("data: "):
            payload = line[len("data: "):]
    if not payload:
        raise RuntimeError("Unrecognized MCP response shape")
    return json.loads(payload)


class MCPClient:
    """Stateful streamable-HTTP client (initialize -> session header)."""

    def __init__(
        self,
        url: str = DEFAULT_MCP_URL,
        bearer: str = "",
        timeout: float = 15.0,
        transport: Any | None = None,
    ) -> None:
        self.url = url
        self._bearer = resolve_bearer(bearer)
        self.timeout = timeout
        self._transport = transport
        self.session_id: str | None = None
        self._rpc_id = 0

    def _headers(self) -> dict[str, str]:
        headers = dict(_BASE_HEADERS)
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        if self._transport is not None:
            return self._transport.post(self.url, json=body, headers=self._headers())
        with httpx.Client(timeout=self.timeout) as http:
            return http.post(self.url, json=body, headers=self._headers())

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        self._rpc_id += 1
        resp = self._post(
            {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params}
        )
        resp.raise_for_status()
        envelope = _extract_jsonrpc(resp.text)
        if "error" in envelope:
            raise RuntimeError(f"MCP error: {envelope['error']}")
        return envelope.get("result")

    def initialize(self) -> str:
        """Handshake; stores the Mcp-Session-Id for later calls."""
        self._rpc_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "noc-agent-mcp-client", "version": "0.1"},
            },
        }
        if self._transport is not None:
            resp = self._transport.post(self.url, json=body, headers=self._headers())
        else:
            with httpx.Client(timeout=self.timeout) as http:
                resp = http.post(self.url, json=body, headers=self._headers())
        resp.raise_for_status()
        session = resp.headers.get("mcp-session-id") or resp.headers.get(
            "Mcp-Session-Id"
        )
        if session:
            self.session_id = session
        _extract_jsonrpc(resp.text)  # validate shape, ignore capabilities
        return self.session_id or ""

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._rpc("tools/list", {}) or {}
        return list(result.get("tools", []))

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Call one curated tool. Non-curated names never hit the network."""
        if not is_allowed(name):
            raise PermissionError(f"Tool {name!r} not in curated catalog")
        style = call_style(name)
        arguments = dict(args or {}) if style == "flat" else {"params": dict(args or {})}
        return self._rpc("tools/call", {"name": name, "arguments": arguments})
