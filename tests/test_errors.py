"""Clasificación de errores L2: credencial vencida vs transitorio + alarma.

La clasificación es pura (texto/tipo de excepción): cero red, cero tokens.
"""

import json

from l2agent import errors
from l2agent.loop import run_loop


class FakeModel:
    def __init__(self, steps):
        self.steps = steps

    def decide(self, goal, history):
        i = min(len(history), len(self.steps) - 1)
        return self.steps[i]


class FakeMCP:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def call_tool(self, name, args=None):
        if self.error is not None:
            raise self.error
        return self.payload


def test_auth_por_not_authorized():
    assert errors.classify(RuntimeError("Not authorized")) == "auth"


def test_auth_por_401_y_token_invalido():
    assert errors.classify(RuntimeError("401 Unauthorized")) == "auth"
    assert errors.classify(RuntimeError("invalid token")) == "auth"


def test_transitorio_por_timeout_conexion_y_429():
    assert errors.classify(TimeoutError("request timed out")) == "transient"
    assert errors.classify(ConnectionError("hub caído: connection refused")) == "transient"
    assert errors.classify(RuntimeError("429 Too Many Requests")) == "transient"


def test_generico_sigue_unknown():
    # "hub caído" sin más datos no se puede clasificar: no se inventa.
    assert errors.classify(RuntimeError("hub caído")) == "unknown"


def test_loop_marca_error_auth_en_audit_y_observacion(tmp_path):
    log = tmp_path / "audit.jsonl"
    model = FakeModel(
        [
            {"thought": "consulto",
             "action": {"tool": "problem_active_get", "args": {}}},
            {"thought": "sin credencial", "answer": "Sin acceso al hub."},
        ]
    )
    fake = FakeMCP(error=RuntimeError("Not authorized"))
    out = run_loop("¿hay alertas?", model=model, client=fake, audit_path=log)
    assert out == "Sin acceso al hub."
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    tool_rec = [r for r in records if r["action"] == "problem_active_get"][0]
    assert tool_rec["result"] == "error_auth"
    assert tool_rec["detail"]["observation"].startswith("error_auth:")


def test_loop_marca_transitorio_en_audit(tmp_path):
    log = tmp_path / "audit.jsonl"
    model = FakeModel(
        [
            {"thought": "consulto",
             "action": {"tool": "problem_active_get", "args": {}}},
            {"thought": "caído", "answer": "El hub no responde."},
        ]
    )
    fake = FakeMCP(error=TimeoutError("request timed out"))
    run_loop("¿hay alertas?", model=model, client=fake, audit_path=log)
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    tool_rec = [r for r in records if r["action"] == "problem_active_get"][0]
    assert tool_rec["result"] == "error_transient"


def test_loop_error_generico_sigue_error_compatible(tmp_path):
    # Contrato viejo intacto: lo no clasificable sigue siendo "error:".
    log = tmp_path / "audit.jsonl"
    model = FakeModel(
        [
            {"thought": "consulto",
             "action": {"tool": "problem_active_get", "args": {}}},
            {"thought": "falló", "answer": "Falló."},
        ]
    )
    fake = FakeMCP(error=RuntimeError("hub caído"))
    run_loop("¿hay alertas?", model=model, client=fake, audit_path=log)
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    tool_rec = [r for r in records if r["action"] == "problem_active_get"][0]
    assert tool_rec["result"] == "error"


def test_loop_modelo_con_credencial_rota_da_alarma(tmp_path):
    log = tmp_path / "audit.jsonl"

    class ModeloRoto(FakeModel):
        def decide(self, goal, history):
            raise RuntimeError("401 Unauthorized")

    out = run_loop("hola", model=ModeloRoto([]), client=FakeMCP(),
                   audit_path=log)
    assert "alarma" in out
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert records[0]["result"] == "error_auth"
