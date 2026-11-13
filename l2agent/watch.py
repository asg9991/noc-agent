"""Barrido proactivo del L2: baseline en SQLite, taxonomía, heartbeat.

Cero tokens: habla directo al hub (sin LLM). El LLM entra después, solo
si hay novedad (barato primero, runbook §9). Conceptos:

- Estado: cada barrido deja huella en DB; la novedad se define CONTRA
  la huella, no contra el barrido anterior en memoria.
- Histéresis: una sola ausencia no es recuperación (flapping del
  simulador/red); hacen falta ausencias seguidas para declarar RECUPERADO.
- Heartbeat: cada barrido firma la hora; si nadie firma hace mucho, el
  problema es el vigilante (dead-man switch).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol

from l2agent.errors import classify, result_for


class SweepClient(Protocol):
    def call_tool(self, name: str, args: dict[str, Any] | None = ...) -> Any: ...


RECOVER_AFTER_MISSING = 2  # ausencias seguidas para declarar recuperado

SCHEMA = """
CREATE TABLE IF NOT EXISTS sweeps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    active_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS observations (
    eventid TEXT PRIMARY KEY,
    host TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    missing_streak INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    recovered_reported INTEGER NOT NULL DEFAULT 0
);
"""


def _db(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    return conn


def _problem_list(result: Any) -> list[dict[str, Any]]:
    """Normaliza un tools/call a la lista de problemas.

    Acepta la forma real del hub (envelope MCP: content[0].text con guarda
    [System: ...] y payload {"problems": [...]} o lista) y la lista plana
    de los fakes. Un error de tool o una forma irreconocida NO se tragan:
    un barrido que no entendió la respuesta jamás declara "sin problemas"
    (ese vacío silencioso era el bug P1 del backlog).
    """
    if isinstance(result, list):
        return [p for p in result if isinstance(p, dict)]
    if not isinstance(result, dict):
        raise ValueError(f"resultado de tool inesperado: {type(result).__name__}")
    if result.get("isError"):
        raise RuntimeError(f"hub tool error: {str(result)[:200]}")
    problems = result.get("problems")
    if isinstance(problems, list):
        return [p for p in problems if isinstance(p, dict)]
    text = ""
    for item in result.get("content") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"]
            break
    if not text:
        sc = result.get("structuredContent")
        if isinstance(sc, dict) and isinstance(sc.get("result"), str):
            text = sc["result"]
    payload = text.strip()
    if payload.startswith("[System:"):
        _, _, payload = payload.partition("\n")
    payload = payload.strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"texto de tool no parsea JSON: {text[:120]!r}") from exc
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    if isinstance(data, dict) and isinstance(data.get("problems"), list):
        return [p for p in data["problems"] if isinstance(p, dict)]
    raise ValueError(f"forma de payload no reconocida: {payload[:120]!r}")


def sweep(client: SweepClient, db_path: str | Path,
          now: float | None = None) -> dict[str, Any]:
    """Un barrido: snapshot del hub, clasifica contra baseline, firma."""
    ts = time.time() if now is None else now
    problems = _problem_list(client.call_tool("problem_active_get", {}))
    current = {}
    for p in problems:
        eid = str(p.get("eventid", ""))
        if eid:
            current[eid] = p
    new, recurrent, recovered = [], [], []
    conn = _db(db_path)
    try:
        for eid, p in current.items():
            row = conn.execute(
                "SELECT status FROM observations WHERE eventid = ?", (eid,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO observations "
                    "(eventid, host, severity, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (eid, str(p.get("host", "")),
                     str(p.get("severity", "")), ts, ts),
                )
                new.append({"eventid": eid, **{k: p.get(k, "") for k in ("host", "severity")}})
            else:
                conn.execute(
                    "UPDATE observations SET last_seen = ?, missing_streak = 0,"
                    " host = ?, severity = ?,"
                    " status = 'active', recovered_reported = 0"
                    " WHERE eventid = ?",
                    (ts, str(p.get("host", "")),
                     str(p.get("severity", "")), eid),
                )
                # Reaparecido tras recuperado = NUEVO (re-alarma); si nunca
                # se fue, es RECURRENTE (aviso sin alarma).
                (new if row[0] == "inactive" else recurrent).append(
                    {"eventid": eid, "host": str(p.get("host", "")),
                     "severity": str(p.get("severity", ""))})
        for (eid,) in conn.execute(
                "SELECT eventid FROM observations WHERE status = 'active'"):
            if eid not in current:
                streak = conn.execute(
                    "SELECT missing_streak FROM observations WHERE eventid = ?",
                    (eid,)).fetchone()[0] + 1
                conn.execute(
                    "UPDATE observations SET missing_streak = ? WHERE eventid = ?",
                    (streak, eid))
                if streak == RECOVER_AFTER_MISSING:
                    conn.execute(
                        "UPDATE observations SET status = 'inactive',"
                        " recovered_reported = 1 WHERE eventid = ?", (eid,))
                    info = conn.execute(
                        "SELECT host, severity FROM observations WHERE eventid = ?",
                        (eid,)).fetchone()
                    recovered.append({"eventid": eid, "host": info[0],
                                      "severity": info[1]})
        conn.execute(
            "INSERT INTO sweeps (ts, active_count) VALUES (?, ?)",
            (ts, len(current)))
        conn.commit()
    finally:
        conn.close()
    return {"new": new, "recurrent": recurrent, "recovered": recovered,
            "heartbeat_ts": ts, "active_count": len(current)}


def is_alive(db_path: str | Path, max_age_s: float = 3600,
             now: float | None = None) -> bool:
    """Dead-man switch: ¿firmó algún barrido dentro de la ventana?"""
    ts = time.time() if now is None else now
    p = Path(db_path)
    if not p.exists():
        return False
    conn = sqlite3.connect(p)
    try:
        row = conn.execute(
            "SELECT MAX(ts) FROM sweeps").fetchone()
    finally:
        conn.close()
    return row[0] is not None and (ts - row[0]) <= max_age_s


def main(argv: list[str] | None = None, *, client: SweepClient | None = None) -> int:
    """CLI para cron/systemd: barre, informa novedad, sale con código."""
    from agent.mcp_client import MCPClient  # import tardío: tests no lo piden

    parser = argparse.ArgumentParser(description="Barrido watch del L2 (0 tokens)")
    parser.add_argument("--db", default="watch.db", help="baseline SQLite")
    parser.add_argument("--max-age", type=float, default=3600,
                        help="ventana del heartbeat en segundos (solo chequeo)")
    parser.add_argument("--check-alive", action="store_true",
                        help="no barre: solo dice si el vigilante sigue vivo")
    parser.add_argument("--notify", action="store_true",
                        help="aplica compuertas de aviso al barrido (alarma/digest)")
    parser.add_argument("--outbox", default="outbox.jsonl",
                        help="buzón de alarmas para el futuro adapter")
    parser.add_argument("--min-severity", default="High",
                        help="severidad mínima que alarma (default High)")
    args = parser.parse_args(argv)
    if args.check_alive:
        vivo = is_alive(args.db, args.max_age)
        print("vivo" if vivo else "MUERTO")
        return 0 if vivo else 1
    if client is None:
        client = MCPClient()
    init = getattr(client, "initialize", None)
    if callable(init):
        try:
            init()  # el hub exige handshake con sesión antes de tools/call
        except Exception as exc:
            result = result_for(classify(exc))
            if result == "error_auth":
                print("corté con alarma: el hub rechazó la credencial en el "
                      "handshake (401/403 o bearer inválido); rotá el token.")
            else:
                print(f"corté: no hay sesión con el hub ({result}): "
                      f"{str(exc)[:200]}")
            return 1
    r = sweep(client, args.db)
    print(f"nuevos={len(r['new'])} recurrentes={len(r['recurrent'])} "
          f"recuperados={len(r['recovered'])} activos={r['active_count']}")
    for p in r["new"]:
        print(f"  NUEVO {p['eventid']} {p.get('host','')} {p.get('severity','')}")
    for p in r["recovered"]:
        print(f"  RECUPERADO {p['eventid']} {p.get('host','')}")
    if args.notify:
        from l2agent import notify as notify_mod
        d = notify_mod.decide(r, outbox_path=args.outbox,
                              min_severity=args.min_severity)
        print(f"aviso: alarmas={len(d['alarms'])} digest={len(d['digest'])}")
        for a in d["alarms"]:
            print(f"  ALARMA {a['subject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
