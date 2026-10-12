# NOC Agent — Runbook operativo (unificado)

> Unifica diario cliente [11] (instalación + errores, `ses_fca675a56ffeKG6RYSfTZWvrrZ`)
> y [13] (HUB MCP ZBX + Discord) en la canónica [31].
> Estado: lab. Solo lectura contra Zabbix (el CLI no escribe).

## 1. Prerrequisitos

- Lab `zbx-in-docker` levantado (data engine: Zabbix 7.4.13, postgres 15).
- Python >= 3.10.
- Acceso a la API JSON-RPC del lab (`ZABBIX_URL`).
- Credenciales por entorno, nunca en archivos (ver `agent/config.py`):
  `ZABBIX_URL`, `ZABBIX_TOKEN` (o `ZABBIX_USER` / `ZABBIX_PASSWORD` para `user.login` local), `ZABBIX_TIMEOUT`.

## 2. Instalación (agente)

```bash
cd /home/asg/projects/lab/noc-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
python3 -m pytest -q   # router + catalogo curado, sin red (FakeClient)
```

Errores vistos en [11] y cómo resolverlos:

| Síntoma | Causa probable | Fix |
|---|---|---|
| `ModuleNotFoundError: agent` | correr fuera del root o sin install | correr desde el root o `pip install -e .` |
| `Zabbix API error / login error` | URL o token/user mal | verificar `ZABBIX_URL` y token vigente o user/pass lab |
| `Connection refused / timeout` | lab caído o URL a puerto equivocado | levantar `zbx-in-docker`, probar API con curl |
| `Sin problemas activos` persistente | filtro `recent:true` sin eventos recientes | normal en lab idle, verificar con `estado` (hosts + versión) |
| venv contamina repo | `.venv/` dentro del repo | está gitignored, no commitear |

## 3. Operación diaria (CLI read-only)

```bash
source .venv/bin/activate
python3 -m agent.cli estado              # L0: versión + hosts + problemas
python3 -m agent.cli problemas --limit 20
python3 -m agent.cli ack                 # guía, no escribe en Zabbix
```

Niveles (ver `agent/router.py`):

- L0 exacto (`estado`, `ack`): 0 tokens.
- L1 keywords (problema/alerta/estado/version/hosts/salud): mismo handler, sin LLM.
- L2 resto: agente local `l2agent` (loop + catálogo curado; sin `LLM_MODEL` avisa en vez de romper).

## 4. HUB MCP ZBX (thread [13])

Decisión Fase 2 (2026-09-26, ratificada): initMAX `zabbix-mcp-server` v1.36.1
(Python/FastMCP, AGPL-3.0, filtrado de tools por token, tokens read-only sin
writes ni `raw_api_call`). Catálogo curado 15–25 tools por token, nunca completo.

Estado actual:

- `mcp/` holds the client-side curated catalog (`mcp/curated-tools.json`,
  20 read-only tools split by role) plus the loader/validator
  (`mcp/catalog.py`, no network). The hub itself still lives in `zbx-in-docker`
  (`docker/zabbix-mcp-config.toml`, build local, loopback `:8080`, `read_only`, ~35 tools).
- El agente aquí es consumidor/orquestador, no duplica compose ni templates.

Pendiente operativo:

- [x] Agregar `mcp/` client config curada (~15–25 tools, nunca catálogo completo) — desbloquea L2 real.
- [ ] Doc de operación del hub + rotación de tokens (procedimiento 2026-10-11 en `odd/tasks/l2-local-agent.md` §Cierre: token vía UI, toml, restart, borrar viejo).
- [ ] Clasificación `error_auth` en `l2agent`: distinguir credencial vencida de error transitorio + alarma (hoy todo error va a `result="error"` sin clasificar).
- [x] Telemetría de piloto free: `usage_total` en `ChatModel` + `usage` en `respuesta_final` del audit (50 passed).
- [ ] Mover hub a VM dedicada fuera del compose (decisión de arquitectura).
- [ ] Revisar permisos y secretos según auditoría (toml con token, `.env` group-writable, token Telegram en historial) — rotar y corregir permisos, sin pegar valores acá.

## 5. Adapters: mail, Discord, Telegram y agentes directos (thread [13])

- Decisión de producto: adapters intercambiables sobre el mismo orquestador y
  vocabulario (`reply`, `menu`, `form`, `ephemeral`); cada instancia elige el suyo.
  Instancia cliente (2026-10): mail-first (hilos por incidente); Discord/Telegram
  fuera del plan inmediato. El adapter vive en `agent/` (Fase 4), hoy no existe.
- Vocabulario abstracto del orquestador (`reply`, `menu`, `form`, `ephemeral`) que cada canal chat traduce a nativos.
- Telegram queda para después, reutilizando el mismo vocabulario y el mismo orquestador que Discord.
- Agentes directos: técnicos de la coope con OpenCode / Claude Code / Codex van directo al hub MCP en `zbx-in-docker` (`127.0.0.1:8080` en lab, VM dedicada en prod), con bearer propio y rol `operator` / `technician` de `mcp/curated-tools.json`. No pasan por Discord ni crean hilos.

