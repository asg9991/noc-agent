"""Watch tests: barridos deterministas con memoria. Cero tokens, cero red real.

El FakeMCP finge al hub: cada barrido devuelve una lista de problemas
(dicts con eventid/host/severidad). El tmp_path aísla la DB por test.
"""

from l2agent import watch


class FakeMCP:
    def __init__(self, payload):
        self.payload = payload

    def call_tool(self, name, args=None):
        assert name == "problem_active_get"
        return self.payload


def prob(eid, host="h1", sev="High"):
    return {"eventid": eid, "host": host, "severity": sev}


def test_primer_barrido_todo_nuevo(tmp_path):
    db = tmp_path / "watch.db"
    r = watch.sweep(FakeMCP([prob("e1"), prob("e2")]), db)
    assert [p["eventid"] for p in r["new"]] == ["e1", "e2"]
    assert r["recurrent"] == [] and r["recovered"] == []
    assert r["heartbeat_ts"] > 0


def test_segundo_barrido_igual_es_recurrente_sin_alarma(tmp_path):
    db = tmp_path / "watch.db"
    watch.sweep(FakeMCP([prob("e1")]), db)
    r = watch.sweep(FakeMCP([prob("e1")]), db)
    assert r["new"] == []
    assert [p["eventid"] for p in r["recurrent"]] == ["e1"]


def test_ausencia_simple_no_es_recuperado_histéresis(tmp_path):
    db = tmp_path / "watch.db"
    watch.sweep(FakeMCP([prob("e1")]), db)
    r = watch.sweep(FakeMCP([]), db)  # falta 1 vez: puede ser flapping
    assert r["recovered"] == []
    assert r["new"] == []


def test_doble_ausencia_es_recuperado_y_no_repite(tmp_path):
    db = tmp_path / "watch.db"
    watch.sweep(FakeMCP([prob("e1")]), db)
    watch.sweep(FakeMCP([]), db)
    r = watch.sweep(FakeMCP([]), db)  # falta 2da vez: se normalizó
    assert [p["eventid"] for p in r["recovered"]] == ["e1"]
    r2 = watch.sweep(FakeMCP([]), db)  # 3ra vez: silencio, ya avisado
    assert r2["recovered"] == []


def test_reaparecido_tras_recuperado_es_nuevo(tmp_path):
    db = tmp_path / "watch.db"
    watch.sweep(FakeMCP([prob("e1")]), db)
    watch.sweep(FakeMCP([]), db)
    watch.sweep(FakeMCP([]), db)
    r = watch.sweep(FakeMCP([prob("e1")]), db)
    assert [p["eventid"] for p in r["new"]] == ["e1"]


def test_heartbeat_dice_si_el_vigilante_sigue_vivo(tmp_path):
    db = tmp_path / "watch.db"
    assert watch.is_alive(db, max_age_s=3600) is False  # nunca barrió
    watch.sweep(FakeMCP([]), db)
    assert watch.is_alive(db, max_age_s=3600) is True
    assert watch.is_alive(db, max_age_s=0) is False  # umbral vencido
