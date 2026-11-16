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

Los symlinks jamás se siguen: un artefacto symlink (o un impostor con nombre
de rotado) se excluye de la poda, la rotación, el tope y la apertura de la
DB, y se reporta como `skipped_symlinks`; su objetivo queda intacto.

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
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from l2agent.audit import (assert_chain_intact, file_lock,
                           log_decision, rechain_lines, split_record_lines)
from l2agent.notify import _cooldown_path, _load_cooldown, _save_cooldown

DEFAULT_AUDIT_DAYS = 90.0
DEFAULT_OUTBOX_DAYS = 30.0
DEFAULT_DB_DAYS = 90.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_KEEP_ROTATED = 5

# Nombres emitidos por la rotación: <basename>.<UTC stamp>[-N]. El patrón
# se deriva del nombre del log para que un --audit con nombre custom también
# gestione sus rotados (blocker S5h de la verificación de P9). Los grupos de
# captura alimentan `_rotated_key`: el orden del cap es por (stamp, n) con n
# NUMÉRICO — el orden lexicográfico invertía Z-10 antes que Z-2 (C4).
def _rotated_re(name: str) -> re.Pattern[str]:
    return re.compile(re.escape(name) + r"\.(\d{8}T\d{6}Z)(?:-(\d+))?\Z")


def _rotated_key(match: re.Match[str]) -> tuple[str, int]:
    return (match.group(1), int(match.group(2) or 0))


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


