"""Bitácora de decisiones del agente L2 (arquitectura §2: auditoría completa).

Cada decisión del loop queda como una línea JSON: quién pidió qué, cuándo,
desde qué canal y con qué resultado. Append-only: se agrega, nunca se
reescribe. Además cada línea se encadena con la anterior (`prev_hash` /
`entry_hash`, hash-chain ligera): modificar, borrar o insertar una línea
pasada rompe la cadena y `--verify` lo detecta. Sin log no hay agente: hay
caja negra.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _canonical(record: dict[str, Any]) -> bytes:
    """Forma canónica de una línea para hashear (sin su propio entry_hash)."""
    payload = {k: v for k, v in record.items() if k != "entry_hash"}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _entry_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(record)).hexdigest()


def _tail_hash(p: Path) -> str:
    """entry_hash de la última línea ("" si no hay o la línea es legada)."""
    try:
        last = ""
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return ""
        record = json.loads(last)
        if isinstance(record, dict):
            return str(record.get("entry_hash", ""))
        return ""
    except (OSError, json.JSONDecodeError):
        return ""


def log_decision(
    path: str | Path,
    *,
    actor: str,
    action: str,
    channel: str,
    result: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Agrega una decisión al log JSONL y devuelve el registro escrito.

    La línea se encadena con la anterior (hash-chain ligera). Supone un solo
    proceso escribiendo (el loop L2); el lock del archivo protege de la
    carrera entre hebras del mismo proceso.
    """
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
    fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # serializa writers (hebras/procesos)
        os.fchmod(fd, 0o600)  # permisos estrictos (P25), también en legados
        record["prev_hash"] = _tail_hash(p)
        record["entry_hash"] = _entry_hash(record)
        os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n")
                 .encode("utf-8"))
    finally:
        os.close(fd)  # close libera el lock
    return record


def verify_audit(path: str | Path) -> dict[str, Any]:
    """Verifica la cadena de integridad del log.

    Devuelve {"ok", "sealed", "unsealed", "broken_line"}: `ok` es False si
    hay una línea modificada, borrada o insertada (la primera con problema
    queda en `broken_line`, 1-based). Líneas sin sellar solo se aceptan como
    prefijo legado: una sin sellar después de una sellada es inyección.
    """
    result: dict[str, Any] = {"ok": True, "sealed": 0, "unsealed": 0,
                              "broken_line": None}
    p = Path(path)
    if not p.exists():
        return result
    expected_prev = ""
    sealed_seen = False
    for n, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            result.update(ok=False, broken_line=n)
            return result
        if not isinstance(record, dict):
            result.update(ok=False, broken_line=n)  # línea corrupta/inyectada
            return result
        if "entry_hash" not in record:
            if sealed_seen:
                result.update(ok=False, broken_line=n)  # inyección
                return result
            result["unsealed"] += 1
            expected_prev = ""
            continue
        if (record.get("prev_hash") != expected_prev
                or record.get("entry_hash") != _entry_hash(record)):
            result.update(ok=False, broken_line=n)
            return result
        expected_prev = str(record["entry_hash"])
        result["sealed"] += 1
        sealed_seen = True
    return result


def seal_audit(path: str | Path) -> dict[str, Any]:
    """Sella la historia: rechaza la línea con la anterior y la hashea.

    Migración para archivos legados (líneas sin integridad). Se niega si la
    cadena ya sellada está rota: sellar taparía una manipulación. Reescribe
    de forma atómica preservando todo el contenido.
    """
    p = Path(path)
    v = verify_audit(p)
    if not v["ok"]:
        raise ValueError(
            f"cadena rota en la línea {v['broken_line']}: sellar taparía "
            "una manipulación — investigar antes de continuar")
    if not p.exists() or v["sealed"] == 0 and v["unsealed"] == 0:
        return v
    lines = [x for x in p.read_text(encoding="utf-8").splitlines()
             if x.strip()]
    sealed: list[str] = []
    prev = ""
    for raw in lines:
        record = json.loads(raw)
        record["prev_hash"] = prev
        record["entry_hash"] = _entry_hash(record)
        prev = str(record["entry_hash"])
        sealed.append(json.dumps(record, ensure_ascii=False))
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(x + "\n" for x in sealed))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)  # atómico
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return verify_audit(p)


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
    """CLI: informe por nivel (default), --verify o --seal sobre el log."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m l2agent.audit",
        description="Audit del agente L2: informe por nivel (§5) o "
                    "integridad (P25).")
    parser.add_argument("path", help="log JSONL de decisiones")
    parser.add_argument("--since", default=None,
                        help="fecha ISO mínima (ej. 2026-11-01)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true",
                      help="verifica la cadena de integridad; exit 0 intacto,"
                           " 2 sin sellar, 1 manipulado")
    mode.add_argument("--seal", action="store_true",
                      help="sella la historia legada (rechaza si hay cadena "
                           "rota)")
    args = parser.parse_args(argv)
    if args.since and (args.verify or args.seal):
        import sys
        print("error: --since solo aplica al informe por nivel",
              file=sys.stderr)
        return 1
    if args.verify:
        result = verify_audit(args.path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            return 1
        return 2 if result["unsealed"] else 0
    if args.seal:
        try:
            result = seal_audit(args.path)
        except ValueError as exc:
            print(f"sellado rechazado: {exc}")
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(routing_report(args.path, since=args.since),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
