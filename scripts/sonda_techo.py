"""Sonda de techo L2: N corridas reales midiendo latencia/usage/errores.

Lab-only. Todo por env (nunca secrets en argv): MCP_URL, MCP_BEARER,
LLM_BASE_URL, LLM_MODEL, LLM_API_KEY. Uso:
    set -a; source .env; set +a
    python scripts/sonda_techo.py [N=10]
Cada corrida usa modelo fresco (usage por corrida) y goals rotados
(ráfaga realista de incidente, no la misma pregunta xN).
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path
import time

# La sonda se corre como `python scripts/sonda_techo.py` desde la raíz del
# repo: scripts/ en sys.path[0] esconde la raíz, así que se re-agrega.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from l2agent.loop import run_loop
from l2agent.main import build_client_from_env, build_model_from_env

GOALS = [
    "¿hay problemas activos en Zabbix? Resumí por severidad.",
    "¿qué hosts tienen problemas de alta severidad ahora?",
    "¿hay algo sin reconocer (acknowledged=0) que mire urgente?",
]


def main(argv: list[str] | None = None) -> int:
    n = int((argv or [None])[0] or 10) if argv else 10
    client = build_client_from_env()
    lat, tin, tout, fails, json_fails, cortes = [], [], [], 0, 0, 0
    for i in range(n):
        model = build_model_from_env("operator")  # fresco: usage por corrida
        goal = GOALS[i % len(GOALS)]
        t0 = time.monotonic()
        try:
            answer = run_loop(goal, model=model, client=client,
                              audit_path="/tmp/sonda.jsonl",
                              max_iters=5)
            # El loop nunca revienta: los "corté" (tope, repetición,
            # modelo caído) son retornos normales. Para la sonda son
            # fallos igual: el objetivo no se cumplió.
            ok = not answer.startswith("corté")
            if not ok:
                cortes += 1
                print(f"[{i+1}/{n}] CORTE: {answer[:120]}")
        except ValueError as exc:  # parse_step: el modelo no dio JSON válido
            ok = False
            json_fails += 1
            print(f"[{i+1}/{n}] FALLO_JSON: {str(exc)[:120]}")
        except Exception as exc:  # noqa: BLE001 - la sonda registra, no esconde
            ok = False
            print(f"[{i+1}/{n}] FALLO: {type(exc).__name__}: {str(exc)[:120]}")
        dt = time.monotonic() - t0
        lat.append(dt)
        tin.append(model.usage_total["prompt_tokens"])
        tout.append(model.usage_total["completion_tokens"])
        fails += 0 if ok else 1
        print(f"[{i+1}/{n}] {dt:5.1f}s in={tin[-1]:5d} out={tout[-1]:4d} "
              f"{'ok' if ok else 'FALLO'}")
    print(f"\n--- {n} corridas ---")
    print(f"latencia  p50={statistics.median(lat):.1f}s "
          f"p95={sorted(lat)[max(0, int(n*0.95)-1)]:.1f}s max={max(lat):.1f}s")
    print(f"tokens    in_total={sum(tin)} out_total={sum(tout)} "
          f"in/corrida={sum(tin)//max(n,1)}")
    print(f"fallos    {fails}/{n} (json: {json_fails}, cortes: {cortes})")
    print("techo: si p95 > 60s o fallos por 429 > 0, el gratis limita el servicio.")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
