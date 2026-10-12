"""Audit tests: log JSONL append-only, sin red, con tmp_path."""

import json

from l2agent.audit import log_decision


def test_registro_lleva_quien_que_cuando_y_resultado(tmp_path):
    log = tmp_path / "audit.jsonl"
    record = log_decision(
        log, actor="guardia", action="consultar_problemas", channel="lab", result="ok"
    )
    assert record["actor"] == "guardia"
    assert record["action"] == "consultar_problemas"
    assert record["channel"] == "lab"
    assert record["result"] == "ok"
    assert "ts" in record  # cuándo, ISO-8601
    lineas = log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lineas) == 1
    assert json.loads(lineas[0])["action"] == "consultar_problemas"


def test_segunda_llamada_agrega_sin_reescribir(tmp_path):
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="primera", channel="lab", result="ok")
    log_decision(
        log, actor="a", action="segunda", channel="lab", result="error",
        detail={"motivo": "timeout al hub"},
    )
    lineas = log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lineas) == 2
    segunda = json.loads(lineas[1])
    assert segunda["result"] == "error"
    assert segunda["detail"] == {"motivo": "timeout al hub"}
