# NOC Agent — Runbook operativo (unificado)

> Unifica diario CESPAL [11] (instalación + errores, `ses_fca675a56ffeKG6RYSfTZWvrrZ`)
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
python3 -m pytest -q   # 4 tests router, sin red (FakeClient)
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
- L2 resto: stub `"no implementado, usar MCP"` — esperado hasta Fase 3/4.

## 4. HUB MCP ZBX (thread [13])

Estado actual (auditoría 2026-09-10):

- `mcp/` en este repo está vacío (solo `.gitkeep`): el hub vive en `zbx-in-docker`
  (`docker/zabbix-mcp-config.toml`, build local, loopback `:8080`, `read_only`, ~35 tools).
- El agente aquí es consumidor/orquestador, no duplica compose ni templates.

Pendiente operativo:

- [ ] Elegir server MCP Zabbix de Fase 2 y agregar `mcp/` client config curada (~15–25 tools, nunca catálogo completo).
- [ ] Doc de operación del hub + rotación de tokens (hoy solo hallazgo de auditoría, sin procedimiento).
- [ ] Mover hub a VM dedicada fuera del compose (decisión de arquitectura).
- [ ] Revisar permisos y secretos según auditoría (toml con token, `.env` group-writable, token Telegram en historial) — rotar y corregir permisos, sin pegar valores acá.

## 5. Discord (thread [13])

- Decisión: Discord-first (arquitectura §3). Adapter vive en `agent/` (Fase 4), hoy no existe.
- Vocabulario abstracto del orquestador (`reply`, `menu`, `form`, `ephemeral`) que cada canal traduce a nativos.
- Telegram queda para después, reutilizando el mismo vocabulario.

## 6. Gaps abiertos (para [31])

1. `mcp/` client config ausente (bloquea L2 real; en lab se usa initMAX 1.36.1 como spike, selección formal pendiente Fase 2).
2. Adapter Discord ausente (Fase 4).
3. Runbook de upgrade `instalacion.md` (en `zbx-in-docker/docs/`) parcial: 3 pasos sin backup/restore/verificación.
4. Sin troubleshooting general, sin backups automáticos/offsite, sin rotación de secretos (los 3 faltantes de la auditoría).

## 7. Referencias

- Canónico: `docs/arquitectura.md` (§3–§4 hub + canales).
- Auditoría: `docs/auditoria-2026-09-10.md`.
- Diseño lab / upgrade parcial: `zbx-in-docker/docs/instalacion.md`.
- Diario: CESPAL [31] canónica (sup [11] + [13]).
