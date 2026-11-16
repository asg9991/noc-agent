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


def test_call_builds_flat_args_for_core_tools():
    t = _FakeTransport()
    c = MCPClient(bearer="x", transport=t)
    c.session_id = "sess-123"
    c.call_tool("problem_active_get", {"limit": 5})
    assert t.calls[0]["arguments"] == {"limit": 5}
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


# --- JD#2 info rows: SSE + initialize (A-2/A-5/B-1/B-2) ---


def test_sse_multiframe_devuelve_resultado_no_la_notificacion():
    """B-1: si después del resultado llega una notificación, la respuesta
    sigue siendo el resultado (antes: se tragaba y devolvía None)."""
    text = ('data: {"jsonrpc":"2.0","id":1,"result":{"tools":[1]}}\n\n'
            'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n')
    env = _extract_jsonrpc(text)
    assert env.get("result") == {"tools": [1]}


def test_sse_data_sin_espacio_y_multilinea():
    """A-5: 'data:{...}' (spec SSE) y campos data multi-línea se parsean."""
    assert _extract_jsonrpc('data:{"jsonrpc":"2.0","id":1,"result":5}'
                            )["result"] == 5
    multi = 'data: {"jsonrpc":"2.0","id":1,\ndata:  "result": 7}\n\n'
    assert _extract_jsonrpc(multi)["result"] == 7


def test_sse_solo_notificaciones_es_error_loud():
    """B-1: un stream sin envelope de respuesta NO devuelve None en
    silencio — falla loud."""
    with pytest.raises(RuntimeError):
        _extract_jsonrpc('data: {"jsonrpc":"2.0","method":"ping"}\n\n')


def test_initialize_no_traga_errores_jsonrpc():
    """B-2: un rechazo JSON-RPC del handshake debe disparar error (y el
    alarm de rotación), no devolver '' como si nada."""
    class _ErrTransport:
        def post(self, url, json=None, headers=None):
            body = {"jsonrpc": "2.0", "id": json["id"],
                    "error": {"code": -32001, "message": "unauthorized"}}
            return _FakeResp(json_lib_dumps(body))

    c = MCPClient(url="http://hub", transport=_ErrTransport())
    with pytest.raises(RuntimeError, match="unauthorized"):
        c.initialize()
