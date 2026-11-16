"""Router tests: cliente fake, sin red."""

import json

import pytest

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
    level, text = route("estado", FakeClient(), actor="ana", channel="lab",
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L0"
    assert "7.4.13" in text


def test_l0_exact_ack(tmp_path):
    level, text = route("ack", FakeClient(), actor="ana", channel="lab",
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L0"
    assert "CPU alta" in text


def test_l1_keyword_routes_to_l0_handler(tmp_path):
    assert route_l0("hay alertas nuevas?") is None  # no es comando exacto
    assert classify_l1("hay alertas nuevas?") is not None
    level, text = route("hay alertas nuevas?", FakeClient(), actor="ana", channel="lab",
                        audit_path=tmp_path / "audit.jsonl")
    assert level == "L1"
    assert "CPU alta" in text


def test_l2_sin_modelo_avisa_en_vez_de_romper(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    level, text = route("correlaciona la causa raiz con runbooks", FakeClient(), actor="ana", channel="lab",
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
    text = handle_l2("¿hay alertas?", actor="ana", channel="lab", model=model, client=fake, audit_path=log)
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
    route("estado", FakeClient(), actor="ana", channel="lab", audit_path=log)
    route("hay alertas nuevas?", FakeClient(), actor="ana", channel="lab", audit_path=log)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    route("explica la causa raiz de todo", FakeClient(), actor="ana",
          channel="lab", audit_path=log)
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


# --- JD#2 info rows: identidad obligatoria, trazas, totales (B-6..B-9/A-4) ---


def test_identidad_es_obligatoria():
    """B-7: route()/handle_l2 no fabrican identidad — sin actor/channel
    explícito, error inmediato (antes: default silencioso 'l2'/'lab')."""
    from agent.router import route, handle_l2
    with pytest.raises(TypeError):
        route("estado", FakeClient())
    with pytest.raises(TypeError):
        handle_l2("hola", model=None, client=None)


def test_traza_cli_se_escribe_antes_de_fallar_por_modelo(tmp_path,
                                                         monkeypatch):
    """B-5: el intento L2 del CLI queda en el audit aunque falle la
    construcción del modelo (antes: 0 registros)."""
    from l2agent.main import main as l2main
    monkeypatch.delenv("LLM_MODEL", raising=False)
    log = tmp_path / "audit.jsonl"
    with pytest.raises(SystemExit):
        l2main(["objetivo", "--audit", str(log)])
    assert log.exists() and '"route"' in log.read_text(encoding="utf-8")


def test_min_interval_malo_da_error_amable(tmp_path, monkeypatch):
    """B-10: LLM_MIN_INTERVAL_S malformado sale con mensaje claro (exit 2),
    no con traceback crudo."""
    from l2agent.main import main as l2main
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "no-numero")
    with pytest.raises(SystemExit) as exc:
        l2main(["objetivo", "--audit", str(tmp_path / "a.jsonl")])
    assert exc.value.code == 2


def test_actor_source_queda_en_el_audit(tmp_path, monkeypatch):
    """B-6: la cadena de identidad deja el ORIGEN en el audit — lo
    auto-declarado (NOC_ACTOR) es distinguible de lo autenticado (kernel)."""
    from l2agent.main import main as l2main
    monkeypatch.setenv("NOC_ACTOR", "intruso")
    monkeypatch.delenv("LLM_MIN_INTERVAL_S", raising=False)
    log = tmp_path / "audit.jsonl"
    l2main(["hola", "--audit", str(log)], model=FakeModel([]),
           client=FakeClient())
    records = [json.loads(x) for x in
               log.read_text(encoding="utf-8").splitlines()]
    record = next(r for r in records if r["action"] == "route")
    assert record["actor"] == "intruso"
    assert record["detail"]["actor_source"] == "env"


def test_estado_reporta_muestra_cuando_trunca(tmp_path):
    """B-8: si el fetch llegó al limit, el conteo se reporta como muestra
    ('100+'), no como total exacto (antes: sub-reacción a incidentes)."""
    from agent.router import route

    class Big:
        def get_version(self):
            return "7.4"

        def get_problems(self, limit=100):
            return [{"name": "x"}] * limit

        def get_hosts(self, limit=100):
            return [{"host": "h"}] * limit

    level, text = route("estado", Big(), actor="ana", channel="lab",
                        audit_path=str(tmp_path / "a.jsonl"))
    assert level == "L0"
    assert "hosts: 100+" in text and "problemas activos: 100+" in text


def test_l1_empates_van_a_estado(tmp_path):
    """A-4: consultas ambiguas (familia ack y estado a la vez) resuelven
    por regla declarada hacia el resumen de estado, no por orden de tabla."""
    from agent.router import route
    log = str(tmp_path / "a.jsonl")
    for q in ("estado de los problemas", "problemas del estado",
              "alerta de estado"):
        level, text = route(q, FakeClient(), actor="ana", channel="lab",
                            audit_path=log)
        assert level == "L1"
        assert "Zabbix" in text, f"{q!r} debe ir a handle_estado, fue: {text}"


def test_route_propaga_role_y_on_denied(tmp_path, monkeypatch):
    """B-9: route() expone role/on_denied y los llega a handle_l2."""
    import agent.router as r
    seen = {}
    real = r.handle_l2

    def spy(text, **kw):
        seen.update(kw)
        return "ok"

    monkeypatch.setattr(r, "handle_l2", spy)
    level, _ = route("explica la causa raiz de todo", FakeClient(),
                     actor="ana", channel="lab", role="technician",
                     on_denied=lambda *_: None,
                     audit_path=str(tmp_path / "a.jsonl"))
    assert level == "L2"
    assert seen["role"] == "technician" and seen["on_denied"] is not None


def test_min_interval_malo_igual_deja_traza(tmp_path, monkeypatch):
    """B-5+B-10: el fallo de configuración también es decisión registrada."""
    from l2agent.main import main as l2main
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "no-numero")
    log = tmp_path / "audit.jsonl"
    with pytest.raises(SystemExit) as exc:
        l2main(["objetivo", "--audit", str(log)])
    assert exc.value.code == 2
    assert '"route"' in log.read_text(encoding="utf-8")


def test_identidad_parcial_o_vacia_tambien_es_typeerror():
    """B-7: ni actor sin channel ni cadena vacía fabrican identidad."""
    from agent.router import route
    with pytest.raises(TypeError):
        route("estado", FakeClient(), actor="ana")
    with pytest.raises(TypeError):
        route("estado", FakeClient(), actor="", channel="lab")
