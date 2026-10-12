"""Cerebro intercambiable del L2: habla OpenAI-compatible por httpx.

El proveedor lo elige el operador por env (Ollama local, nube, el que sea):
LLM_BASE_URL, LLM_MODEL, LLM_API_KEY opcional. Sin SDK nuevo: httpx ya es
dependencia del repo. El día que cambies de proveedor, cambiás env, no código
(doctrina: configuración, no refactor).

El modelo decide en JSON: {"thought": ..., "action": {"tool", "args"} | null,
"answer": ... | null}. temperature=0: acá se decide, no se crea.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from mcp.catalog import load_catalog

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"  # Ollama local, endpoint OpenAI-compatible

# Familias que hablan dialecto nativo de tools (canal tool_calls en vez de
# JSON-en-texto). El gateway las rechaza con 400 si no se les manda `tools`
# (visto en vivo con gpt-oss-20b: "tool choice is none, but model called
# a tool"). Opt-in por nombre; override explícito en el constructor.
NATIVE_TOOL_MODELS = ("gpt-oss",)

# Razonar consume cupo de completion: las nativas piden más techo.
NATIVE_MAX_TOKENS = 2048


def _menu(role: str) -> str:
    """El menú que ve el modelo: nombres + porqué, sin schemas (tokens)."""
    entries = load_catalog()["roles"][role]
    return "\n".join(f"- {e['name']}: {e.get('why', '')}" for e in entries)


def system_prompt(role: str) -> str:
    return (
        "Sos el motor de decisión de un agente NOC de solo lectura. "
        "Respondés SOLO con un JSON: "
        '{"thought": "...", "action": {"tool": "...", "args": {...}} o null, '
        '"answer": "..." o null}. '
        "Con acción pedís UNA tool; con respuesta cerrás. "
        "Respondé solo con datos de las observaciones; si no hay datos, decilo.\n"
        f"Tools disponibles:\n{_menu(role)}"
    )


def native_system_prompt(role: str) -> str:
    """Variante para modelos tool-nativos: las tools viajan en `tools`,
    no en texto. El JSON-en-texto acá ESTORBA (el gateway lo rechaza)."""
    return (
        "Sos el motor de decisión de un agente NOC de solo lectura. "
        "Pedís datos con las tools nativas (UNA por turno); cuando tengas "
        "lo necesario, cerrás respondiendo en texto plano y directo. "
        "Respondé solo con datos de las observaciones; si no hay datos, decilo."
    )


def native_tools_payload(role: str) -> list[dict[str, Any]]:
    """Catálogo curado en formato OpenAI function-calling.

    Sin schemas por herramienta (el catálogo no los tiene): objeto genérico.
    El gate real sigue siendo tools.run + allowlist del lado nuestro.
    """
    return [
        {"type": "function",
         "function": {"name": e["name"],
                      "description": e.get("why") or e["name"],
                      "parameters": {"type": "object", "properties": {}}}}
        for e in load_catalog()["roles"][role]
    ]


def parse_step(text: str) -> dict[str, Any]:
    """Extrae el paso JSON tolerando fences de markdown. Lo demás: ValueError."""
    t = text.strip()
    if t.startswith("```"):
        t = "\n".join(t.split("\n")[1:])
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -len("```")]
    try:
        step = json.loads(t.strip())
    except json.JSONDecodeError:
        raise ValueError(f"el modelo no devolvió JSON: {text[:200]}")
    if not isinstance(step, dict) or "action" not in step:
        raise ValueError(f"paso sin 'action': {text[:200]}")
    return step


def render_history(history: list[dict[str, Any]], keep: int = 6) -> str:
    """Últimas vueltas en texto plano para el prompt (memoria corta)."""
    parts = []
    for h in history[-keep:]:
        action = h.get("action")
        if action:
            parts.append(
                f"Pensamiento: {h.get('thought', '')}\n"
                f"Acción: {action.get('tool')} {action.get('args') or {}}\n"
                f"Observación: {h.get('observation', '')}"
            )
        else:
            parts.append(f"Pensamiento: {h.get('thought', '')}")
    return "\n---\n".join(parts)


class ChatModel:
    """Adapter fino sobre cualquier endpoint OpenAI-compatible."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "",
        api_key: str = "",
        role: str = "operator",
        timeout: float = 60.0,
        max_tokens: int | None = None,  # None: 2048 nativas, 512 texto
        transport: httpx.BaseTransport | None = None,
        native_tools: bool | None = None,  # None: auto por familia
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.role = role
        self.timeout = timeout
        self.native_tools = (
            any(tag in model.lower() for tag in NATIVE_TOOL_MODELS)
            if native_tools is None else native_tools
        )
        self.max_tokens = (NATIVE_MAX_TOKENS if self.native_tools else 512
                           if max_tokens is None else max_tokens)
        self.usage_total = {"prompt_tokens": 0, "completion_tokens": 0}  # piloto
        self._transport = transport

    def decide(self, goal: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        user = goal
        if history:
            user += "\n\nHistorial:\n" + render_history(history)
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": self._system()},
                {"role": "user", "content": user},
            ],
        }
        if self.native_tools:
            body["tools"] = native_tools_payload(self.role)
            body["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self._transport is not None:
            with httpx.Client(transport=self._transport) as http:
                resp = http.post(self.url, json=body, headers=headers)
        else:
            with httpx.Client(timeout=self.timeout) as http:
                resp = http.post(self.url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        self.usage_total["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
        self.usage_total["completion_tokens"] += int(usage.get("completion_tokens", 0))
        message = data["choices"][0]["message"]
        if self.native_tools:
            return self._native_step(message)
        return parse_step(message["content"])

    def _system(self) -> str:
        return native_system_prompt(self.role) if self.native_tools \
            else system_prompt(self.role)

    @staticmethod
    def _native_step(message: dict[str, Any]) -> dict[str, Any]:
        """Traduce respuesta tool-nativa al paso del loop.

        Con tool_calls: la primera es la acción (el loop hace UNA por turno).
        Sin tool_calls: el texto es la respuesta final directa.
        """
        calls = message.get("tool_calls") or []
        if calls:
            fn = calls[0].get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                raise ValueError(f"argumentos no-JSON: {fn.get('arguments')!r}")
            thought = (message.get("content") or "").strip() \
                or f"pide {fn.get('name')}"
            return {"thought": thought,
                    "action": {"tool": fn.get("name"), "args": args},
                    "answer": None}
        content = (message.get("content") or "").strip()
        if not content:
            raise ValueError("respuesta nativa vacía: sin texto ni tool_calls")
        return {"thought": content, "action": None, "answer": content}
