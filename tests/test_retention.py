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

import pytest

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

    left = [x for x in log.read_text(encoding="utf-8").splitlines()
            if '"retention_prune"' not in x]  # el registro de la poda no
    assert len(left) == 2                   # cuenta como línea conservada
    assert r == {"kept": 2, "dropped": 1, "rotated": None, "files_removed": 0,
                 "skipped_symlinks": []}


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


def test_nombre_con_salto_de_linea_final_no_es_tratado_como_rotado(tmp_path):
    # Un \n final jamás lo emite la rotación; si el ancla acepta un nombre
    # así, la poda lo contaría como rotado y podría borrarlo.
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    impostor = tmp_path / "audit.jsonl.20260101T000000Z\n"
    impostor.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")

    r = retention.prune_audit(log, max_age_days=90, now=NOW, keep_rotated=999)

    assert retention._rotated_re(log.name).match(impostor.name) is None
    assert impostor.exists()
    assert r["files_removed"] == 0


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

    assert r == {"kept": 1, "dropped": 1, "cooldown_dropped": 1,
                 "skipped_symlinks": []}
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
    assert r == {"sweeps_dropped": 0, "observations_dropped": 1,
                 "skipped_symlinks": []}


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

    assert r == {"sweeps_dropped": 1, "observations_dropped": 0,
                 "skipped_symlinks": []}


def test_archivos_ausentes_no_fallan(tmp_path):
    assert retention.prune_audit(tmp_path / "no.jsonl", now=NOW)["kept"] == 0
    assert retention.prune_outbox(tmp_path / "no.jsonl", now=NOW)["kept"] == 0
    assert retention.prune_db(tmp_path / "no.db", now=NOW) == {
        "sweeps_dropped": 0, "observations_dropped": 0, "skipped_symlinks": []}


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
    assert len([x for x in log.read_text(encoding="utf-8").splitlines()
                if '"retention_prune"' not in x]) == 1


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
    assert r == {"sweeps_dropped": 0, "observations_dropped": 1,
                 "skipped_symlinks": []}
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
    rotados = [p for p in tmp_path.glob("custom.jsonl.*")
               if p.suffix != ".lock"]
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
    assert r == {"kept": 4, "dropped": 1, "rotated": None, "files_removed": 0,
                 "skipped_symlinks": []}
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
    assert len([x for x in log.read_text(encoding="utf-8").splitlines()
                if '"retention_prune"' not in x]) == 1


# --- Symlinks jamás se siguen (hallazgo C1) ---


