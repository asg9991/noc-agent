# Feature: l2-local-agent (L2 en contenedor Docker)

Objetivo: agente local L2 que cubra el stub de `router.handle_l2`, viviendo en un
contenedor Docker. Ejecuta la decisión ya aprobada en `docs/arquitectura.md` §9
(instancia cliente: L2 con LLM/agente local + mail).
Problema: `handle_l2` devuelve "no implementado, usar MCP"; no hay loop agente,
ni guardrails, ni auditoría de decisiones.
Alcance autorizado: lab local, read-only primero (writes futuros con confirmación
explícita según arquitectura §7). Sin secretos en repo ni en imagen (env por fuera).
Reutilizar `agent/mcp_client.py` (allowlist) y `mcp/curated-tools.json`; no copiar
nada de zbx-in-docker.
TDD: modo estándar (pytest presente, sin strict_tdd en sesión). Runner: `source .venv/bin/activate && python -m pytest -q`.
Route: inline (delegación no disponible en este runtime) + piezas chicas ya entendidas.

## Checklist

- [x] T1 `l2agent/audit.py` + `tests/test_audit.py` (log JSONL de decisiones: quién/qué/cuándo/resultado) — checks: `pytest -q` (RED→GREEN en vivo)
- [x] T2 `l2agent/tools.py` (manos: superficie angosta sobre `mcp_client`, allowlist, límite de resultados) — checks: `pytest -q` (26 passed: 6 nuevos, RED→GREEN en vivo)
- [x] T3 `l2agent/guardrails.py` (reglas: acciones prohibidas, confirmación para writes) — checks: `pytest -q` (35 passed: 9 nuevos, RED→GREEN en vivo)
- [x] T4 `l2agent/loop.py` (workflow: observa→piensa→actúa→verifica, tope de iteraciones, anti-alucinación: solo datos de tools) — checks: `pytest -q` con modelo fake (41 passed: 6 nuevos, RED→GREEN en vivo)
- [x] T5 `l2agent/main.py` + `l2agent/Dockerfile` (entrypoint + imagen slim, non-root, env por fuera) — checks: `docker build` + run sin secretos (uid=10001, --help, --list-tools, env limpio) + `pytest` 46 passed
- [x] T6 cablear `router.handle_l2` → l2agent (reemplazar stub) — checks: `pytest -q` + `route()` devuelve L2 real (47 passed; stub pineado por 2 tests viejos → actualizados al nuevo contrato)

## Cierre: primer loop real (2026-10-11)

- Groq free (`qwen/qwen3.8-27b`) + hub lab + simuladores: `¿hay problemas
  activos?` → 8 problemas reales resumidos por severidad, en español.
- Hallazgos del estreno: (1) Groq exige `max_tokens` (OTPM 1000) →
  `ChatModel(max_tokens=512)` + test; (2) faltaba `initialize()` de sesión
  MCP → handshake perezoso en `run_loop` + test; (3) token hub `lab_l2`
  creado (hash `sha256:` + restart); (4) anti-alucinación verificada en vivo:
  con el 400 el modelo dijo "no pude" sin inventar.
- `pytest`: 48 passed. Rotación token hub CERRADA v2 2026-10-11 (token `lab_hub`
  fresco desde UI → toml → restart → 8 problemas live + `lastaccess` EN_USO;
  token viejo borrado). Lección del incidente intermedio: verificar
  `lastaccess>0`, no solo un llamado suelto.
- Pendiente nuevo: clasificación `error_auth` en l2agent (distinguir credencial
  vencida de error transitorio + alarma; hoy todo error va a `result="error"`
  sin clasificar).

## Criterios de aceptación

- `pytest -q` verde (existentes + nuevos).
- El loop con modelo fake responde solo con datos devueltos por tools (si no hay dato, lo dice).
- `call` a tool fuera de allowlist nunca sale a red (`PermissionError` local).
- La imagen buildea, corre como non-root y no contiene secretos.
- `route("...")` ambiguo llega a L2 real en vez del stub.

## Progreso

- Doc creado. Branch: `feature/l2-local-agent` (creado desde main en sincro con origin).
- T1 siguiente: leer estilo de `tests/test_router.py`, escribir test RED, implementar GREEN.

## Siguiente paso

- Ejecutar T1 en vivo con explicación parte por parte.
