"""Thin MCP client tests: transport fakes only, no network."""

import json

import pytest

from agent.mcp_client import MCPClient, _extract_jsonrpc


class _FakeResp:
    def __init__(self, text, headers=None, status=200):
        self.text = text
        self.headers = headers or {}
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")


class _FakeTransport:
    """Records bodies, answers initialize/list/call from canned data."""

    def __init__(self):
        self.bodies = []
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.bodies.append(json)
        method = (json or {}).get("method")
        if method == "initialize":
            body = {"jsonrpc": "2.0", "id": json["id"], "result": {"capabilities": {}}}
            return _FakeResp(
                "data: " + json_lib_dumps(body),
                headers={"mcp-session-id": "sess-123"},
            )
        if method == "tools/list":
            assert headers.get("Mcp-Session-Id") == "sess-123"
            body = {
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {"tools": [{"name": "problem_active_get"}]},
            }
            return _FakeResp("data: " + json_lib_dumps(body))
        if method == "tools/call":
            self.calls.append(json["params"])
            body = {
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
            return _FakeResp(json_lib_dumps(body))
        raise AssertionError(f"unexpected method {method!r}")


def json_lib_dumps(obj):
    return json.dumps(obj)


def test_extract_jsonrpc_plain_and_sse():
    assert _extract_jsonrpc('{"jsonrpc":"2.0","result":{}}')["jsonrpc"] == "2.0"
    sse = 'event: message\ndata: {"jsonrpc":"2.0","result":{"tools":[]}}\n\n'
    assert _extract_jsonrpc(sse)["result"] == {"tools": []}


def test_initialize_stores_session_and_lists():
    t = _FakeTransport()
    c = MCPClient(bearer="x", transport=t)
    assert c.initialize() == "sess-123"
    assert c.list_tools() == [{"name": "problem_active_get"}]


def test_call_builds_params_wrapper_for_core_tools():
    t = _FakeTransport()
    c = MCPClient(bearer="x", transport=t)
    c.session_id = "sess-123"
    c.call_tool("problem_active_get", {})
    assert t.calls[0]["arguments"] == {"params": {}}
    assert t.calls[0]["name"] == "problem_active_get"


def test_call_builds_flat_args_for_extensions():
    t = _FakeTransport()
    c = MCPClient(bearer="x", transport=t)
    c.session_id = "sess-123"
    c.call_tool("anomaly_detect", {"host": "h1"})
    assert t.calls[0]["arguments"] == {"host": "h1"}


def test_gate_blocks_writes_before_network():
    t = _FakeTransport()
    c = MCPClient(bearer="x", transport=t)
    c.session_id = "sess-123"
    for bad in ("host_create", "raw_api_call", "event_acknowledge", "HOST_GET"):
        with pytest.raises(PermissionError):
            c.call_tool(bad, {})
    assert t.calls == []  # nothing left the process
    assert all(b.get("method") != "tools/call" for b in t.bodies)