def test_symlink_rotado_no_se_sigue_y_se_reporta(tmp_path):
    """C1 · un rotado symlink no se lee, no se reescribe y no se borra.

    Su objetivo vive fuera del alcance gestionado: debe quedar intacto y el
    symlink debe reportarse en skipped_symlinks en lugar de seguirse.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.jsonl"
    victim.write_text(_audit_line(_iso(NOW - 200 * DAY)) + "\n",
                      encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    link = tmp_path / "audit.jsonl.20260101T000000Z"
    link.symlink_to(victim)
    victim_bytes = victim.read_bytes()
    gestionados = [p for p in tmp_path.glob("audit.jsonl*")
                   if not p.is_symlink()]
    antes = sum(len(p.read_text(encoding="utf-8").splitlines())
                for p in gestionados)

    r = retention.prune_audit(log, max_age_days=90, now=NOW, keep_rotated=999)

    assert victim.read_bytes() == victim_bytes, \
        "el objetivo externo debe quedar intacto"
    assert link.is_symlink(), \
        "el symlink se reporta, no se sigue ni se borra"
    assert r["skipped_symlinks"] == [link.name]
    assert r["files_removed"] == 0
    despues = sum(len(p.read_text(encoding="utf-8").splitlines())
                  for p in gestionados)
    assert r["kept"] + r["dropped"] == antes
    assert r["kept"] == despues, \
        "lo conservado reconcilia sólo sobre archivos gestionados"


def test_symlink_del_log_vivo_no_se_sigue(tmp_path):
    """C1 · audit.jsonl symlink no se poda ni se rota a través del objetivo."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.jsonl"
    victim.write_text(_audit_line(_iso(NOW - 200 * DAY)) + "\n",
                      encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    log.symlink_to(victim)
    victim_bytes = victim.read_bytes()

    r = retention.prune_audit(log, max_age_days=90, max_bytes=10, now=NOW)

    assert victim.read_bytes() == victim_bytes
    assert log.is_symlink(), "ni podado, ni rotado, ni borrado"
    assert r == {"kept": 0, "dropped": 0, "rotated": None,
                 "files_removed": 0, "skipped_symlinks": [log.name]}


def test_symlink_outbox_y_cooldown_no_se_siguen(tmp_path):
    """C1 · outbox.jsonl y su .cooldown.json symlink no se reescriben."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "outbox.jsonl"
    victim.write_text(json.dumps({"ts": NOW - 200 * DAY, "kind": "alarma",
                                  "eventid": "viejo"}) + "\n",
                      encoding="utf-8")
    cvictim = outside / "cooldown.json"
    cvictim.write_text(json.dumps({"viejo": NOW - 200 * DAY}),
                       encoding="utf-8")
    out = tmp_path / "outbox.jsonl"
    out.symlink_to(victim)
    clink = tmp_path / "outbox.jsonl.cooldown.json"
    clink.symlink_to(cvictim)
    victim_bytes, cvictim_bytes = victim.read_bytes(), cvictim.read_bytes()

    r = retention.prune_outbox(out, max_age_days=30, now=NOW)

    assert victim.read_bytes() == victim_bytes
    assert cvictim.read_bytes() == cvictim_bytes
    assert out.is_symlink() and clink.is_symlink()
    assert r == {"kept": 0, "dropped": 0, "cooldown_dropped": 0,
                 "skipped_symlinks": ["outbox.jsonl",
                                      "outbox.jsonl.cooldown.json"]}


def test_symlink_en_tope_no_se_borra_ni_ocupa_slot(tmp_path):
    """C1 · el tope --keep gestiona sólo archivos reales; el symlink sobrevive."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.jsonl"
    victim.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    for i in (2, 3):
        (tmp_path / f"audit.jsonl.2026010{i}T000000Z").write_text(
            _audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    link = tmp_path / "audit.jsonl.20260101T000000Z"
    link.symlink_to(victim)
    victim_bytes = victim.read_bytes()
    gestionados = [p for p in tmp_path.glob("audit.jsonl*")
                   if not p.is_symlink()]
    antes = sum(len(p.read_text(encoding="utf-8").splitlines())
                for p in gestionados)

    r = retention.prune_audit(log, max_age_days=90, keep_rotated=1, now=NOW)

    assert victim.read_bytes() == victim_bytes
    assert link.is_symlink()
    assert r["skipped_symlinks"] == [link.name]
    assert r["files_removed"] == 1  # sólo el real más viejo, jamás el symlink
    assert sorted(p.name for p in tmp_path.glob("audit.jsonl.2*")
                  if not p.is_symlink()) == ["audit.jsonl.20260103T000000Z"]
    despues = sum(len([x for x in p.read_text(encoding="utf-8").splitlines()
                       if '"retention_prune"' not in x])
                  for p in tmp_path.glob("audit.jsonl*")
                  if not p.is_symlink() and p.suffix != ".lock")
    assert r["kept"] + r["dropped"] == antes
    assert r["kept"] == despues


def test_symlink_vacio_no_se_elimina_en_limpieza(tmp_path):
    """C1 · la limpieza de rotados vacíos no borra ni sigue un symlink."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.jsonl"
    victim.write_text("", encoding="utf-8")
    log = tmp_path / "audit.jsonl"
    log.write_text(_audit_line(_iso(NOW)) + "\n", encoding="utf-8")
    link = tmp_path / "audit.jsonl.20260101T000000Z"
    link.symlink_to(victim)

    r = retention.prune_audit(log, max_age_days=90, now=NOW, keep_rotated=999)

    assert link.is_symlink(), \
        "el symlink vacío no se borra: se reporta, no se sigue"
    assert victim.exists()
    assert r["skipped_symlinks"] == [link.name]
    assert r["files_removed"] == 0


def test_db_symlink_no_se_abre_y_se_reporta(tmp_path):
    """C1 · watch.db symlink jamás se abre: DELETE/VACUUM irían al objetivo."""
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.db"
    conn = sqlite3.connect(real)
    conn.executescript(watch.SCHEMA)
    conn.execute("INSERT INTO sweeps (ts, active_count) VALUES (?, 1)",
                 (NOW - 400 * DAY,))
    conn.commit()
    conn.close()
    real_bytes = real.read_bytes()
    link = tmp_path / "watch.db"
    link.symlink_to(real)

    r = retention.prune_db(link, max_age_days=90, now=NOW)

    assert real.read_bytes() == real_bytes, \
        "la base externa debe quedar intacta"
    assert link.is_symlink()
    assert r == {"sweeps_dropped": 0, "observations_dropped": 0,
                 "skipped_symlinks": [link.name]}


# --- Judgment Day round 1: C2/C3/C4/C6 (RED primero) ---


def test_c2_lock_serializa_append_durante_poda(tmp_path):
    """C2: un writer cooperativo BLOQUEA mientras la poda retiene el lock;
    la línea no se pierde jamás."""
    import threading
    import time as _time
    from l2agent.audit import file_lock, log_decision
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    started = threading.Event()
    done = threading.Event()

    def writer():
        started.set()
        log_decision(log, actor="b", action="y", channel="lab", result="ok")
        done.set()

    with file_lock(log):
        t = threading.Thread(target=writer)
        t.start()
        started.wait(1)
        _time.sleep(0.3)
        assert not done.is_set(), "el writer entró durante el lock (race viva)"
    t.join(2)
    assert done.is_set()
    text = log.read_text(encoding="utf-8")
    assert '"y"' in text  # la línea del writer sobrevive


def test_c2_falla_a_media_escritura_no_trunca_el_archivo(tmp_path,
                                                         monkeypatch):
    """C2/S1: si el write falla a mitad, el archivo original queda intacto."""
    from l2agent.audit import log_decision
    import l2agent.retention as ret
    log = tmp_path / "audit.jsonl"
    for i in range(3):
        log_decision(log, actor="a", action=f"x{i}", channel="lab",
                     result="ok")
    before = log.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise OSError("ENOSPC simulado")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        ret.prune_audit(log, max_age_days=1, now=_future_days(10))
    assert log.read_text(encoding="utf-8") == before  # intacto


def test_c3_poda_no_rompe_la_cadena_p25(tmp_path):
    """C3: tras podar un log encadenado, --verify sigue en verde y la
    retención deja constancia de su corrida."""
    from l2agent.audit import log_decision as ld, verify_audit
    log = tmp_path / "audit.jsonl"
    for i in range(4):
        ld(log, actor="a", action=f"x{i}", channel="lab", result="ok")
    report = retention.prune_audit(log, max_age_days=2, now=_future_days(4))
    assert report["dropped"] >= 1
    v = verify_audit(log)
    assert v["ok"] is True, f"cadena rota tras poda: {v}"
    assert v["unsealed"] == 0
    records = [json.loads(x) for x in
               log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(r.get("action") == "retention_prune" for r in records), \
        "la retención debe dejar constancia en el audit"


def test_c4_cap_conserva_los_mas_nuevos_en_colisiones(tmp_path):
    """C4: con colisiones -N del mismo stamp, el cap conserva los más
    nuevos (orden numérico, no lexicográfico)."""
    log = tmp_path / "audit.jsonl"
    log.write_text('{"ts":"2099-01-01T00:00:00+00:00","a":1}\n',
                   encoding="utf-8")
    stamp = "20260101T000000Z"
    names = [f"audit.jsonl.{stamp}"] + \
            [f"audit.jsonl.{stamp}-{n}" for n in range(1, 12)]
    for name in names:
        (tmp_path / name).write_text(
            '{"ts":"2099-01-01T00:00:00+00:00","a":1}\n', encoding="utf-8")
    report = retention.prune_audit(log, keep_rotated=5)
    alive = {f.name for f in tmp_path.iterdir()
             if f.name.startswith("audit.jsonl.")}
    newest = {f"audit.jsonl.{stamp}-{n}" for n in range(7, 12)}
    assert newest <= alive, f"sobrevivieron {sorted(alive)}"
    assert report["files_removed"] == 7


def test_c6_keep_cero_es_invalido(tmp_path):
    """C6: --keep 0 destruiría todo lo no expirado; se rechaza."""
    from l2agent.audit import log_decision
    from l2agent.retention import main as ret_main
    log = tmp_path / "audit.jsonl"
    log_decision(log, actor="a", action="x", channel="lab", result="ok")
    with pytest.raises(ValueError):
        retention.prune_audit(log, keep_rotated=0)
    with pytest.raises(SystemExit):  # parser.error del CLI
        ret_main([str(log), "--keep", "0"])


def _future_days(d: float) -> float:
    import time as _t
    return _t.time() + d * 86400.0
