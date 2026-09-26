"""Router tests: cliente fake, sin red."""

from agent.router import L2_FALLBACK, classify_l1, route, route_l0


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


def test_l2_stub():
    level, text = route("correlaciona la causa raiz con runbooks", FakeClient())
    assert level == "L2"
    assert text.startswith(L2_FALLBACK)
    assert "mcp/curated-tools.json" in text
