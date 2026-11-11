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


def test_informe_agrega_por_nivel(tmp_path):
    """P11: el informe de distribución por nivel agrega las trazas de routing."""
    from l2agent.audit import routing_report
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="ana", action="route", channel="lab",
                 result="L0", detail={"handler": "handle_estado", "text": "x"})
    log_decision(log, actor="ana", action="route", channel="lab",
                 result="L0", detail={"handler": "handle_estado", "text": "y"})
    log_decision(log, actor="juan", action="route", channel="mail",
                 result="L2", detail={"handler": "run_loop", "text": "z"})
    log_decision(log, actor="ana", action="respuesta_final", channel="lab",
                 result="ok")  # ruido: no es decisión de routing
    r = routing_report(log)
    assert r["total"] == 3
    assert r["levels"] == {"L0": 2, "L2": 1}
    assert r["handlers"] == {"handle_estado": 2, "run_loop": 1}
    assert r["actors"] == {"ana": 2, "juan": 1}
    r_mes = routing_report(log, since="2099-01-01")
    assert r_mes["total"] == 0
