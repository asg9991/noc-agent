"""Loop tests: workflow con modelo fake y cliente fake. Cero tokens, cero red."""

import json

from l2agent.loop import MAX_ITERS, run_loop


class FakeModel:
    """Modelo de juguete: devuelve pasos guionados según la historia."""

    def __init__(self, steps):
        self.steps = steps

    def decide(self, goal, history):
        i = min(len(history), len(self.steps) - 1)
        return self.steps[i]


class FakeMCP:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def call_tool(self, name, args=None):
        self.calls.append((name, args or {}))
        if self.error is not None:
            raise self.error
        return self.payload


def test_camino_feliz_pregunta_accion_respuesta(tmp_path):
    log = tmp_path / "audit.jsonl"
    model = FakeModel(
        [
            {"thought": "Hay que ver problemas activos",
             "action": {"tool": "problem_active_get", "args": {}}},
            {"thought": "Ya tengo datos", "answer": "Hay 2 problemas activos."},
        ]
    )
    fake = FakeMCP(payload=[{"name": "CPU alta"}, {"name": "Disco lleno"}])
    out = run_loop("¿hay alertas?", model=model, client=fake, audit_path=log)
    assert out == "Hay 2 problemas activos."
    assert fake.calls == [("problem_active_get", {})]
    assert log.exists()  # la corrida dejó traza


def test_tool_denegada_no_llega_al_cliente(tmp_path):
    log = tmp_path / "audit.jsonl"
    model = FakeModel(
        [
            {"thought": "Voy a crear un host",
             "action": {"tool": "host_create", "args": {"host": "x"}}},
            {"thought": "No puedo", "answer": "Crear hosts no está permitido."},
        ]
    )
    fake = FakeMCP(payload="nunca debería verse")
    out = run_loop("creá un host", model=model, client=fake, audit_path=log)
    assert out == "Crear hosts no está permitido."
    assert fake.calls == []  # frenado antes de la frontera
    assert "denegado" in log.read_text(encoding="utf-8")


def test_error_de_transporte_llega_como_texto_al_modelo(tmp_path):
    log = tmp_path / "audit.jsonl"
    visto = {}

    class Espia(FakeModel):
        def decide(self, goal, history):
            if history:
                visto["obs"] = history[-1]["observation"]
                return {"thought": "falló", "answer": "El hub no responde."}
            return self.steps[0]

    model = Espia([{"thought": "consulto",
                    "action": {"tool": "problem_active_get", "args": {}}}])
    fake = FakeMCP(error=RuntimeError("hub caído"))
    out = run_loop("¿hay alertas?", model=model, client=fake, audit_path=log)
    assert out == "El hub no responde."
    assert visto["obs"].startswith("error:")


def test_tope_de_iteraciones_corta(tmp_path):
    log = tmp_path / "audit.jsonl"

    class Variado(FakeModel):
        def decide(self, goal, history):
            # Acciones distintas cada vuelta: no hay repetición, solo tope.
            return {"thought": "sigo",
                    "action": {"tool": "history_get",
                               "args": {"itemid": str(len(history))}}}

    model = Variado([])
    fake = FakeMCP(payload=[1, 2, 3])
    out = run_loop("dame historia", model=model, client=fake,
                   audit_path=log, max_iters=3)
    assert "tope de 3 iteraciones" in out
    assert len(fake.calls) == 3


def test_accion_repetida_corta_antes_del_tope(tmp_path):
    log = tmp_path / "audit.jsonl"
    model = FakeModel(
        [{"thought": "otra vez", "action": {"tool": "history_get", "args": {}}}]
    )
    fake = FakeMCP(payload=[1])
    out = run_loop("dame historia", model=model, client=fake,
                   audit_path=log, max_iters=MAX_ITERS)
    assert "repiti" in out  # repitió la misma acción: posible loop
    assert len(fake.calls) == 1  # cortó en la 2da, no consumió las 5


def test_modelo_sin_decision_corta(tmp_path):
    log = tmp_path / "audit.jsonl"
    model = FakeModel([{"thought": "no sé"}])
    out = run_loop("hola", model=model, client=FakeMCP(), audit_path=log)
    assert "sin decisión" in out


def test_loop_inicializa_sesion_si_el_cliente_sabe(tmp_path):
    log = tmp_path / "audit.jsonl"

    class ConSesion(FakeMCP):
        def __init__(self):
            super().__init__(payload=[])
            self.inits = 0

        def initialize(self):
            self.inits += 1
            return "sesion-lab"

    model = FakeModel([{"thought": "listo", "answer": "nada activo."}])
    fake = ConSesion()
    out = run_loop("¿hay alertas?", model=model, client=fake, audit_path=log)
    assert out == "nada activo."
    assert fake.inits == 1  # handshake una sola vez, antes del loop


def test_respuesta_final_registra_usage_del_modelo(tmp_path):
    log = tmp_path / "audit.jsonl"

    class ConUsage(FakeModel):
        usage_total = {"prompt_tokens": 10, "completion_tokens": 5}

    model = ConUsage([{"thought": "listo", "answer": "ok"}])
    run_loop("hola", model=model, client=FakeMCP(), audit_path=log)
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    final = [r for r in records if r["action"] == "respuesta_final"][0]
    assert final["detail"]["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}
