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


# --- Probes de regresión del verificador independiente (B1/B2/B3) ---


def _write_raw(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_linea_json_no_objeto_es_linea_rota_no_crash(tmp_path):
    """B1: --verify reporta broken_line (no crashea) en líneas no-objeto."""
    from l2agent.audit import main, verify_audit
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    raw = log.read_text(encoding="utf-8").splitlines()
    for payload in ("null", "5", "[1,2]", '"hola"'):
        _write_raw(log, raw[0] + "\n" + payload + "\n")
        v = verify_audit(log)
        assert v["ok"] is False and v["broken_line"] == 2  # nunca raise
    # --seal sobre basura legada debe rechazar limpio, sin traceback
    _write_raw(log, '{"ts": "2026-01-01T00:00:00+00:00", "actor": "a", '
                    '"action": "x", "channel": "lab", "result": "ok", '
                    '"detail": {}}\n[1,2]\n')
    assert main([str(log), "--seal"]) != 0


def test_seal_y_verify_rechazan_since(tmp_path):
    """B2: --since no se ignora silenciosamente en --verify/--seal."""
    from l2agent.audit import main
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    assert main([str(log), "--verify", "--since", "2026-01-01"]) != 0
    assert main([str(log), "--seal", "--since", "2026-01-01"]) != 0


def test_append_concurrente_no_rompe_la_cadena(tmp_path):
    """B3: log_decision concurrente no produce cadena rota (lock real)."""
    import threading
    from l2agent.audit import verify_audit
    log = tmp_path / "audit.jsonl"
    barrier = threading.Barrier(2)

    def w(i):
        barrier.wait()
        log_decision(log, actor=f"t{i}", action="x", channel="lab",
                     result="ok")

    ts = [threading.Thread(target=w, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert verify_audit(log)["ok"] is True
