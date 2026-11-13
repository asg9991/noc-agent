"""P25 — Integridad y tamper-evidence del audit: hash-chain ligera.

La verificación que exige el item: una modificación de una línea pasada
debe ser detectable. Cubre también borrado, inserción, el sello de
historia legada y los permisos del archivo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from l2agent.audit import log_decision, seal_audit, verify_audit


def _append_raw(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in
            path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_lines(path: Path, lines: list[dict]) -> None:
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n"
                            for x in lines), encoding="utf-8")


def test_cadena_intacta_verifica_ok(tmp_path):
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    log_decision(log, actor="a", action="y", channel="lab", result="ok")
    v = verify_audit(log)
    assert v["ok"] is True
    assert v["broken_line"] is None
    assert v["unsealed"] == 0
    assert v["sealed"] == 2


def test_modificacion_de_linea_pasada_es_detectada(tmp_path):
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    log_decision(log, actor="a", action="y", channel="lab", result="ok")
    lines = _read_lines(log)
    lines[0]["result"] = "denegado"  # reescribir la historia
    _write_lines(log, lines)
    v = verify_audit(log)
    assert v["ok"] is False
    assert v["broken_line"] == 1


def test_borrado_de_linea_es_detectado(tmp_path):
    log = tmp_path / "audit.jsonl"
    for i in range(3):
        log_decision(log, actor="a", action=f"x{i}", channel="lab",
                     result="ok")
    lines = _read_lines(log)
    del lines[1]  # borrar una decisión del medio
    _write_lines(log, lines)
    v = verify_audit(log)
    assert v["ok"] is False
    assert v["broken_line"] == 2


def test_insercion_de_linea_falsa_es_detectada(tmp_path):
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    log_decision(log, actor="a", action="z", channel="lab", result="ok")
    lines = _read_lines(log)
    lines.insert(1, {"ts": "2026-01-01T00:00:00+00:00", "actor": "intruso",
                     "action": "backdoor", "channel": "lab", "result": "ok",
                     "detail": {}})
    _write_lines(log, lines)
    v = verify_audit(log)
    assert v["ok"] is False
    assert v["broken_line"] == 2


def test_seal_migra_legado_preservando_contenido(tmp_path):
    log = tmp_path / "audit.jsonl"
    _append_raw(log, {"ts": "2026-01-01T00:00:00+00:00", "actor": "a",
                      "action": "x", "channel": "lab", "result": "ok",
                      "detail": {"k": 1}})
    assert verify_audit(log)["unsealed"] == 1
    seal_audit(log)
    v = verify_audit(log)
    assert v["ok"] is True
    assert v["unsealed"] == 0
    (line,) = _read_lines(log)
    assert line["actor"] == "a"
    assert line["action"] == "x"
    assert line["detail"] == {"k": 1}  # el contenido no se toca


def test_seal_se_niega_si_hay_cadena_rota(tmp_path):
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    log_decision(log, actor="a", action="y", channel="lab", result="ok")
    lines = _read_lines(log)
    lines[0]["result"] = "denegado"
    _write_lines(log, lines)
    with pytest.raises(ValueError):
        seal_audit(log)
    assert verify_audit(log)["ok"] is False  # la manipulación sigue ahí


def test_archivo_se_crea_con_permisos_600(tmp_path):
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    assert oct(log.stat().st_mode & 0o777) == "0o600"
