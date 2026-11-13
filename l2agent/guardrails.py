"""Reglas de la Casa 3: lo prohibido por escrito y el freno de writes.

Tres piezas, en orden de uso por el loop (T4):

- classify(): ¿esta tool está permitida? Si no, ¿parece write o es desconocida?
- denied(): registra la denegación en el audit (T1) y avisa al hook.
- require_confirmation(): freno de writes futuros. Hoy todo llega sin
  confirmar y se frena; cuando exista el modal humano, confirmed=True deja
  pasar y audita QUIÉN autorizó.

La lista de lo prohibido NO se duplica acá: se referencia la de
mcp/catalog.py (fuente única). El hook de alarma nunca abre el freno:
si el hook rompe, la denegación igual queda (fail-closed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mcp import catalog
from mcp.catalog import is_allowed

from l2agent.audit import log_decision

# Fuente única de lo prohibido: el mismo tuple que valida el catálogo.
_WRITE_MARKERS = catalog._WRITE_MARKERS

WRITE_ATTEMPT = "write_attempt"
UNKNOWN_TOOL = "unknown_tool"

DeniedHook = Callable[[dict[str, Any]], None] | None


def classify(name: Any) -> str | None:
    """None si está curada; si no, 'write_attempt' o 'unknown_tool'."""
    if is_allowed(name):
        return None
    lowered = name.lower() if isinstance(name, str) else ""
    if lowered == "raw_api_call" or any(m in lowered for m in _WRITE_MARKERS):
        return WRITE_ATTEMPT
    return UNKNOWN_TOOL


def _notify(hook: DeniedHook, record: dict[str, Any]) -> None:
    if hook is None:
        return
    try:
        hook(record)
    except Exception:
        pass  # fail-closed: una alarma rota jamás abre el freno


def denied(
    name: str,
    *,
    actor: str,
    channel: str,
    audit_path: str | Path,
    reason: str | None = None,
    on_denied: DeniedHook = None,
) -> dict[str, Any]:
    """Registra una denegación (result='denegado'), avisa al hook y la devuelve."""
    record = log_decision(
        audit_path,
        actor=actor,
        action=name,
        channel=channel,
        result="denegado",
        detail={"reason": reason or classify(name) or "manual"},
    )
    _notify(on_denied, record)
    return record


def require_confirmation(
    action: str,
    *,
    confirmed: bool = False,
    actor: str = "l2",
    channel: str = "lab",
    audit_path: str | Path,
    on_denied: DeniedHook = None,
) -> bool:
    """Freno de writes. Sin confirmación: registra, avisa y levanta.

    Con confirmed=True (futuro modal humano): deja pasar y audita la
    autorización. Toda autorización de write queda registrada: quién, qué,
    cuándo. Sin excepciones.
    """
    if confirmed:
        log_decision(
            audit_path,
            actor=actor,
            action=action,
            channel=channel,
            result="confirmado",
            detail={},
        )
        return True
    denied(action, actor=actor, channel=channel, audit_path=audit_path, on_denied=on_denied)
    raise PermissionError(f"Write {action!r} requiere confirmación explícita")
