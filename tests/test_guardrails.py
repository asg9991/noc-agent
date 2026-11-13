"""Guardrails tests: reglas sin red, audit a tmp_path."""

import pytest

from l2agent import guardrails
from l2agent.guardrails import classify, denied, require_confirmation


def test_classify_permite_curada():
    assert classify("problem_active_get") is None
    assert classify("report_generate") is None


def test_classify_detecta_intento_de_write():
    assert classify("host_create") == "write_attempt"
    assert classify("event_acknowledge") == "write_attempt"
    assert classify("raw_api_call") == "write_attempt"


def test_classify_marca_desconocida():
    assert classify("herramienta_inventada") == "unknown_tool"


def test_denied_registra_y_avisa_al_hook(tmp_path):
    log = tmp_path / "audit.jsonl"
    avisos = []
    record = denied(
        "host_create", actor="l2", channel="lab", audit_path=log,
        on_denied=avisos.append,
    )
    assert record["result"] == "denegado"
    assert record["detail"]["reason"] == "write_attempt"
    assert avisos == [record]  # el hook recibe el registro para alarmar
    assert log.exists()  # quedó en el audit


def test_denied_sin_hook_no_rompe(tmp_path):
    log = tmp_path / "audit.jsonl"
    record = denied("x", actor="l2", channel="lab", audit_path=log)
    assert record["result"] == "denegado"


def test_hook_roto_no_abre_el_freno(tmp_path):
    log = tmp_path / "audit.jsonl"

    def hook_malo(record):
        raise RuntimeError("smtp caído")

    record = denied(
        "host_delete", actor="l2", channel="lab", audit_path=log,
        on_denied=hook_malo,
    )
    assert record["result"] == "denegado"  # la alarma falló, el freno no
    assert log.exists()


def test_write_sin_confirmacion_se_frena_y_registra(tmp_path):
    log = tmp_path / "audit.jsonl"
    avisos = []
    with pytest.raises(PermissionError):
        require_confirmation(
            "event_acknowledge", actor="l2", channel="lab", audit_path=log,
            on_denied=avisos.append,
        )
    assert len(avisos) == 1
    assert avisos[0]["result"] == "denegado"


def test_write_confirmado_pasa_y_queda_auditado(tmp_path):
    log = tmp_path / "audit.jsonl"
    avisos = []
    assert require_confirmation(
        "event_acknowledge", confirmed=True, actor="tecnico",
        channel="lab", audit_path=log, on_denied=avisos.append,
    ) is True
    assert avisos == []  # autorizado: no hay alarma, pero sí auditoría
    assert "confirmado" in log.read_text(encoding="utf-8")


def test_guardrails_no_duplica_lista_de_prohibidos():
    # La fuente de lo prohibido vive en mcp/catalog.py; acá solo se referencia.
    from mcp import catalog

    assert guardrails._WRITE_MARKERS is catalog._WRITE_MARKERS
