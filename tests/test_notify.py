"""Notify tests: qué merece interrumpir a un humano y qué no.

Tres compuertas en orden: taxonomía (solo NUEVO alarma, RECUPERADO va a
digest), severidad (umbral configurable, default High) y cooldown (el mismo
eventid no re-alarma dentro de la ventana aunque re-nazca).
"""

from l2agent import notify


def alarm(eid, sev="High", host="h1"):
    return {"eventid": eid, "host": host, "severity": sev}


def test_nuevo_high_alarma_y_va_a_outbox(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    r = notify.decide({"new": [alarm("e1")], "recurrent": [], "recovered": []},
                      outbox_path=outbox)
    assert len(r["alarms"]) == 1
    assert r["alarms"][0]["eventid"] == "e1"
    assert "e1" in outbox.read_text(encoding="utf-8")
    assert r["digest"] == []


def test_recurrente_nunca_alarma(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    r = notify.decide({"new": [], "recurrent": [alarm("e1")],
                       "recovered": []}, outbox_path=outbox)
    assert r["alarms"] == [] and r["digest"] == []
    assert not outbox.exists()  # silencio total: ni archivo


def test_average_no_alarma_va_a_digest(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    r = notify.decide({"new": [alarm("e2", sev="Average")], "recurrent": [],
                       "recovered": [alarm("e9", sev="High")]},
                      outbox_path=outbox)
    assert r["alarms"] == []  # nada interrumpe
    kinds = sorted(d["kind"] for d in r["digest"])
    assert kinds == ["bajo-umbral", "recuperado"]


def test_cooldown_suprime_realarma_del_mismo_evento(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    sweep = {"new": [alarm("e1")], "recurrent": [], "recovered": []}
    r1 = notify.decide(sweep, outbox_path=outbox, now=1000.0)
    assert len(r1["alarms"]) == 1
    r2 = notify.decide(sweep, outbox_path=outbox, now=1000.0 + 3600)
    assert r2["alarms"] == []  # mismo evento dentro de 24h: mudo
    assert any(d["kind"] == "cooldown" for d in r2["digest"])
    r3 = notify.decide(sweep, outbox_path=outbox,
                       now=1000.0 + 25 * 3600)
    assert len(r3["alarms"]) == 1  # ventana vencida: re-alarma


def test_severidad_desconocida_no_alarma(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    r = notify.decide({"new": [alarm("eX", sev="???")], "recurrent": [],
                       "recovered": []}, outbox_path=outbox)
    assert r["alarms"] == []
    assert r["digest"][0]["kind"] == "severidad-desconocida"


def test_umbral_configurable_deja_pasar_average(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    r = notify.decide({"new": [alarm("e2", sev="Average")], "recurrent": [],
                       "recovered": []}, outbox_path=outbox,
                      min_severity="Average")
    assert len(r["alarms"]) == 1


def test_digest_bajo_umbral_es_neutro_en_severidad(tmp_path):
    outbox = tmp_path / "outbox.jsonl"
    r = notify.decide({"new": [alarm("e1", sev="Warning"),
                               alarm("e2", sev="Info")],
                       "recurrent": [], "recovered": []},
                      outbox_path=outbox)
    assert r["alarms"] == []
    assert [d["kind"] for d in r["digest"]] == ["bajo-umbral", "bajo-umbral"]
