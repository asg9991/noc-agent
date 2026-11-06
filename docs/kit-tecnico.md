# Kit del técnico: cómo hablar con el hub MCP

> Para técnicos con agente propio (OpenCode, Claude Code, Codex).
> El hub es un mostrador, no una persona: te da DATOS de Zabbix.
> El criterio (correlación, "¿pega con…?") se le pide al noc-agent (ver §5).

## 1. Conexión (te la da tu admin)

- **Endpoint**: el de tu instancia (lab: `http://127.0.0.1:8080/mcp`).
- **Auth**: bearer propio por header `Authorization: Bearer <tu-token>`.
  Sin bearer → `401`. Tu token expone solo tu rol, nada más.
- **Protocolo**: MCP streamable HTTP. Handshake primero (`initialize`,
  guarda el `Mcp-Session-Id`), después `tools/list` y `tools/call`.
- Regla 0: el token vive en tu config local con permiso 600.
  Nunca en chats, mails ni repos.

## 2. Tu menú (curado, no completo)

Nunca ves las ~237 tools: solo tu subconjunto (~15–25). Lista viva con
`tools/list`; referencia en `mcp/curated-tools.json` de noc-agent.
Las 5 de todos los días (rol operator, args FLAT siempre):

- `problem_active_get` — problemas activos (punto de partida de todo).
- `event_get` — detalle detrás de un problema (clock, severidad).
- `trigger_get` — distinguir "disparando" de "mal configurado".
- `host_get` / `host_status_get` — inventario y salud por host.
- `history_get` / `trend_get` — valores recientes o agregados ("¿desde cuándo?").

Rol technician suma diagnóstico y reportes (`graph_get`, `map_get`,
`maintenance_get`, `anomaly_detect`, `capacity_forecast`, `report_generate`).

## 3. Cómo pedir (cortesía = servicio)

1. **Una pregunta, una tool.** No encadenes a ciegas: mirá cada respuesta
   antes del siguiente paso (igual que el loop del noc-agent).
2. **Filtros y límites siempre.** Pedí por host/grupo/ventana, nunca "todo".
   Cada dato de más son tokens tuyos y carga del hub.
3. **Args FLAT.** `{"hostid": "1"}`, sin envoltorio `params` (el hub lo ignora).
4. **Leé los errores.** `isError` o `401/406` te dicen qué corregir:
   sin bearer, sin header `Accept`, o tool fuera de tu rol.
5. **No spamees `tools/list`.** Una vez por sesión alcanza; el menú no cambia.

## 4. Lo que NO existe (aunque lo pidas lindo)

- **Writes**: `*_create/update/delete`, `*_acknowledge`, `raw_api_call`,
  `user_*`, `script_*`. El gate frena ANTES de la red y la denegación
  queda auditada + nos avisa. No es un error a reintentar: es un límite.
- **El catálogo completo**: pedirlo gasta ~100k tokens por turno. Por eso
  existe la curaduría. Si te falta una tool read-only para tu laburo,
  pedila a tu admin (se agrega al curado con justificación, no a pedido).

## 5. Cuándo escalar al noc-agent (contrato de escalamiento)

Esta sección ES el contrato: vive acá, en el skill, no en código. Si tu
agente duda, aplica esta regla en orden:

1. **Datos primero, criterio después.** Agotá tus tools (máximo 2 vueltas):
   si con datos reales respondés, no escales. Escalar lo respondible es
   gastar tokens ajenos.
2. **Escalá si pasa ALGUNA:** necesitás correlacionar 2+ incidentes; la
   respuesta depende de historia ("¿pega con lo de ayer?"); necesitás un
   runbook o memoria del NOC; tu segunda vuelta devolvió lo mismo que la
   primera (estancado); hay que ACTUAR (ack, mantenimiento) y no solo mirar.
3. **Cómo escalar:** hoy, derivá a tu humano con resumen + lo intentado
   ("tengo X, probé Y, necesito criterio"). Instancia mail-first: reply en el
   hilo del incidente (adapter Fase 4). Futuro: `pedir_criterio` como tool.

Lo que NO se escala: dato crudo disponible, tool denegada (es un límite,
no una duda), error de red (reintentá, no escales).

## 6. Validación en 10 minutos (practicidad al instante)

Contra el lab, con tu token y rol, tienen que salir estas 3 sin ayuda:

1. `problem_active_get` → lista de problemas con severidad.
2. `history_get` de un host con problema → valores recientes.
3. Una denegada a propósito (`host_create`) → gate local, sin red.

Si las 3 salen, tu pata anda. Si alguna falla, el problema es conexión,
token o rol — nunca el modelo. Avisá a tu admin con el mensaje exacto.
