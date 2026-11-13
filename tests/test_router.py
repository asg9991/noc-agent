"""Router tests: cliente fake, sin red."""

from agent.router import L2_NO_MODEL, classify_l1, handle_l2, route, route_l0


class FakeClient:
    def get_version(self):
        return "7.4.13"

    def get_problems(self, limit=20):
        return [
            {
                "eventid": "123",
                "name": "CPU alta en lab-host",
                "severity": "4",
                "clock": "1700000000",
                "objectid": "1",
            }
        ][:limit]

    def get_hosts(self, limit=20):
        return [{"hostid": "1", "host": "lab-host", "name": "lab-host", "status": "0"}]


def test_l0_exact_estado(tmp_path):
    level, text = route("estado", FakeClient(),
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L0"
    assert "7.4.13" in text


def test_l0_exact_ack(tmp_path):
    level, text = route("ack", FakeClient(),
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L0"
    assert "CPU alta" in text


def test_l1_keyword_routes_to_l0_handler(tmp_path):
    assert route_l0("hay alertas nuevas?") is None  # no es comando exacto
    assert classify_l1("hay alertas nuevas?") is not None
    level, text = route("hay alertas nuevas?", FakeClient(),
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L1"
    assert "CPU alta" in text


def test_l2_sin_modelo_avisa_en_vez_de_romper(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    level, text = route("correlaciona la causa raiz con runbooks", FakeClient(),
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L2"
    assert text == L2_NO_MODEL


class FakeModel:
    def __init__(self, steps):
        self.steps = steps

    def decide(self, goal, history):
        i = min(len(history), len(self.steps) - 1)
        return self.steps[i]


class FakeMCP:
    def __init__(self, payload=None):
        self.payload = payload
        self.calls = []

    def call_tool(self, name, args=None):
        self.calls.append((name, args or {}))
        return self.payload


def test_l2_con_fakes_corre_el_loop(tmp_path):
    model = FakeModel(
        [
            {"thought": "veo problemas",
             "action": {"tool": "problem_active_get", "args": {}}},
            {"thought": "listo", "answer": "2 problemas activos."},
        ]
    )
    fake = FakeMCP(payload=[{"name": "CPU alta"}, {"name": "Disco lleno"}])
    log = tmp_path / "audit.jsonl"
    text = handle_l2("¿hay alertas?", model=model, client=fake, audit_path=log)
    assert text == "2 problemas activos."
    assert fake.calls == [("problem_active_get", {})]
    assert log.exists()


def test_l1_matchea_los_ejemplos_publicados():
    for texto in ("hay alertas?", "problemas", "versión",
                  "¿cómo está el zabbix?"):
        assert classify_l1(texto) is not None, texto


def test_l1_no_matchea_subcadenas_de_palabras():
    # 'ack' no vive dentro de 'backup'; 'estación'/'estadística' no traen
    # 'estado'. La coincidencia es por palabra completa, no por subcadena.
    assert classify_l1("se hizo el backup nocturno") is None
    assert classify_l1("¿cuándo se instaló la estación?") is None
    assert classify_l1("la estadística del mes") is None


def test_handle_l2_propaga_actor_y_canal_al_audit(tmp_path):
    """P10: la identidad real llega hasta run_loop y queda en cada registro."""
    import json
    model = FakeModel(
        [{"thought": "ok", "answer": "listo."}]
    )
    fake = FakeMCP(payload=[])
    log = tmp_path / "audit.jsonl"
    handle_l2("pregunta", model=model, client=fake, audit_path=log,
              actor="ana", channel="mail")
    lineas = [json.loads(x) for x in
              log.read_text(encoding="utf-8").splitlines()]
    assert lineas and all(l["actor"] == "ana" for l in lineas)
    assert all(l["channel"] == "mail" for l in lineas)


def test_route_lleva_actor_y_canal_al_l2(monkeypatch):
    visto = {}

    def fake_handle_l2(text, **kw):
        visto.update(kw)
        return "ok"

    monkeypatch.setattr("agent.router.handle_l2", fake_handle_l2)
    nivel, _ = route("explica la causa raiz de todo", FakeClient(),
                     actor="ana", channel="mail")
    assert nivel == "L2"
    assert visto["actor"] == "ana" and visto["channel"] == "mail"


def test_cli_estampa_actor_real_en_audit(tmp_path):
    """P10: el origen CLI ya no escribe actor fijo "l2"."""
    import json
    from l2agent.main import main as l2_cli_main
    model = FakeModel([{"thought": "ok", "answer": "listo."}])
    fake = FakeMCP(payload=[])
    log = tmp_path / "audit.jsonl"
    rc = l2_cli_main(["pregunta", "--actor", "juan", "--audit", str(log)],
                     client=fake, model=model)
    assert rc == 0
    lineas = [json.loads(x) for x in
              log.read_text(encoding="utf-8").splitlines()]
    assert lineas and all(l["actor"] == "juan" for l in lineas)


def test_cli_actor_por_env_noc_actor(tmp_path, monkeypatch):
    import json
    from l2agent.main import main as l2_cli_main
    monkeypatch.setenv("NOC_ACTOR", "guardia-noche")
    model = FakeModel([{"thought": "ok", "answer": "listo."}])
    fake = FakeMCP(payload=[])
    log = tmp_path / "audit.jsonl"
    l2_cli_main(["pregunta", "--audit", str(log)], client=fake, model=model)
    lineas = [json.loads(x) for x in
              log.read_text(encoding="utf-8").splitlines()]
    assert lineas and all(l["actor"] == "guardia-noche" for l in lineas)


def test_origenes_distintos_dejan_actor_distinto(tmp_path):
    """P10 (criterio de verificación): misma pregunta, dos orígenes, dos actores."""
    import json
    from l2agent.main import main as l2_cli_main
    log = tmp_path / "audit.jsonl"
    model = FakeModel([{"thought": "ok", "answer": "listo."}])
    l2_cli_main(["pregunta", "--actor", "juan", "--audit", str(log)],
                client=FakeMCP(payload=[]), model=model)
    handle_l2("pregunta", model=FakeModel([{"thought": "ok", "answer": "sí."}]),
              client=FakeMCP(payload=[]), audit_path=log,
              actor="ana", channel="mail")
    actores = {json.loads(x)["actor"] for x in
               log.read_text(encoding="utf-8").splitlines()}
    assert actores == {"juan", "ana"}


def _route_records(log):
    import json
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()
            if json.loads(x).get("action") == "route"]


def test_route_deja_traza_por_nivel(tmp_path, monkeypatch):
    """P11: cada decisión de routing queda registrada con su nivel (§5)."""
    log = tmp_path / "audit.jsonl"
    route("estado", FakeClient(), actor="ana", audit_path=log)
    route("hay alertas nuevas?", FakeClient(), actor="ana", audit_path=log)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    route("explica la causa raiz de todo", FakeClient(), actor="ana",
          audit_path=log)
    regs = _route_records(log)
    assert [r["result"] for r in regs] == ["L0", "L1", "L2"]
    assert [r["detail"]["handler"] for r in regs] == [
        "handle_estado", "handle_ack", "run_loop"]
    assert all(r["actor"] == "ana" for r in regs)


def test_main_cli_registra_decision_l2(tmp_path):
    import json
    from l2agent.main import main as l2_cli_main
    model = FakeModel([{"thought": "ok", "answer": "listo."}])
    log = tmp_path / "audit.jsonl"
    l2_cli_main(["pregunta", "--actor", "juan", "--audit", str(log)],
                client=FakeMCP(payload=[]), model=model)
    regs = _route_records(log)
    assert regs and regs[0]["result"] == "L2"
    assert regs[0]["detail"]["handler"] == "run_loop"
    assert regs[0]["detail"]["text"] == "pregunta"


def test_cli_actor_default_usa_identidad_del_kernel(tmp_path, monkeypatch):
    """P11: el default NO es $USER (spoofeable) sino el dueño real del proceso."""
    import json
    import os
    import pwd
    from l2agent.main import main as l2_cli_main
    monkeypatch.delenv("NOC_ACTOR", raising=False)
    monkeypatch.setenv("USER", "intruso")
    model = FakeModel([{"thought": "ok", "answer": "listo."}])
    log = tmp_path / "audit.jsonl"
    l2_cli_main(["pregunta", "--audit", str(log)],
                client=FakeMCP(payload=[]), model=model)
    lineas = [json.loads(x) for x in
              log.read_text(encoding="utf-8").splitlines()]
    esperado = pwd.getpwuid(os.getuid()).pw_name
    assert lineas and all(l["actor"] == esperado for l in lineas)
    assert all(l["actor"] != "intruso" for l in lineas)
