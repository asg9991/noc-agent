"""Bitácora de decisiones del agente L2 (arquitectura §2: auditoría completa).

Cada decisión del loop queda como una línea JSON: quién pidió qué, cuándo,
desde qué canal y con qué resultado. Append-only: se agrega, nunca se reescribe.
Sin log no hay agente: hay caja negra.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_decision(
    path: str | Path,
    *,
    actor: str,
    action: str,
    channel: str,
    result: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Agrega una decisión al log JSONL y devuelve el registro escrito."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),  # cuándo, UTC, ISO-8601
        "actor": actor,  # quién (usuario de canal o técnico)
        "action": action,  # qué (tool usada o decisión tomada)
        "channel": channel,  # desde dónde (lab, mail, discord...)
        "result": result,  # resultado corto: ok | error | denegado...
        "detail": detail or {},  # resto: parámetros, motivo, conteos
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def routing_report(path: str | Path, *,
                   since: str | None = None) -> dict[str, Any]:
    """Distribución de decisiones de routing (arquitectura §5).

    Agrega las trazas `action="route"` del log por nivel (L0/L1/L2),
    handler y actor — el insumo del informe mensual de costos: cuánto
    tráfico resolvió cada nivel barato antes de caer a L2.

    `since` filtra por fecha ISO (prefijo del `ts` del registro), ej.
    "2026-11-01" para el mes en curso.
    """
    levels: dict[str, int] = {}
    handlers: dict[str, int] = {}
    actors: dict[str, int] = {}
    total = 0
    p = Path(path)
    if not p.exists():
        return {"total": 0, "levels": {}, "handlers": {}, "actors": {}}
    for raw in p.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("action") != "route":
            continue
        ts = str(record.get("ts", ""))
        if since and ts < since:
            continue
        total += 1
        level = str(record.get("result", "?"))
        levels[level] = levels.get(level, 0) + 1
        detail = record.get("detail") or {}
        handler = str(detail.get("handler", "?")) if isinstance(
            detail, dict) else "?"
        handlers[handler] = handlers.get(handler, 0) + 1
        actor = str(record.get("actor", "?"))
        actors[actor] = actors.get(actor, 0) + 1
    return {"total": total, "levels": levels,
            "handlers": handlers, "actors": actors}


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m l2agent.audit audit.jsonl [--since 2026-11-01]."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m l2agent.audit",
        description="Informe de distribución por nivel del audit (§5).")
    parser.add_argument("path", help="log JSONL de decisiones")
    parser.add_argument("--since", default=None,
                        help="fecha ISO mínima (ej. 2026-11-01)")
    args = parser.parse_args(argv)
    print(json.dumps(routing_report(args.path, since=args.since),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
