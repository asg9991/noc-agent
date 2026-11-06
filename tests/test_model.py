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


def _transport_nativo(respuesta, visto):
    def handler(request):
        body = json.loads(request.content.decode())
        visto.append(body)
        return httpx.Response(200, json=respuesta)

    return httpx.MockTransport(handler)


def test_gpt_oss_manda_tools_nativas_y_qwen_no():
    visto_oss, visto_qwen = [], []
    resp_oss = {"choices": [{"message": {"content": "nada"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    resp_qwen = {"choices": [{"message": {"content":
        '{"thought": "t", "action": null, "answer": "nada"}'}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    m_oss = ChatModel(base_url="http://x/v1", model="openai/gpt-oss-120b",
                      transport=_transport_nativo(resp_oss, visto_oss))
    m_qwen = ChatModel(base_url="http://x/v1", model="qwen/qwen3-32b",
                       transport=_transport_nativo(resp_qwen, visto_qwen))
    m_oss.decide("hola", [])
    m_qwen.decide("hola", [])
    tools = visto_oss[0].get("tools") or []
    assert visto_oss[0].get("tool_choice") == "auto"
    assert {t["function"]["name"] for t in tools} >= {"problem_active_get"}
    assert "tools" not in visto_qwen[0]  # qwen sigue texto, sin cambios
    assert visto_oss[0]["max_tokens"] == 2048  # razonar consume cupo
    assert visto_qwen[0]["max_tokens"] == 512


def test_tool_calls_nativa_se_traduce_a_paso():
    visto = []
    resp = {"choices": [{"message": {
        "content": None,
        "tool_calls": [{"id": "1", "type": "function",
                        "function": {"name": "problem_active_get",
                                     "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    model = ChatModel(base_url="http://x/v1", model="openai/gpt-oss-120b",
                      transport=_transport_nativo(resp, visto))
    step = model.decide("¿hay alertas?", [])
    assert step["action"] == {"tool": "problem_active_get", "args": {}}
    assert step["answer"] is None
    assert model.usage_total == {"prompt_tokens": 100, "completion_tokens": 50}


def test_respuesta_texto_nativa_es_answer_directa():
    visto = []
    resp = {"choices": [{"message": {"content": "Hay 2 problemas."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    model = ChatModel(base_url="http://x/v1", model="openai/gpt-oss-120b",
                      transport=_transport_nativo(resp, visto))
    step = model.decide("¿hay alertas?", [])
    assert step == {"thought": "Hay 2 problemas.", "action": None,
                    "answer": "Hay 2 problemas."}


def test_override_explicito_apaga_tools_nativas():
    visto = []
    resp = {"choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    model = ChatModel(base_url="http://x/v1", model="openai/gpt-oss-120b",
                      native_tools=False,
                      transport=_transport_nativo(resp, visto))
    with pytest.raises(ValueError):  # texto plano no-JSON en modo texto
        model.decide("hola", [])
    assert "tools" not in visto[0]


# --- P2: reintento ante 429 con retry-after (el free tier throttlea, no falla)


def _ok_body():
    return {"choices": [{"message": {"content":
            '{"thought": "t", "action": null, "answer": "ok"}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def test_429_con_retry_after_reintenta_y_resuelve():
    posts, waits = [], []

    def handler(request):
        posts.append(request)
        if len(posts) == 1:
            return httpx.Response(429, headers={"retry-after": "1"},
                                  json={"error": "rate limit"})
        return httpx.Response(200, json=_ok_body())

    model = ChatModel(base_url="http://x/v1", model="lab-model",
                      transport=httpx.MockTransport(handler),
                      sleep=waits.append)
    step = model.decide("¿hay alertas?", [])
    assert step["answer"] == "ok"
    assert len(posts) == 2
    assert waits == [1.0]  # esperó lo que dice el header


def test_429_sin_header_usa_backoff_creciente():
    posts, waits = [], []

    def handler(request):
        posts.append(request)
        if len(posts) <= 2:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(200, json=_ok_body())

    model = ChatModel(base_url="http://x/v1", model="lab-model",
                      transport=httpx.MockTransport(handler),
                      sleep=waits.append)
    step = model.decide("¿hay alertas?", [])
    assert step["answer"] == "ok"
    assert len(posts) == 3
    assert waits == [2.0, 4.0]  # backoff creciente sin header


def test_429_agota_reintentos_y_revienta():
    posts, waits = [], []

    def handler(request):
        posts.append(request)
        return httpx.Response(429, headers={"retry-after": "1"},
                              json={"error": "rate limit"})

    model = ChatModel(base_url="http://x/v1", model="lab-model",
                      transport=httpx.MockTransport(handler),
                      sleep=waits.append)
    with pytest.raises(httpx.HTTPStatusError):
        model.decide("¿hay alertas?", [])
    assert len(posts) == 3  # intento + 2 reintentos, y corta
    assert waits == [1.0, 1.0]


def test_errores_no_429_no_se_reintentan():
    posts, waits = [], []

    def handler(request):
        posts.append(request)
        return httpx.Response(500, json={"error": "boom"})

    model = ChatModel(base_url="http://x/v1", model="lab-model",
                      transport=httpx.MockTransport(handler),
                      sleep=waits.append)
    with pytest.raises(httpx.HTTPStatusError):
        model.decide("¿hay alertas?", [])
    assert len(posts) == 1  # comportamiento previo: corta a la primera
    assert waits == []
