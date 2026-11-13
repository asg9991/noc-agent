"""Tools tests: superficie angosta del L2, sin red.

El gate de escritura se prueba contra el MCPClient real sin transporte:
el PermissionError salta antes de tocar la red. El resto usa cliente fake.
"""

import json

import pytest

from agent.mcp_client import MCPClient
from l2agent.tools import MAX_RESULTS, list_available, run


class FakeMCP:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def call_tool(self, name, args=None):
        self.calls.append((name, args or {}))
        if self.error is not None:
            raise self.error
        return self.payload


def test_list_available_respeta_roles():
    ops = list_available("operator")
    assert "problem_active_get" in ops
    assert "report_generate" not in ops  # esa es de technician
    techs = list_available("technician")
    assert "report_generate" in techs


def test_run_frena_write_antes_de_la_red():
    client = MCPClient(bearer="fake-sin-red")  # gate salta antes de transport
    with pytest.raises(PermissionError):
        run(client, "host_create", {"host": "x"})
    with pytest.raises(PermissionError):
        run(client, "raw_api_call", {"method": "host.create"})


def test_run_trunca_listas_largas_y_avisa():
    fake = FakeMCP(payload=[{"id": i} for i in range(100)])
    out = run(fake, "history_get", {"hostid": "1"}, limit=10)
    primera, aviso = out.split("\n")
    assert len(json.loads(primera)) == 10
    assert "90 más" in aviso


def test_run_respeta_limite_por_defecto():
    assert MAX_RESULTS == 50
    fake = FakeMCP(payload=list(range(60)))
    out = run(fake, "history_get", {})
    assert len(json.loads(out.split("\n")[0])) == 50


def test_run_normaliza_error_de_transporte_a_texto():
    fake = FakeMCP(error=RuntimeError("hub caído"))
    out = run(fake, "problem_active_get", {})
    assert out.startswith("error:")
    assert "hub caído" in out


def test_run_deja_pasar_resultado_chico_intacto():
    fake = FakeMCP(payload={"version": "7.4.13"})
    out = run(fake, "host_get", {"hostid": "1"})
    assert json.loads(out) == {"version": "7.4.13"}
    assert fake.calls == [("host_get", {"hostid": "1"})]


def test_run_marca_el_truncado_por_caracteres():
    from l2agent.tools import MAX_CHARS

    fake = FakeMCP(payload="x" * (MAX_CHARS + 1000))
    out = run(fake, "history_get", {})
    assert out.splitlines()[0] == "x" * MAX_CHARS
    assert "1000 caracteres afuera" in out  # nunca truncado en silencio
