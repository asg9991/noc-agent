# Feature: l2-local-agent (L2 en contenedor Docker)

Objetivo: agente local L2 que cubra el stub de `router.handle_l2`, viviendo en un
contenedor Docker. Ejecuta la decisión ya aprobada en `docs/arquitectura.md` §9
(instancia de referencia: L2 con LLM/agente local + mail).
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
- [x] T7 clasificación `error_auth` (diario #51): `l2agent/errors.py` (`classify`/`result_for`: 401/403→auth, 429/5xx/timeout→transient, resto unknown) + prefijo en `tools.run` + `result` en loop + alarma en observación y retorno — checks: `pytest -q` 58 passed (8 nuevos en `tests/test_errors.py`, RED→GREEN en vivo)
- [x] T8 handshake `initialize()` clasificado (follow-up de T7): mismo `classify`/`result_for`, acción `hub_handshake` en audit, alarma si es credencial — checks: `pytest -q` 60 passed (2 nuevos, RED→GREEN en vivo). Lección: `mcp_client.initialize` hace `raise_for_status` crudo (401 si el bearer muere) y el loop ni lo miraba.
- [x] T9 adapter `tool_calls` nativo (diario #54): `model.py` manda `tools`+`tool_choice` solo en familia gpt-oss (auto-detect + override), traduce tool_calls a paso y texto a answer; qwen intacto; max 2048 en nativas — checks: `pytest -q` 64 passed (4 nuevos, RED→GREEN) + benchmark 120b **6/8** (resuelve investigar-host 0/4 en qwen; 2 fallos = 429 pacing, no calidad).
- [x] T10 slice watch state/histéresis/heartbeat (diario #53): `l2agent/watch.py` determinista 0 tokens (baseline SQLite sweeps+observations, taxonomía nuevo/recurrente/recuperado con histéresis de 2 ausencias, heartbeat + CLI para cron) — checks: `pytest -q` 70 passed (6 nuevos, RED→GREEN) + 2 barridos live contra lab (0 activos: wiring+heartbeat verificados, taxonomía cubierta por tests). Lección repetida: el hub exige `initialize()` antes de tools/call (el primer live falló 400 por saltearlo).
- [x] T11 lógica de aviso (diario #55, compuertas): `l2agent/notify.py` (taxonomía→solo NUEVO alarma, severidad default High, cooldown 24h, outbox mail-ready, 0 tokens) + `--notify` en CLI + §9b en runbook — checks: `pytest -q` 76 passed (6 nuevos, RED→GREEN). Timer systemd pendiente.

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
- Recovery commit `b102216` (2026-10-12): T1-T6 + sonda, `pytest -q` 50 passed.
- T1–T11 completos (2026-10-12): `pytest -q` 76 passed; watch + notify +
  timer 15 min instalado y verificado. Branch lista para merge a `main`.

## Siguiente paso

- Trabajar el backlog de patas flojas (`odd/tasks/backlog-patas-flojas.md`);
  el punto más urgente es P1: `watch.sweep` no parsea el envelope real del
  hub (el timer corre hoy sobre lógica que ve 0 problemas).
- Decisión de proveedor/infraestructura de inferencia (cloud vs proyecto de
  IA local) pendiente con el cliente.

## Evidencia #50: sonda de techo + kit §6 (2026-10-12, corregido)

- Kit §6 3/3 verde contra lab: handshake con sesión, `problem_active_get`
  (3 activos), `history_get` (raw Zabbix), `host_create` denegada local.
- Exp 1 (ráfaga N=10): 2 ok, 8 cortes por Groq 429. El gratis NO aguanta
  ráfaga (throttle tras ~3 llamadas seguidas).
- Exp 2 (5 corridas espaciadas 60s): 5/5 ok, 1.2–2.1s por corrida,
  ~1.1–2.4k tokens in + ~0.2–0.4k out por corrida. La cadencia cura el
  429 → el techo es por-minuto (RPM 30 o TPM 8K), NO diario.
- Límites free qwen/qwen3-32b (docs Groq 2026-10-09): 30 RPM, 8K TPM,
  1K RPD, 200K TPD.
- Matemática diaria (corrida ≈ 2k tokens, 2–3 req):
  - watch 5 min (288/día): ~580K tok vs 200K TPD ❌, ~600 req vs 1K ⚠️
  - watch 10 min (144/día): ~290K vs 200K ⚠️ marginal
  - watch 15 min (96/día): ~190K vs 200K ✓ justo
- Síntesis para cliente en `docs/comparativa-modelos.md` (carga medida,
  límites, precios, escenarios S1–S3, recomendación por etapas). Bitácora
  de opciones considerada acá:
  a) gratis + cadencia ≥15 min + backoff (cero costo, margen fino);
  b) Groq paid (~10x límites, ~u$d 2/mes a este volumen);
  c) modelo chico (llama-3.1-8b: 500K TPD — verificar vigencia en
     console.groq.com/settings/limits, reportes contradictorios);
  d) LLM local en VM (SIN DATOS: un 27B Q8 pide ~30GB VRAM; en CPU de
     T14 serían ~2–5 tok/s; falta benchmark de latencia y calidad).
- Bugs de la sonda (la primera corrida mintió 10/10 ok): la sonda ignoraba
  el return del loop (los "corté" contaban como éxito) y necesitaba
  `PYTHONPATH=.`. Fix: cuenta `cortes`, bootstrap de `sys.path`.
