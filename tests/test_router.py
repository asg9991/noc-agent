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


def test_l0_exact_estado():
    level, text = route("estado", FakeClient())
    assert level == "L0"
    assert "7.4.13" in text


def test_l0_exact_ack():
    level, text = route("ack", FakeClient())
    assert level == "L0"
    assert "CPU alta" in text


def test_l1_keyword_routes_to_l0_handler():
    assert route_l0("hay alertas nuevas?") is None  # no es comando exacto
    assert classify_l1("hay alertas nuevas?") is not None
    level, text = route("hay alertas nuevas?", FakeClient())
    assert level == "L1"
    assert "CPU alta" in text


def test_l2_sin_modelo_avisa_en_vez_de_romper(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    level, text = route("correlaciona la causa raiz con runbooks", FakeClient())
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
