"""Workflow del agente L2: el loop observa → piensa → actúa → verifica.

El patrón es viejo y probado, solo cambia quién piensa adentro:

- ReAct (2022, agentes LLM): Thought → Action → Observation, repetir.
- OODA (Boyd, aviación): Observe → Orient → Decide → Act, repetir.
- Control clásico (el termostato): sensor → comparador → actuador, repetir.
- Tu arquitectura §1: Monitorear → Notificar → Comprender → Asistir → Actuar.

Acá el "orient/decide" lo ocupa un modelo (inyectado como callable: en lab
un fake guionado, en producción el LLM). El resto es determinista y testeable.

Tres reglas estructurales, sin excepción:

1. Tope de iteraciones: todo loop termina (costo + blast radius acotados).
2. Anti-repetición: misma acción dos veces = estancado, se corta.
3. Anti-alucinación por construcción: las observaciones SOLO salen de run()
   (datos reales de tools); el modelo nunca genera una observación. Si no hay
   dato, el modelo lo ve y lo dice.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from l2agent.audit import log_decision
from l2agent.guardrails import DeniedHook, classify, denied
from l2agent.tools import ToolClient, run as run_tool

MAX_ITERS = 5  # vueltas máximas por objetivo (terminación + costo acotados)


class Model(Protocol):
    def decide(self, goal: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        """Devuelve {'thought': str, 'action': {'tool', 'args'} | None,
        'answer': str | None}. Con acción se ejecuta; con respuesta se cierra."""
        ...


def run_loop(
    goal: str,
    *,
    model: Model,
    client: ToolClient,
    actor: str = "l2",
    channel: str = "lab",
    audit_path: str,
    max_iters: int = MAX_ITERS,
    on_denied: DeniedHook = None,
) -> str:
    """Corre el loop hasta respuesta, tope o estancamiento. Devuelve texto."""
    history: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Handshake perezoso: si el cliente sabe inicializar sesión (MCP real),
    # se conecta solo. Los fakes de tests no lo tienen y no les pasa nada.
    init = getattr(client, "initialize", None)
    if callable(init):
        init()

    for _ in range(max_iters):
        step = model.decide(goal, history)
        thought = step.get("thought", "")
        action = step.get("action")
        if action is None:
            answer = step.get("answer") or "corté: el modelo cerró sin decisión."
            usage = getattr(model, "usage_total", None) or {}
            log_decision(audit_path, actor=actor, action="respuesta_final",
                         channel=channel, result="ok",
                         detail={"answer": answer[:500], "usage": usage})
            return answer
        tool = action.get("tool", "")
        args = action.get("args") or {}
        key = tool + ":" + json.dumps(args, sort_keys=True)
        if key in seen:
            return (
                f"corté: el modelo está repitiendo la acción {tool} "
                "con los mismos parámetros (posible loop)."
            )
        seen.add(key)
        reason = classify(tool)
        if reason is not None:
            denied(tool, actor=actor, channel=channel, audit_path=audit_path,
                   reason=reason, on_denied=on_denied)
            observation = (
                f"denegado ({reason}): la tool {tool!r} no está permitida."
            )
            result = "denegado"
        else:
            observation = run_tool(client, tool, args)
            result = "error" if observation.startswith("error:") else "ok"
        log_decision(audit_path, actor=actor, action=tool, channel=channel,
                     result=result,
                     detail={"args": args, "observation": observation[:500]})
        history.append({"thought": thought, "action": action,
                        "observation": observation})

    last = history[-1]["observation"][:200] if history else "sin observaciones"
    return f"corté por tope de {max_iters} iteraciones; última observación: {last}"