## 6. Gaps abiertos (para [31])

1. `mcp/` client config + L2 real hechos (loop `l2agent` verificado en lab 2026-10-11; server initMAX 1.36.1, decisión Fase 2 del 2026-09-26).
2. Adapter Discord ausente (Fase 4).
3. Runbook de upgrade `instalacion.md` (en `zbx-in-docker/docs/`) parcial: 3 pasos sin backup/restore/verificación.
4. Sin troubleshooting general, sin backups automáticos/offsite, sin rotación de secretos (los 3 faltantes de la auditoría).

## 7. Referencias

- Canónico: `docs/arquitectura.md` (§3–§4 hub + canales).
- Auditoría: `docs/auditoria-2026-09-10.md`.
- Diseño lab / upgrade parcial: `zbx-in-docker/docs/instalacion.md`.
- Diario: cliente [31] canónica (sup [11] + [13]).

## 8. Mapa de triggers (qué despierta al agente)

Estado 2026-10-11: solo CLI/`main.py` existen (terminal). Hilos, botones y
adapters son arquitectura (Fase 4), no implementación. Esta tabla es el
contrato a implementar; es lo que el técnico VE (la capa que vende).

| # | Lo dispara | Llega por | Atiende | Estado |
|---|---|---|---|---|
| 1 | Zabbix dispara alerta | webhook → adapter → hilo del incidente con botones | L0 | futuro (adapter Fase 4) |
| 2 | Guardia clickea Ack/Detalle | botón del hilo | L0/L1 | futuro (adapter Fase 4) |
| 3 | Guardia pregunta en el hilo | reply en el hilo (el historial es el contexto) | L2 | futuro (adapter Fase 4) |
| 4 | Técnico profundiza solo | su agente → directo al hub | nadie (self-service) | hoy (token + rol propios + `docs/kit-tecnico.md`) |
| 5 | Técnico pide criterio | mensaje al noc-agent vía adapter | L2 | futuro (adapter Fase 4) |
| 6 | Watch programado | cron → `main.py` con goal fijo | L2 | futuro (memoria pendiente) |
| 7 | Agente externo pide criterio | `pedir_criterio` como tool (agent-as-tool) | L2 | futuro (decisiones: quién paga tokens, contrato de escalamiento) |

Reglas:

- La ambigüedad en el agente PROPIO del técnico NO despierta al noc-agent:
  su agente es otro consumidor del hub; su loop (o su fallo) es suyo.
  Derivar criterio al noc-agent sería un handoff diseñado, no automático.
- Cada fila necesita antes de cliente: transporte, auth y contrato de formato.
- cliente es mail-first: hilo = thread de mail; botones = los que el mail
  permita (links/keywords), no componentes Discord.

## 9. Watch proactivo: notas de diseño (futuro, fila 6 del mapa)

Idea (2026-10-11): cron barre, guarda en DB, compara, notifica solo novedad.

- **Baseline en DB, no archivos**: tablas `sweeps` + `observations`
  (eventid, host, severidad, ts). La historia se CONSULTA (SQL), no se
  grepea. El JSONL sigue como evidencia append-only; la DB es el índice
  consultable (misma dualidad que auditoría §7 de arquitectura).
- **Taxonomía antes de notificar**: NUEVO (eventid no visto en X días) →
  alarma; RECURRENTE (ya visto) → aviso con link al anterior, sin repetir
  alarma; HISTÓRICO (contexto para correlación, no notifica); RECUPERADO
  (se normalizó) → digest.
- **Barato primero**: gate L0 (diff contra DB, 0 tokens) → LLM solo si
  cambió algo. 95% de barridos gratis.
- **Heartbeat**: el watch emite "sigo vivo"; su silencio es incidente del
  vigilante (dead-man switch).

## 9b. Lógica de aviso: qué suena y qué no (implementado, `l2agent/notify.py`)

Principio: "cambió una métrica → suena" fabrica sordera. El barrido ni
siquiera mira valores, solo membresía de la lista de problemas; después,
tres compuertas en orden:

1. **Taxonomía**: solo NUEVO puede alarmar; RECUPERADO va a digest
   (resumen, no interrupción); RECURRENTE es silencio deliberado.
2. **Severidad**: umbral configurable (default High). Lo menor va a digest.
   Severidad ilegible no alarma pero queda en digest marcada (no se pierde).
3. **Cooldown 24h**: el mismo evento no re-alarma aunque re-nazca (flapping
   alta → recuperado → alta). La repetición queda en digest como "cooldown".

Destino: outbox JSONL con asunto y cuerpo listos para mail (hilos del
futuro adapter); cliente es mail-first. Cero tokens: plantillas, no LLM.
CLI: `python -m l2agent.watch --db watch.db --notify [--min-severity High]`.
Timer instalado 2026-10-12: `noc-agent-watch.timer` (systemd user, cada 15
min, Persistent=true) → `noc-agent-watch.service` con DB/outbox en
`~/.local/share/noc-agent-watch/`, env de `.env` del repo. Primer disparo
verificado SUCCESS. Pendiente: redactado LLM solo sobre novedad
confirmada + transporte mail (adapter Fase 4).
