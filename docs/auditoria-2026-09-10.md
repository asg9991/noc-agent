# Auditoría NOC-Agent 2026-09-10 — hallazgos (solo lectura, sin secretos)

Fuente: verificación empírica en lab + prod (ssh no interactivo, solo lectura) + ambos repos.
Sin valores de secretos: solo existencia/patrones. Sin commits.

## Lab (verificado)

- Zabbix 7.4.13 (API), postgres 15, nginx:alpine, agent2/web pineados 7.4.13.
- Hub MCP initMAX 1.36.1 (build local, `healthy`, `:8080` solo loopback, read_only, 35 tools).
- Puertos: 80 y 10051 en 0.0.0.0; 8080 en 127.0.0.1; sin 3000 (grafana removido).
- Token API lab `mcp-spike-lab` expira 2026-09-15 (5 días al 09-10).
- `settings.url` vacío (sin Frontend URL pública) → reportes por link rotos.
- Housekeeping: history 31d, trends 365d. Datos reales 2026-08-23→09-10 (~18 días).
- Extensiones postgres: solo `plpgsql` (pgcrypto NO habilitado — afirmación previa refutada).
- Media Telegram habilitado (único activo); Discord y resto deshabilitados.
- `docker/zabbix-mcp-config.toml` permiso 644 y contiene token API vigente + hash de bearer (ALTA).
- `docker/.env` permiso 664 (media). `/tmp/.mcp_bearer` 600 (ok).
- Usuario `Admin` superadmin existe; rotación de password no verificable en modo lectura (pendiente manual).
- Sin cron de backups en host lab ni en prod (usuario zabbix sin crontab).
- Token Telegram en historial git (`da12351`, con patrón presente); working tree con placeholder (ok).
- Spike `docs/mcp-spike-fase2.md` sin commitear; compose y .gitignore con cambios locales sin commitear (no tocar).
- Tags flotantes: `nginx:alpine`, `postgres:15`, `lab-simulator:latest` (supply chain).

## Prod `zabbix-muni` (ssh no interactivo, solo lectura)

- Up 6 días. Contenedores: `muni/zabbix-server:7.4.13`, web 7.4.13, postgres 15, nginx:alpine. Sin grafana, sin MCP.
- Puertos: 80, 10051, 14022. Nginx sin TLS.
- Sin crontab para usuario zabbix; offsite pendiente.

## Docs

- Desactualizados: `zbx-in-docker/README.md` (sin hub/MCP/Telegram/simulator), `noc-agent/docs/arquitectura-resumen.md`
  (apunta a ubicación vieja del diseño canónico).
- Parcial: runbook de upgrade (`instalacion.md`, 3 pasos sin backup/restore/verificación).
- Faltantes: doc de operación del MCP (runbook operativo + rotación de tokens), troubleshooting general,
  doc de backups automáticos/offsite, runbook de rotación de secretos.

## Roadmap sugerido (Fase siguiente)

1. Cerrar brechas de seguridad alta/media (permisos, rotación token MCP, `settings.url`, TLS).
2. Automatizar backups + offsite con cron y doc.
3. Operativizar MCP: doc de operación, rotación de tokens, VM dedicada fuera del compose.
4. Baseline de datos (dejar correr simulator ≥30d) + ETL trends→DB para Excel sin LLM.
5. Orquestador L0/L1 + adapter Discord (Fase 3/4); evaluar n8n vs scripts (ver auditoría en chat).
