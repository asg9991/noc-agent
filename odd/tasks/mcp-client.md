# Feature: mcp-client flaco (L2 directo al hub)

Objetivo: cliente MCP read-only para que L2 consulte Zabbix vía hub sin pasar por Discord.
Problema: `mcp/catalog.py` solo valida nombres en local; no hay transporte con red.
Alcance autorizado: lab local `127.0.0.1:8080`, bearer fuera del repo (`/tmp/.mcp_bearer`, 600). Sin secretos en archivos. Sin Discord en este slice.
TDD: modo estándar (pytest presente, sin strict_tdd en sesión). Runner: `source .venv/bin/activate && python -m pytest -q`.
Route: delegated direct no disponible en runtime (free tier) → inline con evidencia.

## Checklist

- [x] T1 cliente flaco `agent/mcp_client.py` (init + list + call, gate allowlist, params vs flat, SSE parse, sin log de bearer) — route: inline (delegación no disponible)
- [x] T2 tests sin red `tests/test_mcp_client.py` (gate bloquea writes, payload params/flat, parse SSE) — checks: `pytest -q`
- [x] T3 demo viva loopback (health + initialize + tools/list + problem_active_get, bearer por env, nada se commitea con secretos) — checks: observado en terminal

## Criterios de aceptación

- `pytest -q` verde (existentes + nuevos).
- `call_tool("host_create", ...)` nunca sale a red: levanta `PermissionError` por allowlist.
- Demo viva muestra conteo de tools del hub y 1 lectura real sin exponer bearer.

## Progreso

- Branch: `feature/mcp-client` (base `main@77ae94d`).
- Work-unit 1: T1+T2+T3 hechos. `pytest 18 passed`. Viva: hub 35 tools, `problem_active_get` real (eventid 11281, router-sim-0), gate frena `host_create` en local.
- Commits: pendiente work-unit 1.

## Siguiente paso

- Implementar T1+T2 y correr pytest.
