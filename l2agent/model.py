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
        max_tokens: int = 512,  # decisiones cortas: freno de costo y de cuota
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.role = role
        self.timeout = timeout
        self.max_tokens = max_tokens
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
                {"role": "system", "content": system_prompt(self.role)},
                {"role": "user", "content": user},
            ],
        }
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
        content = data["choices"][0]["message"]["content"]
        return parse_step(content)
