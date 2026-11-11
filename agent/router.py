"""Router L0/L1/L2 segun doctrina de costos (docs/arquitectura.md).

L0: reglas exactas (0 tokens) -> handlers directos.
L1: clasificador por keywords simple -> MISMO handler de L0.
L2: agente local l2agent (loop + catálogo curado); sin LLM_MODEL configurado
    avisa en vez de romper.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Protocol

from l2agent.guardrails import DeniedHook
from l2agent.loop import run_loop
from l2agent.main import build_client_from_env, build_model_from_env
from l2agent.model import ChatModel
from l2agent.tools import ToolClient


class ZabbixReader(Protocol):
    def get_version(self) -> str: ...
    def get_problems(self, limit: int = ...) -> list[dict[str, Any]]: ...
    def get_hosts(self, limit: int = ...) -> list[dict[str, Any]]: ...


L2_NO_MODEL = (
    "L2 necesita un cerebro: definí LLM_MODEL (y opcionalmente LLM_BASE_URL) "
    "y reintentá. Sin modelo no hay agente, solo stub."
)


def handle_estado(client: ZabbixReader) -> str:
    version = client.get_version()
    problems = client.get_problems(limit=100)
    hosts = client.get_hosts(limit=100)
    return (
        f"Zabbix {version} | hosts: {len(hosts)} | "
        f"problemas activos: {len(problems)}"
    )


def handle_ack(client: ZabbixReader) -> str:
    problems = client.get_problems(limit=5)
    if not problems:
        return "Sin problemas activos para hacer ack."
    names = "; ".join(p.get("name", "?") for p in problems[:5])
    return (
        f"Hay {len(problems)} problema(s) reciente(s). "
        f"ACK manual requerido via Zabbix UI. Ej: {names}"
    )


def handle_l2(
    text: str,
    *,
    model: ChatModel | None = None,
    client: ToolClient | None = None,
    role: str = "operator",
    audit_path: str = "audit.jsonl",
    on_denied: DeniedHook = None,
    actor: str = "l2",
    channel: str = "lab",
) -> str:
    """L2 real: el objetivo corre por el loop con el catálogo curado.

    Sin inyección (producción/CLI): modelo y cliente salen del env. Sin
    LLM_MODEL no se rompe: avisa qué falta. En tests se inyectan fakes.
    `actor`/`channel` son la identidad real del origen (arquitectura §7):
    llegan hasta run_loop y quedan en cada registro de audit.
    """
    try:
        the_model = model if model is not None else build_model_from_env(role)
        the_client = client if client is not None else build_client_from_env()
    except SystemExit:
        return L2_NO_MODEL
    return run_loop(
        text, model=the_model, client=the_client,
        actor=actor, channel=channel,
        audit_path=audit_path, on_denied=on_denied,
    )


Handler = Callable[[ZabbixReader], str]

# L0: comandos exactos (normalizados: strip + lower).
L0_EXACT: dict[str, Handler] = {
    "estado": handle_estado,
    "ack": handle_ack,
}

# L1: palabras clave -> handler L0 (mismo handler, sin LLM). La coincidencia
# es por PALABRA COMPLETA sin tildes ("versión" matchea "version"), nunca por
# subcadena: "backup" no trae "ack" ni "estación" trae "estado".
_ACENTOS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def _words(text: str) -> set[str]:
    """Palabras en minúscula, sin tildes ni puntuación."""
    limpio = text.translate(_ACENTOS).lower()
    return set(re.findall(r"[a-z0-9]+", limpio))


L1_KEYWORDS: list[tuple[frozenset[str], Handler]] = [
    (frozenset({"problema", "problemas", "alerta", "alertas", "ack"}), handle_ack),
    (frozenset({"estado", "version", "versions", "versiones",
                "host", "hosts", "salud"}), handle_estado),
]

# Consultas de estado que no nombran la palabra "estado":
# "¿cómo está el zabbix?", "cómo están los servers".
_ESTADO_RE = re.compile(r"\bcomo esta(?:s|n)?\b")


def route_l0(text: str) -> Handler | None:
    return L0_EXACT.get(text.strip().lower())


def classify_l1(text: str) -> Handler | None:
    words = _words(text)
    for keywords, handler in L1_KEYWORDS:
        if words & keywords:
            return handler
    if _ESTADO_RE.search(text.translate(_ACENTOS).lower()):
        return handle_estado
    return None


def route(text: str, client: ZabbixReader,
          actor: str = "l2", channel: str = "lab") -> tuple[str, str]:
    """Devuelve (nivel, respuesta). Niveles: L0 | L1 | L2.

    `actor`/`channel` identifican al origen real (usuario de canal) y se
    propagan al audit cuando la interacción llega a L2.
    """
    handler = route_l0(text)
    if handler is not None:
        return ("L0", handler(client))
    handler = classify_l1(text)
    if handler is not None:
        return ("L1", handler(client))
    return ("L2", handle_l2(text, actor=actor, channel=channel))
