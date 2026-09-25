"""Router L0/L1/L2 segun doctrina de costos (docs/arquitectura.md).

L0: reglas exactas (0 tokens) -> handlers directos.
L1: clasificador por keywords simple -> MISMO handler de L0.
L2: stub, no implementado (escala a agente/MCP en fases siguientes).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class ZabbixReader(Protocol):
    def get_version(self) -> str: ...
    def get_problems(self, limit: int = ...) -> list[dict[str, Any]]: ...
    def get_hosts(self, limit: int = ...) -> list[dict[str, Any]]: ...


L2_FALLBACK = "no implementado, usar MCP"


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


def handle_l2(_text: str) -> str:
    return L2_FALLBACK


Handler = Callable[[ZabbixReader], str]

# L0: comandos exactos (normalizados: strip + lower).
L0_EXACT: dict[str, Handler] = {
    "estado": handle_estado,
    "ack": handle_ack,
}

# L1: keywords -> handler L0 (mismo handler, sin LLM).
L1_KEYWORDS: list[tuple[str, Handler]] = [
    ("problema", handle_ack),
    ("problemas", handle_ack),
    ("alerta", handle_ack),
    ("alertas", handle_ack),
    ("ack", handle_ack),
    ("estado", handle_estado),
    ("version", handle_estado),
    ("hosts", handle_estado),
    ("salud", handle_estado),
]


def route_l0(text: str) -> Handler | None:
    return L0_EXACT.get(text.strip().lower())


def classify_l1(text: str) -> Handler | None:
    lowered = text.strip().lower()
    for keyword, handler in L1_KEYWORDS:
        if keyword in lowered:
            return handler
    return None


def route(text: str, client: ZabbixReader) -> tuple[str, str]:
    """Devuelve (nivel, respuesta). Niveles: L0 | L1 | L2."""
    handler = route_l0(text)
    if handler is not None:
        return ("L0", handler(client))
    handler = classify_l1(text)
    if handler is not None:
        return ("L1", handler(client))
    return ("L2", handle_l2(text))
