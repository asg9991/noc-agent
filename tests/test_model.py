"""Model tests: parsing JSON + caller OpenAI-compatible, sin red real.

El transporte se falsifica con httpx.MockTransport: verificamos qué le
pedimos al endpoint sin levantar ningún servidor.
"""

import json

import httpx
import pytest

from l2agent.model import ChatModel, parse_step


def test_parse_step_json_directo():
    step = parse_step('{"thought": "t", "action": null, "answer": "hola"}')
    assert step == {"thought": "t", "action": None, "answer": "hola"}


def test_parse_step_tolera_fences_de_markdown():
    step = parse_step(
        '```json\n{"thought": "t", '
        '"action": {"tool": "host_get", "args": {}}}```'
    )
    assert step["action"] == {"tool": "host_get", "args": {}}


def test_parse_step_sin_json_levanta():
    with pytest.raises(ValueError):
        parse_step("voy a consultar los problemas ahora mismo")


def _transport(payload, visto):
    def handler(request):
        assert "chat/completions" in str(request.url)
        body = json.loads(request.content.decode())
        assert body["model"] == "lab-model"
        assert body["temperature"] == 0  # decisión, no creatividad
        assert body["max_tokens"] == 512  # decisiones cortas: freno de costo
        visto.append(body)
        mens = [m for m in body["messages"] if m["role"] == "system"][0]
        assert "problem_active_get" in mens["content"]  # el modelo ve el menú
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": payload}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    return httpx.MockTransport(handler)


def test_chat_model_devuelve_paso_parseado():
    visto = []
    transport = _transport('{"thought": "t", "action": null, "answer": "ok"}', visto)
    model = ChatModel(base_url="http://x/v1", model="lab-model", transport=transport)
    step = model.decide("¿hay alertas?", [])
    assert step["answer"] == "ok"
    assert len(visto) == 1


def test_chat_model_manda_la_historia_al_endpoint():
    visto = []
    transport = _transport('{"thought": "t2", "action": null, "answer": "listo"}', visto)
    model = ChatModel(base_url="http://x/v1", model="lab-model", transport=transport)
    history = [
        {"thought": "consulto", "action": {"tool": "problem_active_get", "args": {}},
         "observation": "2 problemas"},
    ]
    model.decide("¿hay alertas?", history)
    user = [m for m in visto[0]["messages"] if m["role"] == "user"][0]
    assert "2 problemas" in user["content"]  # la observación viaja al modelo


def test_chat_model_acumula_usage_por_corrida():
    visto = []
    transport = _transport('{"thought": "t", "action": null, "answer": "ok"}', visto)
    model = ChatModel(base_url="http://x/v1", model="lab-model", transport=transport)
    model.decide("hola", [])
    model.decide("hola", [])
    assert model.usage_total == {"prompt_tokens": 200, "completion_tokens": 100}
