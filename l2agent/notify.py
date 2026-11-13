"""Avisos del watch: qué interrumpe a un humano y qué espera.

Tres compuertas, en orden, porque "cambió una métrica → suena" fabrica
sordera (fatiga de alertas: cuando todo es urgente, nada lo es):

1. Taxonomía: solo NUEVO puede alarmar; RECUPERADO va a digest;
   RECURRENTE es silencio (ya se avisó).
2. Severidad: umbral configurable (default High). Lo menor va a digest.
   Severidad ilegible no alarma: va a digest marcado (no se pierde,
   no interrumpe).
3. Cooldown: el mismo evento no re-alarma dentro de la ventana aunque
   re-nazca (flapping alta → recuperado → alta). La repetición queda en
   digest como "cooldown", no como segunda alarma.

El barrido nunca mira valores de métricas, solo membresía de la lista de
problemas: una métrica que fluctúa sin abrir evento no suena jamás.
Destino: outbox JSONL (hilos futuros del adapter lo leen); el cuerpo ya
trae asunto y texto listos para mail. Cero tokens: plantillas, no LLM
(el LLM redacta solo si algún día se quiere, sobre novedad confirmada).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_MIN_SEVERITY = "High"
DEFAULT_COOLDOWN_S = 24 * 3600  # un evento no re-alarma en 24h

_SEVERITY_NAMES = {
    "not classified": 0,
    "info": 1,
    "information": 1,
    "warning": 2,
    "average": 3,
    "high": 4,
    "disaster": 5,
}


def rank(severity: Any) -> int | None:
    """Normaliza severidad Zabbix (número o nombre) a 0–5. None = ilegible."""
    s = str(severity).strip()
    if s.isdigit() and 0 <= int(s) <= 5:
        return int(s)
    return _SEVERITY_NAMES.get(s.lower())


def _cooldown_path(outbox_path: str | Path | None) -> Path | None:
    if outbox_path is None:
        return None
    p = Path(outbox_path)
    return p.parent / (p.name + ".cooldown.json")


def _load_cooldown(path: Path | None) -> dict[str, float]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _save_cooldown(path: Path | None, state: dict[str, float]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _alarm_record(p: dict[str, Any], ts: float) -> dict[str, Any]:
    sev, host, eid = p.get("severity", ""), p.get("host", ""), p["eventid"]
    return {
        "ts": ts,
        "kind": "alarma",
        "eventid": eid,
        "host": host,
        "severity": sev,
        "subject": f"[NOC alarma] {sev} en {host} ({eid})",
        "body": (f"Nuevo problema {eid} en {host} "
                 f"(severidad {sev}). Verificar en Zabbix; "
                 f"hilo del incidente: {eid}."),
    }


def decide(sweep_result: dict[str, Any],
           outbox_path: str | Path | None = None,
           min_severity: str = DEFAULT_MIN_SEVERITY,
           cooldown_s: float = DEFAULT_COOLDOWN_S,
           now: float | None = None) -> dict[str, Any]:
    """Aplica las compuertas a un resultado de sweep. Devuelve alarms+digest.

    El cooldown persiste entre corridas solo si hay `outbox_path` (sin buzón
    no hay dónde recordar); con `outbox_path=None` rige solo dentro de la
    llamada.
    """
    ts = time.time() if now is None else now
    threshold = rank(min_severity)
    if threshold is None:
        raise ValueError(f"umbral inválido: {min_severity!r}")
    alarms, digest = [], []
    cpath = _cooldown_path(outbox_path)
    cooled = _load_cooldown(cpath) if any(
        sweep_result.get(k) for k in ("new",)) else {}
    dirty = False
    for p in sweep_result.get("new", []):
        r = rank(p.get("severity", ""))
        if r is None:
            digest.append({"kind": "severidad-desconocida", **p})
            continue
        if r < threshold:
            digest.append({"kind": "bajo-umbral", **p})
            continue
        last = cooled.get(p["eventid"])
        if last is not None and ts - last < cooldown_s:
            digest.append({"kind": "cooldown", **p})
            continue
        alarms.append(_alarm_record(p, ts))
        cooled[p["eventid"]] = ts
        dirty = True
    for p in sweep_result.get("recovered", []):
        digest.append({"kind": "recuperado", **p})
    # RECURRENTE: silencio deliberado. Ni digest.
    if alarms and outbox_path is not None:
        out = Path(outbox_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            for a in alarms:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    if dirty:
        _save_cooldown(cpath, cooled)
    return {"alarms": alarms, "digest": digest}
