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


# --- Probes de regresión (verificación independiente de P9, commit 021f5fd) ---


def test_corte_estricto_observaciones_y_activas_jamas(tmp_path):
    """R1/S2 · req1+req3: ts==cutoff se conserva (estricto <); active jamás se borra."""
    cut = NOW - 90 * DAY
    db = tmp_path / "watch.db"
    conn = sqlite3.connect(db)
    conn.executescript(watch.SCHEMA)
    for eid, status, ls in [("acut", "active", cut), ("icut", "inactive", cut),
                            ("icut1", "inactive", cut - 1),
                            ("a400", "active", NOW - 400 * DAY),
                            ("aepoch", "active", 0.0)]:
        conn.execute("INSERT INTO observations (eventid, host, severity, first_seen,"
                     " last_seen, status) VALUES (?, 'h', 'High', ?, ?, ?)",
                     (eid, ls, ls, status))
    conn.commit()
    conn.close()
    r = retention.prune_db(db, max_age_days=90, now=NOW)
    conn = sqlite3.connect(db)
    left = {row[0] for row in conn.execute("SELECT eventid FROM observations")}
    conn.close()
    assert r == {"sweeps_dropped": 0, "observations_dropped": 1}
    assert left == {"acut", "icut", "a400", "aepoch"}


def test_regla_dura_payoff_no_realarma_como_nuevo(tmp_path):
    """S6a · req3: la fila active de 400d sobrevive y evita el re-alarma NUEVO."""
    class Fake:
        def __init__(self, payload):
            self.payload = payload

        def call_tool(self, name, args=None):
            return self.payload

    p = {"eventid": "e1", "host": "h1", "severity": "High"}
    db = tmp_path / "watch.db"
    watch.sweep(Fake([p]), db, now=NOW - 400 * DAY)
    r = retention.prune_db(db, max_age_days=90, now=NOW)
    assert r["observations_dropped"] == 0
    r1 = watch.sweep(Fake([p]), db, now=NOW)
    assert r1["new"] == [] and [x["eventid"] for x in r1["recurrent"]] == ["e1"]


def test_rotados_de_log_con_nombre_custom_se_gestionan(tmp_path):
    """S5h · req2: --audit con otro nombre aplica edad y tope también a sus rotados."""
    log = tmp_path / "custom.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    (tmp_path / "custom.jsonl.20260101T000000Z").write_text(
        _audit_line(_iso(NOW - 200 * DAY)) + "\n", encoding="utf-8")
    (tmp_path / "custom.jsonl.20260102T000000Z").write_text(
        _audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    retention.prune_audit(log, max_age_days=90, max_bytes=10, keep_rotated=1,
                          now=NOW)
    en_disco = "".join(p.read_text(encoding="utf-8")
                       for p in tmp_path.glob("custom.jsonl*"))
    rotados = [p for p in tmp_path.glob("custom.jsonl.*")]
    assert _iso(NOW - 200 * DAY) not in en_disco, \
        "la línea vencida del rotado debe podarse"
    assert len(rotados) <= 1, \
        "el tope --keep debe aplicar también al log con nombre custom"


def test_reporte_lo_conservado_igual_a_lo_que_queda_tras_desborde(tmp_path):
    """S3b/R5 · req6: tras desborde del tope el reporte reconcilia con el final."""
    for i in range(3):
        (tmp_path / f"audit.jsonl.2026010{i + 1}T000000Z").write_text(
            _audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    before = sum(len(p.read_text(encoding="utf-8").splitlines())
                 for p in tmp_path.glob("audit.jsonl*"))
    r = retention.prune_audit(log, max_age_days=90, max_bytes=10,
                              keep_rotated=2, now=NOW)
    after = sum(len(p.read_text(encoding="utf-8").splitlines())
                for p in tmp_path.glob("audit.jsonl*"))
    assert r["kept"] + r["dropped"] == before
    assert r["kept"] == after, "lo conservado debe ser lo que queda en disco"


def test_lineas_con_ts_irrecuperable_se_conservan(tmp_path):
    """S1 · req4: basura, ts null, sin ts, ts numérico e ISO no se borran."""
    log = tmp_path / "audit.jsonl"
    log.write_text("esto no es json\n"
                   + json.dumps({"ts": None, "action": "a"}) + "\n"
                   + json.dumps({"action": "b"}) + "\n"
                   + json.dumps({"ts": 12345, "action": "c"}) + "\n"
                   + _audit_line(_iso(NOW - 200 * DAY)) + "\n", encoding="utf-8")
    r = retention.prune_audit(log, max_age_days=90, now=NOW)
    txt = log.read_text(encoding="utf-8")
    assert r == {"kept": 4, "dropped": 1, "rotated": None, "files_removed": 0}
    assert all(t in txt for t in ("esto no es json", '"a"', '"b"', '"c"'))
    out = tmp_path / "outbox.jsonl"
    out.write_text(json.dumps({"ts": _iso(NOW - 200 * DAY),
                               "eventid": "iso"}) + "\n" + "basura\n",
                   encoding="utf-8")
    r2 = retention.prune_outbox(out, max_age_days=30, now=NOW)
    assert r2["kept"] == 2 and r2["dropped"] == 0


def test_cooldown_podado_vuelve_a_alarma_y_fresco_calla(tmp_path):
    """R2 · interacción: podar el cooldown libera el aviso; el fresco sigue callando."""
    from l2agent import notify
    out = tmp_path / "outbox.jsonl"
    out.write_text("", encoding="utf-8")
    (tmp_path / "outbox.jsonl.cooldown.json").write_text(
        json.dumps({"viejo": NOW - 200 * DAY, "reciente": NOW - 0.5 * DAY}),
        encoding="utf-8")
    r = retention.prune_outbox(out, max_age_days=30, now=NOW)
    assert r["cooldown_dropped"] == 1
    dec = notify.decide(
        {"new": [{"eventid": "viejo", "host": "h", "severity": "High"},
                 {"eventid": "reciente", "host": "h", "severity": "High"}]},
        outbox_path=out, now=NOW)
    assert [a["eventid"] for a in dec["alarms"]] == ["viejo"]
    assert [p["kind"] for p in dec["digest"]] == ["cooldown"]


def test_archivos_ausentes_y_no_op_no_escriben_nada(tmp_path):
    """S4a/S4b · invariantes: sin archivos nada se crea; sin expirados nada cambia."""
    import hashlib
    rc = retention.main(["--audit", str(tmp_path / "no.jsonl"),
                         "--outbox", str(tmp_path / "no-out.jsonl"),
                         "--db", str(tmp_path / "no.db"), "--now", str(NOW)])
    assert rc == 0 and list(tmp_path.iterdir()) == []
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    h = hashlib.sha256(log.read_bytes()).hexdigest()
    r2 = retention.prune_audit(log, max_age_days=90, now=NOW)
    assert r2["dropped"] == 0
    assert hashlib.sha256(log.read_bytes()).hexdigest() == h


def test_main_rechaza_valores_negativos(tmp_path, capsys):
    """Advisory S7: --days negativo no puede barrer la historia completa."""
    import pytest
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        retention.main(["--audit", str(log), "--days", "-1",
                        "--now", str(NOW)])
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
