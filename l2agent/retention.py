"""Retención y rotación de los artefactos con datos del cliente (P9).

Todo artefacto con datos del cliente en claro tiene vida acotada (la
auditoría 2026-09-10 marcó su ausencia como deuda):

- `audit.jsonl`: historia de decisiones. Poda por edad (ventana por defecto
  90 días) y rotación por tamaño (5 MiB por archivo, 5 rotados conservados).
- `outbox.jsonl` (+ `.cooldown.json`): transporte, no historia — ventana más
  corta (30 días).
- `watch.db`: `sweeps` (heartbeat) se podan por edad; `observations` solo
  cuando están `inactive`. Regla dura: una observación activa jamás se borra
  (si no, el problema volvería a sonar como NUEVO).

Rotar no reescribe historia: el archivo rotado queda sellado con su
contenido completo; la poda de edad elimina únicamente lo expirado por
política. Líneas sin `ts` parseable se conservan (borrar lo que no se
entiende sería perder auditoría).

Procedimiento operativo y cron: docs/runbook-operativo.md. Backup offsite
del estado: P14 del backlog.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from l2agent.notify import _cooldown_path, _load_cooldown, _save_cooldown

DEFAULT_AUDIT_DAYS = 90.0
DEFAULT_OUTBOX_DAYS = 30.0
DEFAULT_DB_DAYS = 90.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_KEEP_ROTATED = 5

# Nombres emitidos por la rotación: audit.jsonl.<UTC stamp>[-N]
_ROTATED_RE = re.compile(r"^audit\.jsonl\.\d{8}T\d{6}Z(?:-\d+)?$")


def _cutoff(now: float, max_age_days: float) -> float:
    return now - max_age_days * 86400.0


def _parse_iso(value: Any) -> float | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _audit_ts(raw: str) -> float | None:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _parse_iso(obj.get("ts")) if isinstance(obj, dict) else None


def _outbox_ts(raw: str) -> float | None:
    try:
        obj = json.loads(raw)
        return float(obj["ts"]) if isinstance(obj, dict) else None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _prune_jsonl(path: Path, cutoff: float,
                 ts_of: Callable[[str], float | None]) -> tuple[int, int]:
    """Reescribe el archivo sin las líneas expiradas. (kept, dropped)."""
    kept = dropped = 0
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        ts = ts_of(raw)
        if ts is not None and ts < cutoff:
            dropped += 1
            continue
        kept += 1
        out.append(raw)
    path.write_text("".join(line + "\n" for line in out), encoding="utf-8")
    return kept, dropped


def prune_audit(path: str | Path, *,
                max_age_days: float = DEFAULT_AUDIT_DAYS,
                max_bytes: int = DEFAULT_MAX_BYTES,
                keep_rotated: int = DEFAULT_KEEP_ROTATED,
                now: float | None = None) -> dict[str, Any]:
    """Poda por edad y rota por tamaño el log de auditoría."""
    ts_now = time.time() if now is None else now
    cutoff = _cutoff(ts_now, max_age_days)
    p = Path(path)
    kept = dropped = files_removed = 0

    files = [p] if p.exists() else []
    if p.parent.exists():
        files += sorted(f for f in p.parent.iterdir()
                        if _ROTATED_RE.match(f.name))
    for f in files:
        k, d = _prune_jsonl(f, cutoff, _audit_ts)
        kept += k
        dropped += d
        if f != p and f.stat().st_size == 0:
            f.unlink()
            files_removed += 1

    rotated_name = None
    if p.exists() and p.stat().st_size > max_bytes:
        stamp = datetime.fromtimestamp(ts_now, tz=timezone.utc
                                       ).strftime("%Y%m%dT%H%M%SZ")
        target = p.parent / f"{p.name}.{stamp}"
        n = 1
        while target.exists():
            target = p.parent / f"{p.name}.{stamp}-{n}"
            n += 1
        p.rename(target)
        rotated_name = target.name

    if p.parent.exists():
        rotated = sorted(f for f in p.parent.iterdir()
                         if _ROTATED_RE.match(f.name))
        for f in rotated[:max(0, len(rotated) - keep_rotated)]:
            f.unlink()
            files_removed += 1

    return {"kept": kept, "dropped": dropped, "rotated": rotated_name,
            "files_removed": files_removed}


def prune_outbox(path: str | Path, *,
                 max_age_days: float = DEFAULT_OUTBOX_DAYS,
                 now: float | None = None) -> dict[str, Any]:
    """Poda el outbox de transporte y su estado de cooldown."""
    ts_now = time.time() if now is None else now
    cutoff = _cutoff(ts_now, max_age_days)
    p = Path(path)
    kept, dropped = (0, 0) if not p.exists() else _prune_jsonl(
        p, cutoff, _outbox_ts)

    cooled = _load_cooldown(_cooldown_path(p))
    fresh = {k: v for k, v in cooled.items() if v >= cutoff}
    cooldown_dropped = len(cooled) - len(fresh)
    if cooldown_dropped:
        _save_cooldown(_cooldown_path(p), fresh)

    return {"kept": kept, "dropped": dropped,
            "cooldown_dropped": cooldown_dropped}


def prune_db(db_path: str | Path, *,
             max_age_days: float = DEFAULT_DB_DAYS,
             now: float | None = None) -> dict[str, Any]:
    """Poda sweeps viejos e observaciones inactivas viejas del watch.

    Una observación `active` jamás se borra: la baseline define la
    taxonomía NUEVO/RECURRENTE y borrarla re-alaría problemas vivos.
    """
    ts_now = time.time() if now is None else now
    cutoff = _cutoff(ts_now, max_age_days)
    p = Path(db_path)
    if not p.exists():
        return {"sweeps_dropped": 0, "observations_dropped": 0}
    conn = sqlite3.connect(p)
    try:
        sweeps = conn.execute(
            "DELETE FROM sweeps WHERE ts < ?", (cutoff,)).rowcount
        obs = conn.execute(
            "DELETE FROM observations WHERE status = 'inactive'"
            " AND last_seen < ?", (cutoff,)).rowcount
        conn.commit()
        if sweeps or obs:
            conn.execute("VACUUM")
    finally:
        conn.close()
    return {"sweeps_dropped": sweeps, "observations_dropped": obs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m l2agent.retention",
        description="Poda y rota los artefactos con datos del cliente (P9).")
    parser.add_argument("--audit", default="audit.jsonl",
                        help="log de auditoría JSONL")
    parser.add_argument("--outbox", default="outbox.jsonl",
                        help="outbox de transporte JSONL")
    parser.add_argument("--db", default="watch.db",
                        help="baseline SQLite del watch")
    parser.add_argument("--days", type=float, default=DEFAULT_AUDIT_DAYS,
                        help="ventana de retención del audit (días)")
    parser.add_argument("--outbox-days", type=float,
                        default=DEFAULT_OUTBOX_DAYS,
                        help="ventana de retención del outbox (días)")
    parser.add_argument("--db-days", type=float, default=DEFAULT_DB_DAYS,
                        help="ventana de retención de la DB (días)")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                        help="tamaño que dispara la rotación del audit")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_ROTATED,
                        help="archivos rotados conservados")
    parser.add_argument("--now", type=float, default=None,
                        help="epoch de referencia (tests o cron determinista)")
    args = parser.parse_args(argv)
    report = {
        "audit": prune_audit(args.audit, max_age_days=args.days,
                             max_bytes=args.max_bytes,
                             keep_rotated=args.keep, now=args.now),
        "outbox": prune_outbox(args.outbox, max_age_days=args.outbox_days,
                               now=args.now),
        "db": prune_db(args.db, max_age_days=args.db_days, now=args.now),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
