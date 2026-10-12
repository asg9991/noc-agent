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
