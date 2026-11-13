"""Bearer del hub: cadena de resolución sin nunca imprimirlo (P13).

Prioridad: explícito > env MCP_BEARER > archivo (env MCP_BEARER_FILE o el
default de lab /tmp/.mcp_bearer). En producción el archivo se ubica en
$XDG_RUNTIME_DIR o el home del servicio, con 600 — ver runbook §4.
"""

from __future__ import annotations

from agent import mcp_client


def test_bearer_file_env_apunta_a_otra_ubicacion(tmp_path, monkeypatch):
    """P13: producción puede vivir fuera de /tmp vía MCP_BEARER_FILE."""
    bear = tmp_path / "runtime" / "mcp_bearer"
    bear.parent.mkdir()
    bear.write_text("secreto-prod\n", encoding="utf-8")
    monkeypatch.delenv("MCP_BEARER", raising=False)
    monkeypatch.setenv("MCP_BEARER_FILE", str(bear))
    assert mcp_client.resolve_bearer() == "secreto-prod"


def test_default_de_lab_sigue_siendo_tmp(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_BEARER", raising=False)
    monkeypatch.delenv("MCP_BEARER_FILE", raising=False)
    bear = tmp_path / "mcp_bearer"
    bear.write_text("secreto-lab", encoding="utf-8")
    monkeypatch.setattr(mcp_client, "BEARER_FILE", bear)
    assert mcp_client.resolve_bearer() == "secreto-lab"


def test_prioridad_explicito_env_archivo(tmp_path, monkeypatch):
    bear = tmp_path / "mcp_bearer"
    bear.write_text("del-archivo", encoding="utf-8")
    monkeypatch.setattr(mcp_client, "BEARER_FILE", bear)
    monkeypatch.setenv("MCP_BEARER", "del-env")
    assert mcp_client.resolve_bearer("del-explicito") == "del-explicito"
    assert mcp_client.resolve_bearer() == "del-env"
    monkeypatch.delenv("MCP_BEARER")
    monkeypatch.setenv("MCP_BEARER_FILE", str(bear))
    assert mcp_client.resolve_bearer() == "del-archivo"


def test_sin_bearer_nunca_falla_devuelve_vacio(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_BEARER", raising=False)
    monkeypatch.setenv("MCP_BEARER_FILE", str(tmp_path / "no-existe"))
    assert mcp_client.resolve_bearer() == ""