def _write_lines_atomic(path: Path, lines: list[str]) -> None:
    """Escritura atómica: mkstemp + os.replace (un crash no trunca)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name,
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in lines))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)  # atómico
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _prune_jsonl(path: Path, cutoff: float,
                 ts_of: Callable[[str], float | None],
                 rechain: bool = False,
                 lock: bool = True) -> tuple[int, int]:
    """Reescribe el archivo sin las líneas expiradas. (kept, dropped).

    El ciclo leer-filtrar-escribir corre bajo `file_lock` (C2: una línea
    appendeada a mitad de camino no se pierde) y la escritura es atómica
    vía mkstemp+os.replace (un crash no trunca la historia). `lock=False`
    cuando el llamador ya retiene el lock de la familia del log.
    """
    if path.is_symlink():
        # Defensa en profundidad: jamás leer ni reescribir a través de un
        # symlink — su objetivo vive fuera del alcance gestionado.
        return 0, 0
    kept = dropped = 0
    out: list[str] = []

    def _work() -> None:
        nonlocal kept, dropped
        raw_lines = split_record_lines(path.read_text(encoding="utf-8"))
        for raw in raw_lines:
            ts = ts_of(raw)
            if ts is not None and ts < cutoff:
                dropped += 1
                continue
            kept += 1
            out.append(raw)
        if dropped:
            # A-1: la validación corre sobre la cadena COMPLETA pre-poda —
            # los gaps que crea la propia poda son legítimos; la manipulación
            # previa (hash falso / eslabón perdido) bloquea el re-hasheo.
            if rechain:
                assert_chain_intact(raw_lines)
            new = rechain_lines(out) if rechain else out
            _write_lines_atomic(path, new)

    if lock:
        with file_lock(path):
            _work()
    else:
        _work()
    return kept, dropped


def prune_audit(path: str | Path, *,
                max_age_days: float = DEFAULT_AUDIT_DAYS,
                max_bytes: int = DEFAULT_MAX_BYTES,
                keep_rotated: int = DEFAULT_KEEP_ROTATED,
                now: float | None = None) -> dict[str, Any]:
    """Poda por edad y rota por tamaño el log de auditoría."""
    ts_now = time.time() if now is None else now
    if keep_rotated < 1:
        # keep 0 destruiría todo lo no expirado (incluido lo recién rotado):
        # el tope mínimo es 1 — el archivo recién rotado siempre sobrevive.
        raise ValueError("keep_rotated debe ser >= 1")
    if max_age_days < 0:
        # S3: una ventana negativa ubicaría el cutoff en el futuro y borraría
        # todo lo vigente — la biblioteca protege igual que el CLI.
        raise ValueError("max_age_days debe ser >= 0")
    cutoff = _cutoff(ts_now, max_age_days)
    p = Path(path)
    rotated_re = _rotated_re(p.name)
    kept = dropped = files_removed = 0
    # Un symlink (del log vivo o con nombre de rotado) apunta a datos fuera
    # del alcance gestionado: se excluye de todos los conjuntos y se reporta.
    skipped: set[str] = set()

    files: list[Path] = []
    if p.is_symlink():
        skipped.add(p.name)
    elif p.exists():
        files.append(p)
    if p.parent.exists():
        entries = sorted((f for f in p.parent.iterdir()
                          if rotated_re.match(f.name)),
                         key=lambda f: _rotated_key(rotated_re.match(f.name)))
        skipped.update(f.name for f in entries if f.is_symlink())
        files += [f for f in entries if not f.is_symlink()]
    rotated_name = None
    cap_removed: list[str] = []
    # Un solo lock por familia de log (vivo + rotados): los writers del vivo
    # se serializan con toda la poda (C2) sin sidecars por archivo rotado.
    # Sin archivos que tocar, ni siquiera se crea el sidecar del lock (no-op
    # puro: una corrida sobre un estado ausente no escribe nada).
    has_work = bool(files) or any(rotated_re.match(f.name)
                                  for f in p.parent.iterdir()) \
        if p.parent.exists() else bool(files)
    if has_work:
        with file_lock(p):
            for f in files:
                k, d = _prune_jsonl(f, cutoff, _audit_ts, rechain=True,
                                    lock=False)
                kept += k
                dropped += d
                if f != p and not f.is_symlink() and f.stat().st_size == 0:
                    f.unlink()
                    files_removed += 1

            if (not p.is_symlink() and p.exists()
                    and p.stat().st_size > max_bytes):
                stamp = datetime.fromtimestamp(
                    ts_now, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                target = p.parent / f"{p.name}.{stamp}"
                n = 1
                # ni siquiera se pisa un symlink huérfano en el destino
                while target.exists() or target.is_symlink():
                    target = p.parent / f"{p.name}.{stamp}-{n}"
                    n += 1
                p.rename(target)
                rotated_name = target.name

            if p.parent.exists():
                rotated = sorted(
                    (f for f in p.parent.iterdir()
                     if rotated_re.match(f.name) and f.is_file()
                     and not f.is_symlink()),
                    key=lambda f: _rotated_key(rotated_re.match(f.name)))
                # Orden (stamp, n) numérico: los primeros son los MÁS
                # VIEJOS. El archivo recién rotado es el último (más nuevo)
                # y con keep>=1 siempre sobrevive a su propia run (C4/C6) —
                # salvo relojes no-monotónicos, y por eso la constancia no
                # nombra como vivo a un segmento destruido (R3).
                cap_removed: list[str] = []  # (se reinicia en cada run)
                for f in rotated[:max(0, len(rotated) - keep_rotated)]:
                    # las líneas de un archivo removido por el tope dejan de
                    # estar conservadas: el reporte reconcilia con el final
                    lines = len(split_record_lines(f.read_text(encoding="utf-8")))
                    kept -= lines
                    dropped += lines
                    f.unlink()
                    cap_removed.append(f.name)
                    files_removed += 1

    if dropped and not p.is_symlink():
        # Constancia de la mutación autorizada (C3/R1): la poda re-ancla la
        # cadena y lo documenta. Se escribe SIEMPRE que hubo drops — también
        # cuando esta misma run rotó el vivo (p ya no existe tras el rename:
        # log_decision lo crea) o cuando los drops fueron solo en rotados.
        rotated_live = (rotated_name
                        if rotated_name and rotated_name not in cap_removed
                        else None)  # R3: no nombrar segmentos destruidos
        log_decision(p, actor="retention", action="retention_prune",
                     channel="system", result="ok",
                     detail={"kept": kept, "dropped": dropped,
                             "files_removed": files_removed,
                             "rotated": rotated_live,
                             "cap_removed": cap_removed})

    return {"kept": kept, "dropped": dropped, "rotated": rotated_name,
            "files_removed": files_removed,
            "skipped_symlinks": sorted(skipped)}


def prune_outbox(path: str | Path, *,
                 max_age_days: float = DEFAULT_OUTBOX_DAYS,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 now: float | None = None) -> dict[str, Any]:
    """Poda el outbox de transporte y su estado de cooldown.

    Además de la edad, la cola queda **acotada por tamaño**: bajo
    inundación se descarta lo más viejo primero (`overflow_dropped`) — el
    outbox es una cola, no un archivo histórico; su límite natural es el
    tamaño, no la rotación.
    """
    ts_now = time.time() if now is None else now
    if max_age_days < 0:
        raise ValueError("max_age_days debe ser >= 0")
    cutoff = _cutoff(ts_now, max_age_days)
    p = Path(path)
    # Un symlink apunta fuera del alcance gestionado: no se lee ni se
    # reescribe; se reporta.
    skipped: set[str] = set()
    if p.is_symlink():
        skipped.add(p.name)
        kept, dropped = 0, 0
    else:
        kept, dropped = (0, 0) if not p.exists() else _prune_jsonl(
            p, cutoff, _outbox_ts)

    overflow_dropped = 0
    if not p.is_symlink() and p.exists() and p.stat().st_size > max_bytes:
        with file_lock(p):
            text = p.read_text(encoding="utf-8")
            lines = split_record_lines(text)
            # A4: nunca vaciar la cola — si una sola línea excede el tope se
            # conserva (perder lo más nuevo es peor que desbordar).
            while (len(lines) > 1
                   and len("".join(x + "\n" for x in lines)) > max_bytes):
                lines.pop(0)  # la cola se appendea: lo primero es lo más viejo
                overflow_dropped += 1
            _write_lines_atomic(p, lines)

    cooldown_dropped = 0
    cpath = _cooldown_path(p)
    if cpath is not None and cpath.is_symlink():
        skipped.add(cpath.name)
    else:
        cooled = _load_cooldown(cpath)
        fresh = {k: v for k, v in cooled.items() if v >= cutoff}
        cooldown_dropped = len(cooled) - len(fresh)
        if cooldown_dropped:
            _save_cooldown(cpath, fresh)

    return {"kept": kept, "dropped": dropped,
            "cooldown_dropped": cooldown_dropped,
            "overflow_dropped": overflow_dropped,
            "skipped_symlinks": sorted(skipped)}


def prune_db(db_path: str | Path, *,
             max_age_days: float = DEFAULT_DB_DAYS,
             now: float | None = None) -> dict[str, Any]:
    """Poda sweeps viejos e observaciones inactivas viejas del watch.

    Una observación `active` jamás se borra: la baseline define la
    taxonomía NUEVO/RECURRENTE y borrarla re-alaría problemas vivos.
    """
    ts_now = time.time() if now is None else now
    if max_age_days < 0:
        raise ValueError("max_age_days debe ser >= 0")
    cutoff = _cutoff(ts_now, max_age_days)
    p = Path(db_path)
    if p.is_symlink():
        # sqlite3.connect seguiría el symlink y haría DELETE/VACUUM sobre la
        # base objetivo: se excluye sin abrir y se reporta.
        return {"sweeps_dropped": 0, "observations_dropped": 0,
                "skipped_symlinks": [p.name]}
    if not p.exists():
        return {"sweeps_dropped": 0, "observations_dropped": 0,
                "skipped_symlinks": []}
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
    return {"sweeps_dropped": sweeps, "observations_dropped": obs,
            "skipped_symlinks": []}


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
    parser.add_argument("--outbox-max-bytes", type=int,
                        default=DEFAULT_MAX_BYTES,
                        help="tamaño máximo del outbox (cola acotada)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_ROTATED,
                        help="archivos rotados conservados")
    parser.add_argument("--now", type=float, default=None,
                        help="epoch de referencia (tests o cron determinista)")
    args = parser.parse_args(argv)
    for flag, val in (("--days", args.days), ("--outbox-days", args.outbox_days),
                      ("--db-days", args.db_days), ("--max-bytes", args.max_bytes),
                      ("--outbox-max-bytes", args.outbox_max_bytes),
                      ("--keep", args.keep)):
        if val < 0:
            parser.error(f"{flag} no puede ser negativo")
    if args.keep < 1:
        parser.error("--keep debe ser >= 1 (el recién rotado siempre "
                     "sobrevive a su propia run)")
    # S4: cada artefacto se procesa aislado — uno corrupto no saltea los
    # demás ni se come el reporte (la evidencia de mantenimiento es ley).
    def _run(label: str, fn) -> dict[str, Any]:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — el reporte manda
            return {"error": f"{type(exc).__name__}: {exc}"}

    report = {
        "audit": _run("audit", lambda: prune_audit(
            args.audit, max_age_days=args.days,
            max_bytes=args.max_bytes, keep_rotated=args.keep,
            now=args.now)),
        "outbox": _run("outbox", lambda: prune_outbox(
            args.outbox, max_age_days=args.outbox_days,
            max_bytes=args.outbox_max_bytes, now=args.now)),
        "db": _run("db", lambda: prune_db(
            args.db, max_age_days=args.db_days, now=args.now)),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any("error" in v for v in report.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
