"""Retención y rotación de artefactos con datos del cliente (P9).

Política bajo prueba: todo artefacto con datos del cliente en claro tiene
vida acotada — audit rota por tamaño y poda por edad, outbox poda por edad,
watch.db poda sweeps viejos e observaciones inactivas viejas. La regla dura:
una observación activa jamás se borra (si no, el problema volvería a sonar
como NUEVO).
"""

from __future__ import annotations

import json
import sqlite3
import time

from l2agent import retention, watch

NOW = time.time()
DAY = 86400.0


def _audit_line(ts_iso: str) -> str:
    return json.dumps({"ts": ts_iso, "actor": "l2", "action": "x",
                       "channel": "lab", "result": "ok", "detail": {}})


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def test_prune_audit_borra_lineas_viejas_y_conserva_recientes(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text(
        _audit_line(_iso(NOW - 200 * DAY)) + "\n"
        + _audit_line(_iso(NOW - 10 * DAY)) + "\n"
        + _audit_line(_iso(NOW)) + "\n",
        encoding="utf-8")

    r = retention.prune_audit(log, max_age_days=90, now=NOW)

    left = log.read_text(encoding="utf-8").splitlines()
    assert len(left) == 2
    assert r == {"kept": 2, "dropped": 1, "rotated": None, "files_removed": 0}


def test_prune_audit_conserva_lineas_no_parseables(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("esto no es json\n"
                   + _audit_line(_iso(NOW)) + "\n", encoding="utf-8")

    r = retention.prune_audit(log, max_age_days=90, now=NOW)

    assert log.read_text(encoding="utf-8").splitlines()[0] == "esto no es json"
    assert r["kept"] == 2 and r["dropped"] == 0


def test_prune_audit_rota_por_tamano_y_conserva_historial(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")

    r = retention.prune_audit(log, max_age_days=90, max_bytes=10, now=NOW)

    rotated = list(tmp_path.glob("audit.jsonl.2*"))
    assert r["rotated"] is not None and len(rotated) == 1
    # el histórico completo queda en el rotado; el actual arranca vacío
    assert rotated[0].read_text(encoding="utf-8").count("\n") == 1
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_prune_audit_respeta_tope_de_archivos_rotados(tmp_path):
    for i in range(3):
        (tmp_path / f"audit.jsonl.2026010{i + 1}T000000Z").write_text(
            _audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")

    r = retention.prune_audit(log, max_age_days=90, max_bytes=10,
                              keep_rotated=2, now=NOW)

    left = sorted(p.name for p in tmp_path.glob("audit.jsonl.2*"))
    assert len(left) == 2 and left[-1] == r["rotated"]
    assert r["files_removed"] == 2  # 3 previos + el propio actual rotado → 4, quedan 2


def test_prune_outbox_poda_lineas_y_cooldown(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    with outbox.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": NOW - 200 * DAY, "kind": "alarma",
                             "eventid": "viejo"}) + "\n")
        fh.write(json.dumps({"ts": NOW - 10 * DAY, "kind": "alarma",
                             "eventid": "reciente"}) + "\n")
    cpath = tmp_path / "outbox.jsonl.cooldown.json"
    cpath.write_text(json.dumps({"viejo": NOW - 200 * DAY,
                                 "reciente": NOW}), encoding="utf-8")

    r = retention.prune_outbox(outbox, max_age_days=90, now=NOW)

    assert r == {"kept": 1, "dropped": 1, "cooldown_dropped": 1}
    assert "reciente" in outbox.read_text(encoding="utf-8")
    assert "viejo" not in outbox.read_text(encoding="utf-8")
    assert json.loads(cpath.read_text(encoding="utf-8")) == {"reciente": NOW}


def test_prune_db_nunca_borra_observaciones_activas(tmp_path):
    db = tmp_path / "watch.db"
    conn = sqlite3.connect(db)
    conn.executescript(watch.SCHEMA)
    conn.execute(
        "INSERT INTO observations (eventid, host, severity, first_seen,"
        " last_seen, status) VALUES ('vivo', 'h', 'High', ?, ?, 'active')",
        (NOW - 400 * DAY, NOW - 400 * DAY))
    conn.execute(
        "INSERT INTO observations (eventid, host, severity, first_seen,"
        " last_seen, status) VALUES ('muerto', 'h', 'High', ?, ?,"
        " 'inactive')", (NOW - 400 * DAY, NOW - 400 * DAY))
    conn.commit()
    conn.close()

    r = retention.prune_db(db, max_age_days=90, now=NOW)

    conn = sqlite3.connect(db)
    left = {row[0] for row in conn.execute(
        "SELECT eventid FROM observations")}
    conn.close()
    assert left == {"vivo"}
    assert r == {"sweeps_dropped": 0, "observations_dropped": 1}


def test_prune_db_poda_sweeps_viejos(tmp_path):
    db = tmp_path / "watch.db"
    conn = sqlite3.connect(db)
    conn.executescript(watch.SCHEMA)
    for age in (200 * DAY, 10 * DAY):
        conn.execute(
            "INSERT INTO sweeps (ts, active_count) VALUES (?, 1)",
            (NOW - age,))
    conn.commit()
    conn.close()

    r = retention.prune_db(db, max_age_days=90, now=NOW)

    assert r == {"sweeps_dropped": 1, "observations_dropped": 0}


def test_archivos_ausentes_no_fallan(tmp_path):
    assert retention.prune_audit(tmp_path / "no.jsonl", now=NOW)["kept"] == 0
    assert retention.prune_outbox(tmp_path / "no.jsonl", now=NOW)["kept"] == 0
    assert retention.prune_db(tmp_path / "no.db", now=NOW) == {
        "sweeps_dropped": 0, "observations_dropped": 0}


def test_main_de_punta_a_punta(tmp_path, capsys):
    """El procedimiento completo: un solo comando poda los tres artefactos."""
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW - 200 * DAY)) + "\n"
                   + _audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps({"ts": NOW - 200 * DAY, "kind": "alarma",
                                  "eventid": "viejo"}) + "\n",
                      encoding="utf-8")
    db = tmp_path / "watch.db"
    conn = sqlite3.connect(db)
    conn.executescript(watch.SCHEMA)
    conn.execute("INSERT INTO sweeps (ts, active_count) VALUES (?, 0)",
                 (NOW - 200 * DAY,))
    conn.commit()
    conn.close()

    rc = retention.main(["--audit", str(log), "--outbox", str(outbox),
                         "--db", str(db), "--days", "90", "--now", str(NOW)])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["audit"]["dropped"] == 1
    assert report["outbox"]["dropped"] == 1
    assert report["db"]["sweeps_dropped"] == 1
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
